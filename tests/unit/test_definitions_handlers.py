"""Handlers with definitions bundles: components, joins, status, cleanup and full renders."""

import asyncio
import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import kopf
import pytest
from kubernetes_asyncio.client import ApiException

from kaspr.handlers import appcomponent as component_handler
from kaspr.handlers import kasprapp as handler
from kaspr.handlers import kasprjoin as join_handler
from kaspr.resources import KasprJoin, KasprWebView
from kaspr.resources import definitions as d
from kaspr.resources.definitions import CleanupPlan, Delivery
from kaspr.resources.kasprapp import KasprApp
from kaspr.types.schemas import KasprJoinSpecSchema, KasprWebViewSpecSchema
from kaspr.types.settings import Settings
from definitions_fixtures import APP, app_with, every_component_case, webview_doc


@pytest.fixture(autouse=True)
def operator_settings(monkeypatch):
    monkeypatch.setattr(KasprApp, "conf", Settings(), raising=False)


@pytest.fixture
def posted(monkeypatch):
    events = []
    monkeypatch.setattr(kopf, "event", lambda obj, **kw: events.append(("event", kw["reason"])))
    monkeypatch.setattr(kopf, "warn", lambda obj, **kw: events.append(("warn", kw["reason"])))
    return events


def fake_app_api(monkeypatch, module, app_body):
    class FakeKasprApp:
        @staticmethod
        def default():
            return SimpleNamespace(fetch=AsyncMock(return_value=app_body))

    monkeypatch.setattr(module, "KasprApp", FakeKasprApp)


BUNDLE_APP = {"kind": "KasprApp", "metadata": {"annotations": {d.DELIVERY_ANNOTATION: "bundle"}}}
COMPONENTS_APP = {"kind": "KasprApp", "metadata": {}}


def webview_component():
    doc = webview_doc("page")
    component = KasprWebView.from_spec(
        "page", "KasprWebView", "ns", KasprWebViewSpecSchema().load(doc["spec"]), dict(doc["metadata"]["labels"])
    )
    component.synchronize = AsyncMock()
    return component


def run_component(component, status):
    patch = kopf.Patch()
    bundled = asyncio.run(
        component_handler.reconcile_component(
            component,
            body={"metadata": {"name": component.cluster}},
            status=status,
            patch=patch,
            namespace="ns",
            generation=1,
            reason="update",
            logger=Mock(),
        )
    )
    return bundled, dict(patch.get("status", {}))


# ---------------------------------------------------------------------------
# Components
# ---------------------------------------------------------------------------


def test_a_component_of_a_bundle_app_writes_no_config_map(monkeypatch, posted):
    fake_app_api(monkeypatch, component_handler, BUNDLE_APP)
    component = webview_component()
    reported = {"app": {"name": APP, "status": "AppFound"}, "configMap": "page-webview", "hash": component.hash}

    bundled, status = run_component(component, reported)

    assert bundled is True
    component.synchronize.assert_not_awaited()
    assert status == {"configMap": None, "delivery": "bundle"}


def test_a_component_of_a_components_app_reports_as_before(monkeypatch, posted):
    fake_app_api(monkeypatch, component_handler, COMPONENTS_APP)
    component = webview_component()

    bundled, status = run_component(component, {})

    assert bundled is False
    component.synchronize.assert_awaited_once()
    assert status == {
        "app": {"name": APP, "status": "AppFound"},
        "configMap": "page-webview",
        "hash": component.hash,
    }


def test_a_component_back_to_its_own_config_map_drops_the_delivery(monkeypatch, posted):
    fake_app_api(monkeypatch, component_handler, COMPONENTS_APP)
    component = webview_component()
    reported = {"app": {"name": APP, "status": "AppFound"}, "delivery": "bundle", "hash": component.hash}

    _, status = run_component(component, reported)

    component.synchronize.assert_awaited_once()
    assert status == {"configMap": "page-webview", "delivery": None}


# ---------------------------------------------------------------------------
# Joins
# ---------------------------------------------------------------------------


def join_doc():
    _, docs = every_component_case()
    doc = copy.deepcopy(next(c for c in docs if c["kind"] == "KasprJoin"))
    doc["metadata"]["labels"]["kaspr.io/app"] = APP
    return doc


def run_join(monkeypatch, app_body, status, tables_of_app=("orders", "products")):
    fake_app_api(monkeypatch, component_handler, app_body)

    async def fetch_table(name, namespace):
        if name in tables_of_app:
            return {"metadata": {"name": name, "labels": {"kaspr.io/app": APP}}}
        return {"metadata": {"name": name, "labels": {"kaspr.io/app": "other"}}}

    monkeypatch.setattr(join_handler.KasprTable, "default", lambda: SimpleNamespace(fetch=fetch_table))
    written = []
    monkeypatch.setattr(KasprJoin, "sync_config_map", AsyncMock(side_effect=lambda *a, **k: written.append(a)))
    doc = join_doc()
    patch = kopf.Patch()
    asyncio.run(
        join_handler.reconciliation(
            body=doc,
            spec=doc["spec"],
            name=doc["metadata"]["name"],
            namespace="ns",
            logger=Mock(),
            labels=doc["metadata"]["labels"],
            patch=patch,
            meta={"generation": 1},
            status=status,
        )
    )
    return dict(patch.get("status", {})), written


def test_a_join_of_a_components_app_is_not_delivered_and_says_so(monkeypatch, posted):
    status, written = run_join(monkeypatch, COMPONENTS_APP, status={})

    assert written == []
    assert status["delivery"] == "notDelivered"
    assert "configMap" not in status or status["configMap"] is None
    assert status["leftTable"]["status"] == "LeftTableFound"
    assert status["rightTable"]["status"] == "RightTableFound"
    assert ("warn", "NotDelivered") in posted


def test_a_join_of_a_bundle_app_is_delivered(monkeypatch, posted):
    status, written = run_join(monkeypatch, BUNDLE_APP, status={}, tables_of_app=("orders",))

    assert written == []
    assert status["delivery"] == "bundle"
    assert status["rightTable"]["status"] == "RightTableNotFound"
    assert ("warn", "NotDelivered") not in posted
    assert ("warn", "RightTableNotFound") in posted


@pytest.mark.parametrize("code", [403, 404])
def test_joins_list_as_none_without_their_crd_or_permission(monkeypatch, code):
    monkeypatch.setattr(
        handler.KasprJoin, "default", lambda: SimpleNamespace(search=AsyncMock(side_effect=ApiException(status=code)))
    )

    assert asyncio.run(handler._search_joins("ns", APP)) == {"items": []}


def test_other_join_listing_errors_stop_the_reconciliation(monkeypatch):
    monkeypatch.setattr(
        handler.KasprJoin, "default", lambda: SimpleNamespace(search=AsyncMock(side_effect=ApiException(status=500)))
    )
    for kind in (handler.KasprAgent, handler.KasprWebView, handler.KasprTable, handler.KasprTask):
        monkeypatch.setattr(kind, "default", lambda: SimpleNamespace(search=AsyncMock(return_value={"items": []})))

    related = asyncio.run(handler.fetch_app_related_resources(APP, "ns"))

    assert related["success"] is False


def test_an_invalid_join_is_left_out_of_the_app():
    good = join_doc()
    bad = copy.deepcopy(good)
    bad["metadata"]["name"] = "broken"
    bad["spec"] = {"leftTable": "orders"}
    app = KasprApp.default()  # as on_delete builds it: no logger of its own
    related = {"agents": [], "webviews": [], "tables": [], "tasks": [], "joins": [good, bad], "success": True}

    assert asyncio.run(handler.attach_app_related_resources(app, APP, "ns", related=related)) is True
    assert [j.cluster for j in app.joins] == [good["metadata"]["name"]]


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


def shard(name="s", components=3, size=100):
    return SimpleNamespace(name=name, components=components, size=size)


@pytest.mark.parametrize(
    "info, expected",
    [
        (dict(mode="components", shards=[], waiting=0), None),
        (dict(mode="components", shards=[], waiting=2), {"delivery": "components", "pendingDeletion": 2}),
        (
            dict(mode="bundle", shards=[shard("a", 2, 10), shard("b", 3, 20)], waiting=0),
            {"delivery": "bundle", "configMaps": ["a", "b"], "components": 5, "bytes": 30},
        ),
        (
            dict(mode="bundle", shards=[shard("a")], waiting=1),
            {"delivery": "bundle", "configMaps": ["a"], "components": 3, "bytes": 100, "pendingDeletion": 1},
        ),
    ],
)
def test_definitions_status(info, expected):
    assert handler._definitions_status(info) == expected


def test_an_app_without_joins_gets_no_joins_condition():
    status_update = {}

    changed = handler._update_joins_condition(status_update, {"conditions": [{"type": "Ready"}]}, dict(mode="components", joins=[]), 1)

    assert changed is None and status_update == {}


def test_a_components_app_with_joins_is_told_they_are_not_delivered():
    status_update = {}

    changed = handler._update_joins_condition(status_update, {}, dict(mode="components", joins=["j1"]), 1)

    assert changed["status"] == "False" and changed["reason"] == "RequiresBundleDelivery"
    assert "j1" in changed["message"]
    [condition] = status_update["conditions"]
    assert condition["type"] == "JoinsDelivered"
    again = {}
    assert handler._update_joins_condition(again, {"conditions": status_update["conditions"]}, dict(mode="components", joins=["j1"]), 1) is None


def test_joins_condition_turns_true_in_bundle_mode_and_goes_with_the_joins():
    current = {}
    handler._update_joins_condition(current, {}, dict(mode="components", joins=["j1"]), 1)
    status_update = {}

    changed = handler._update_joins_condition(status_update, current, dict(mode="bundle", joins=["j1"]), 1)
    assert changed["status"] == "True" and changed["reason"] == "Bundled"

    removed = {}
    handler._update_joins_condition(removed, status_update, dict(mode="bundle", joins=[]), 1)
    assert removed["conditions"] == []


def linked_status(mode, current=None, joins=("orders-products-join",)):
    case_join = join_doc()
    related = {
        "agents": [],
        "webviews": [],
        "tables": [],
        "tasks": [],
        "joins": [case_join] if joins else [],
        "success": True,
        "hashes": {"joins": {case_join["metadata"]["name"]: "h1"}},
        "definitions": {"mode": mode, "joins": [case_join["metadata"]["name"]] if joins else []},
    }
    app = SimpleNamespace(static_group_membership_enabled=True)
    status_update = {}
    changed = handler._update_linked_resources_status(status_update, current or {}, app, related, APP, Mock())
    return status_update, changed


def test_delivered_joins_are_linked_resources_and_changes_require_a_rebalance():
    first, changed = linked_status("bundle")
    assert changed is False
    assert [j["name"] for j in first["linkedResources"]["joins"]] == [join_doc()["metadata"]["name"]]

    baseline = {"linkedResources": {"agents": [], "webviews": [], "tables": [], "tasks": []}}
    update, changed = linked_status("bundle", current=baseline)
    assert changed is True and update["rebalanceRequired"] is True


def test_undelivered_joins_leave_linked_resources_as_they_were():
    baseline = {"linkedResources": {"agents": [], "webviews": [], "tables": [], "tasks": []}}

    update, changed = linked_status("components", current=baseline)

    assert changed is False and update == {}


# ---------------------------------------------------------------------------
# Cleanup triggers
# ---------------------------------------------------------------------------


class CleanupApp:
    def __init__(self, mode, waiting=()):
        self.definitions_delivery = mode
        self.desired_definitions_config_maps = {"desired"}
        self.definition_shards = [shard("desired")] if mode == "bundle" else []
        self.joins = []
        self.calls = []
        self.waiting = list(waiting)

    async def clean_up_definitions(self, mode, desired, config_maps=None):
        self.calls.append((mode, set(desired), config_maps))
        return CleanupPlan(waiting=self.waiting, reason="a rollout is in progress" if self.waiting else None)


def clean_up(app, config_maps, status):
    state = handler.AppRuntimeState()
    info = asyncio.run(handler._clean_up_definitions(app, config_maps, status, state, APP, "ns", {}, Mock()))
    return info, state


def test_a_components_app_without_components_or_shards_makes_no_call():
    app = CleanupApp("components")

    info, state = clean_up(app, None, {})

    assert app.calls == [] and state.definitions_cleanup is None
    assert handler._definitions_status(info) is None


def test_a_components_app_reuses_the_listing_of_its_definitions_sync():
    app = CleanupApp("components")
    listing = ["listed"]

    clean_up(app, listing, {})

    assert app.calls == [("components", {"desired"}, listing)]


def test_a_components_app_that_had_bundles_lists_its_config_maps():
    app = CleanupApp("components")

    clean_up(app, None, {"definitions": {"delivery": "components", "pendingDeletion": 1}})

    assert app.calls == [("components", {"desired"}, None)]


def test_waiting_config_maps_are_retried_on_status_refreshes():
    app = CleanupApp("bundle", waiting=["old"])

    info, state = clean_up(app, [], {})

    assert state.definitions_cleanup == ("bundle", frozenset({"desired"}))
    assert info["waiting"] == 1

    app.waiting = []
    status_update = {}
    asyncio.run(
        handler._refresh_definitions_cleanup(
            app, status_update, {"definitions": {"delivery": "bundle", "pendingDeletion": 1}}, state, APP, "ns", {}, Mock()
        )
    )
    assert state.definitions_cleanup is None
    # A merge patch keeps what it leaves out: the count must be removed explicitly.
    assert status_update["definitions"] == {"delivery": "bundle", "pendingDeletion": None}


def test_a_components_app_drops_its_definitions_status_once_clean():
    app = CleanupApp("components")
    state = handler.AppRuntimeState()
    state.definitions_cleanup = ("components", frozenset({"desired"}))
    status_update = {}

    asyncio.run(
        handler._refresh_definitions_cleanup(
            app, status_update, {"definitions": {"delivery": "components", "pendingDeletion": 3}}, state, APP, "ns", {}, Mock()
        )
    )

    assert status_update["definitions"] is None


# ---------------------------------------------------------------------------
# Component statuses reported by the app
# ---------------------------------------------------------------------------


def reported_component(cls, name, status, wrote=True):
    component = SimpleNamespace(
        owner={"metadata": {"name": name}, "status": status},
        WRITES_CONFIG_MAP=wrote,
        KIND=cls,
        cluster=name,
        app_name=APP,
        config_map_name=f"{name}-webview",
        patched=[],
    )
    component.definitions_status = lambda bundled: KasprWebView.definitions_status(component, bundled)

    async def patch_status(fields):
        component.patched.append(fields)
        return {}

    component.patch_status = patch_status
    return component


def report(app):
    asyncio.run(handler._report_definitions_to_components(app, Mock()))


def test_components_of_a_components_app_are_left_alone():
    legacy = reported_component("KasprWebView", "page", {"app": {}, "configMap": "page-webview"})
    app = SimpleNamespace(definitions_delivery="components", agents=[], webviews=[legacy], tables=[], tasks=[], joins=[])

    report(app)

    assert legacy.patched == []


def test_components_hear_of_a_switch_to_bundles_and_back():
    component = reported_component("KasprWebView", "page", {"app": {}, "configMap": "page-webview"})
    app = SimpleNamespace(definitions_delivery="bundle", agents=[], webviews=[component], tables=[], tasks=[], joins=[])

    report(app)
    assert component.patched == [{"configMap": None, "delivery": "bundle"}]

    component.owner["status"] = {"app": {}, "delivery": "bundle"}
    component.patched.clear()
    app.definitions_delivery = "components"
    report(app)
    assert component.patched == [{"configMap": "page-webview", "delivery": None}]


def test_joins_hear_their_delivery_and_tables(posted):
    doc = join_doc()
    join = KasprJoin.from_spec(doc["metadata"]["name"], "KasprJoin", "ns", KasprJoinSpecSchema().load(doc["spec"]), doc["metadata"]["labels"])
    join.owner = {"metadata": {"name": join.cluster}, "status": {"app": {"name": APP, "status": "AppFound"}}}
    patched = []

    async def patch_status(fields):
        patched.append(fields)
        return {}

    join.patch_status = patch_status
    table = SimpleNamespace(cluster="orders", owner={}, WRITES_CONFIG_MAP=True)  # has not reported yet
    app = SimpleNamespace(definitions_delivery="components", agents=[], webviews=[], tables=[table], tasks=[], joins=[join])

    report(app)

    [fields] = patched
    assert fields["delivery"] == "notDelivered"
    assert fields["leftTable"]["status"] == "LeftTableFound"
    assert fields["rightTable"]["status"] == "RightTableNotFound"
    assert ("warn", "NotDelivered") in posted


# ---------------------------------------------------------------------------
# Handlers writing the whole pod template
# ---------------------------------------------------------------------------


def test_a_full_render_needs_every_component(monkeypatch):
    monkeypatch.setattr(handler, "attach_app_related_resources", AsyncMock(return_value=False))

    with pytest.raises(kopf.TemporaryError):
        asyncio.run(handler._prepare_full_rendering(SimpleNamespace(), APP, "ns"))


@pytest.mark.parametrize(
    "handler_name, method, extra",
    [
        ("on_replicas_update", "patch_replicas", {"body": {}}),
        ("on_storage_size_update", "patch_storage_size", {}),
        ("on_template_pod_updated", "patch_template_pod", {}),
    ],
)
def test_handlers_writing_the_whole_template_render_the_components_first(monkeypatch, handler_name, method, extra):
    calls = []

    async def prepared(app, name, namespace):
        calls.append("prepare")

    monkeypatch.setattr(handler, "_prepare_full_rendering", prepared)
    monkeypatch.setattr(handler.KasprAppSpecSchema, "load", lambda self, value: object())

    class FakeApp:
        reconciliation_paused = False

    async def patched(self):
        calls.append(method)

    setattr(FakeApp, method, patched)
    monkeypatch.setattr(handler.KasprApp, "from_spec", classmethod(lambda cls, *a, **k: FakeApp()))

    asyncio.run(
        getattr(handler, handler_name)(
            old=None, new=None, diff=(), spec={}, name=APP, meta={}, patch=SimpleNamespace(status={}),
            status={}, namespace="ns", annotations={}, logger=Mock(), **extra,
        )
    )

    assert calls == ["prepare", method]


def test_scaling_keeps_the_definitions_in_the_template(monkeypatch):
    """Before, scaling up synchronized a StatefulSet rendered without the components."""
    app_doc, docs = every_component_case()
    live = app_with().stateful_set
    patches = []

    async def attach(app, name, namespace, related=None):
        built = app_with()
        for kind in ("agents", "webviews", "tables", "tasks", "joins"):
            getattr(app, f"with_{kind}")(getattr(built, kind))
        return True

    monkeypatch.setattr(handler, "attach_app_related_resources", attach)
    monkeypatch.setattr(KasprApp, "unite", lambda self: None)
    monkeypatch.setattr(KasprApp, "sync_hpa", AsyncMock())
    monkeypatch.setattr(KasprApp, "sensor", Mock(), raising=False)
    monkeypatch.setattr(KasprApp, "apps_v1_api", None)
    monkeypatch.setattr(KasprApp, "fetch_stateful_set", AsyncMock(return_value=copy.deepcopy(live)))
    monkeypatch.setattr(KasprApp, "patch_stateful_set", AsyncMock(side_effect=lambda *a, **k: patches.append(k)))
    spec = copy.deepcopy(app_doc["spec"])
    spec.update(image="kasprio/kaspr:0.11.31")

    asyncio.run(
        handler.on_replicas_update(
            body={}, old=3, new=3, diff=(), spec=spec, name=APP, meta={}, patch=SimpleNamespace(status={}),
            status={}, namespace="legacy-rendering", annotations={}, logger=Mock(),
        )
    )

    assert patches == []


def test_status_definitions_drops_keys_the_new_value_lacks():
    current = {"delivery": "bundle", "configMaps": ["a"], "components": 3, "bytes": 10, "pendingDeletion": 2}

    assert handler._merge_patch_value(current, {"delivery": "components", "pendingDeletion": 1}) == {
        "delivery": "components",
        "pendingDeletion": 1,
        "configMaps": None,
        "components": None,
        "bytes": None,
    }
    assert handler._merge_patch_value(current, None) is None
    assert handler._merge_patch_value(None, {"delivery": "bundle"}) == {"delivery": "bundle"}


def test_reconcile_status_clears_the_pending_count():
    status = {"definitions": {"delivery": "bundle", "configMaps": ["s"], "components": 3, "bytes": 100, "pendingDeletion": 7}}
    desired = handler._definitions_status(dict(mode="bundle", shards=[shard("s")], waiting=0))

    assert handler._merge_patch_value(status["definitions"], desired)["pendingDeletion"] is None


def test_a_delivered_joins_internal_topics_are_subscriptions():
    """Without them a rebalance after delivering a join would look unnecessary."""
    from kaspr.utils.subscriptions import check_assignment, subscribed_topics, subscription_change

    linked = {"joins": [{"name": "j", "leftTable": "orders", "rightTable": "products"}]}
    expected = {
        f"probe-app-orders-products-{suffix}"
        for suffix in (
            "subscription-registration",
            "subscription-response",
            "subscriptions-changelog",
            "previous-fk-changelog",
        )
    }

    assert subscribed_topics(linked, "probe") == expected
    assert subscription_change({}, linked, "probe").added == expected
    assert subscription_change(linked, {}, "probe").removed == expected
    members = [{"assignment": {"actives": {"probe-orders": [0]}, "standbys": {}}, "rebalancing": False}]
    check = check_assignment(members, subscribed_topics(linked, "probe"))
    assert not check.satisfied and check.unassigned == sorted(expected)
