"""Handlers with definitions bundles: components, joins, statuses, cleanup and full renders."""

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
from test_event_driven_reconciliation import FakeApp as StatusApp, healthy_status, run_update_status, use_fake_app


@pytest.fixture(autouse=True)
def operator_settings(monkeypatch):
    monkeypatch.setattr(KasprApp, "conf", Settings(), raising=False)


@pytest.fixture
def posted(monkeypatch):
    events = []
    monkeypatch.setattr(kopf, "event", lambda obj, **kw: events.append(("event", kw["reason"])))
    monkeypatch.setattr(kopf, "warn", lambda obj, **kw: events.append(("warn", kw["reason"])))
    return events


def fake_app_api(monkeypatch, module, app_body, stateful_set=None):
    """Serve the app and its StatefulSet; returns the StatefulSet names read."""
    reads = []

    async def fetch_stateful_set(api, name, namespace):
        reads.append(name)
        return stateful_set

    class FakeKasprApp:
        @staticmethod
        def default():
            apps = KasprApp.default()
            apps.__dict__["apps_v1_api"] = None
            apps.fetch = AsyncMock(return_value=app_body)
            apps.fetch_stateful_set = fetch_stateful_set
            return apps

    monkeypatch.setattr(module, "KasprApp", FakeKasprApp)
    return reads


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
    reads = fake_app_api(monkeypatch, component_handler, BUNDLE_APP)
    component = webview_component()
    reported = {"app": {"name": APP, "status": "AppFound"}, "configMap": "page-webview", "hash": component.hash}

    bundled, status = run_component(component, reported)

    assert bundled is True
    component.synchronize.assert_not_awaited()
    assert status == {"configMap": None}
    assert reads == []  # the annotation decides


def test_a_component_of_a_components_app_reports_as_before(monkeypatch, posted):
    reads = fake_app_api(monkeypatch, component_handler, COMPONENTS_APP, app_with().stateful_set)
    component = webview_component()

    bundled, status = run_component(component, {})

    assert bundled is False
    component.synchronize.assert_awaited_once()
    assert status == {
        "app": {"name": APP, "status": "AppFound"},
        "configMap": "page-webview",
        "hash": component.hash,
    }
    assert reads == [f"{APP}-app"]


def test_a_component_of_an_unannotated_app_follows_its_pods(monkeypatch, posted):
    fake_app_api(monkeypatch, component_handler, COMPONENTS_APP, app_with().render_stateful_set(d.BUNDLE))
    component = webview_component()

    bundled, _ = run_component(component, {})

    assert bundled is True
    component.synchronize.assert_not_awaited()


@pytest.mark.parametrize("default, bundled", [("bundle", True), ("components", False)])
def test_a_component_of_an_app_without_pods_follows_the_default(monkeypatch, posted, default, bundled):
    monkeypatch.setattr(KasprApp, "conf", Settings(definitions_delivery_default=default), raising=False)
    fake_app_api(monkeypatch, component_handler, COMPONENTS_APP)

    assert run_component(webview_component(), {})[0] is bundled


def test_a_component_without_its_app_writes_its_config_map(monkeypatch, posted):
    reads = fake_app_api(monkeypatch, component_handler, None)
    component = webview_component()

    bundled, _ = run_component(component, {})

    assert bundled is False
    component.synchronize.assert_awaited_once()
    assert reads == []


def test_a_component_back_to_its_own_config_map_reports_it(monkeypatch, posted):
    fake_app_api(monkeypatch, component_handler, COMPONENTS_APP, app_with().stateful_set)
    component = webview_component()
    reported = {"app": {"name": APP, "status": "AppFound"}, "hash": component.hash}

    _, status = run_component(component, reported)

    component.synchronize.assert_awaited_once()
    assert status == {"configMap": "page-webview"}


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


def test_a_join_of_a_components_app_is_not_delivered_and_says_so_each_time(monkeypatch, posted):
    status, written = run_join(monkeypatch, COMPONENTS_APP, status={})

    assert written == []
    assert set(status) == {"app", "hash", "leftTable", "rightTable"}
    assert status["leftTable"]["status"] == "LeftTableFound"
    assert status["rightTable"]["status"] == "RightTableFound"
    assert posted.count(("warn", "NotDelivered")) == 1

    again, _ = run_join(monkeypatch, COMPONENTS_APP, status=status)
    assert again == {}
    assert posted.count(("warn", "NotDelivered")) == 2


def test_a_join_of_a_bundle_app_is_delivered(monkeypatch, posted):
    status, written = run_join(monkeypatch, BUNDLE_APP, status={}, tables_of_app=("orders",))

    assert written == []
    assert set(status) == {"app", "hash", "leftTable", "rightTable"}
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


def test_the_app_status_reports_nothing_about_definitions(monkeypatch):
    """How an app delivers shows in its StatefulSet and ConfigMaps, not in its status."""
    use_fake_app(monkeypatch, StatusApp(actual_status=healthy_status()))
    case_join = join_doc()
    related = {
        "agents": [],
        "webviews": [],
        "tables": [],
        "tasks": [],
        "joins": [case_join],
        "delivered_joins": [case_join["metadata"]["name"]],
        "success": True,
        "hashes": {},
    }

    changes = run_update_status({}, handler.AppRuntimeState(), related_resources=related)

    assert "definitions" not in changes
    assert [c["type"] for c in changes.get("conditions", []) if "Join" in c["type"]] == []


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
        "delivered_joins": [case_join["metadata"]["name"]] if joins and mode == "bundle" else [],
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
        self.joins = []
        self.calls = []
        self.waiting = list(waiting)

    async def clean_up_definitions(self, mode, desired, config_maps=None):
        self.calls.append((mode, set(desired), config_maps))
        return CleanupPlan(waiting=self.waiting, reason="a rollout is in progress" if self.waiting else None)


def clean_up(app, config_maps):
    state = handler.AppRuntimeState()
    asyncio.run(handler._clean_up_definitions(app, config_maps, state, APP, "ns", {}, Mock()))
    return state


def test_a_components_app_without_components_lists_its_config_maps():
    """Shards left from bundle mode are found from the cluster, whatever the app's status says."""
    app = CleanupApp("components")

    state = clean_up(app, None)

    assert app.calls == [("components", {"desired"}, None)]
    assert state.definitions_cleanup is None


def test_a_components_app_reuses_the_listing_of_its_definitions_sync():
    app = CleanupApp("components")
    listing = ["listed"]

    clean_up(app, listing)

    assert app.calls == [("components", {"desired"}, listing)]


def test_waiting_config_maps_are_retried_on_status_refreshes():
    app = CleanupApp("bundle", waiting=["old"])

    state = clean_up(app, [])

    assert state.definitions_cleanup == ("bundle", frozenset({"desired"}))

    app.waiting = []
    asyncio.run(handler._refresh_definitions_cleanup(app, state, APP, "ns", {}, Mock()))
    assert state.definitions_cleanup is None


def test_a_status_refresh_retries_waiting_deletions_and_writes_no_status_for_them(monkeypatch):
    status_app = StatusApp(actual_status=healthy_status())
    status_app.calls = []
    status_app.waiting = []
    status_app.clean_up_definitions = CleanupApp.clean_up_definitions.__get__(status_app)
    use_fake_app(monkeypatch, status_app)
    state = handler.AppRuntimeState()
    state.definitions_cleanup = ("bundle", frozenset({"desired"}))

    changes = run_update_status({}, state)

    assert status_app.calls == [("bundle", {"desired"}, None)]
    assert state.definitions_cleanup is None
    assert "definitions" not in changes


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
    component.config_map_status = lambda bundled: KasprWebView.config_map_status(component, bundled)

    async def patch_status(fields):
        component.patched.append(fields)
        return {}

    component.patch_status = patch_status
    return component


def report(app, changes=False):
    deployed = "components" if app.definitions_delivery == "bundle" else "bundle"
    delivery = Delivery(app.definitions_delivery, deployed if changes else app.definitions_delivery, "annotation")
    asyncio.run(handler._report_definitions_to_components(app, delivery, Mock()))


def test_components_of_a_components_app_are_left_alone():
    legacy = reported_component("KasprWebView", "page", {"app": {}, "configMap": "page-webview"})
    app = SimpleNamespace(definitions_delivery="components", agents=[], webviews=[legacy], tables=[], tasks=[], joins=[])

    report(app)

    assert legacy.patched == []


def test_components_hear_of_a_switch_to_bundles_and_back():
    component = reported_component("KasprWebView", "page", {"app": {}, "configMap": "page-webview"})
    app = SimpleNamespace(definitions_delivery="bundle", agents=[], webviews=[component], tables=[], tasks=[], joins=[])

    report(app, changes=True)
    assert component.patched == [{"configMap": None}]

    component.owner["status"] = {"app": {}}  # the ConfigMap removed by that patch
    component.patched.clear()
    app.definitions_delivery = "components"
    report(app, changes=True)
    assert component.patched == [{"configMap": "page-webview"}]


def reported_join():
    doc = join_doc()
    join = KasprJoin.from_spec(doc["metadata"]["name"], "KasprJoin", "ns", KasprJoinSpecSchema().load(doc["spec"]), doc["metadata"]["labels"])
    join.owner = {"metadata": {"name": join.cluster}, "status": {"app": {"name": APP, "status": "AppFound"}}}
    join.patched = []

    async def patch_status(fields):
        join.patched.append(fields)
        return {}

    join.patch_status = patch_status
    return join


def test_joins_hear_their_tables(posted):
    join = reported_join()
    table = SimpleNamespace(cluster="orders", owner={}, WRITES_CONFIG_MAP=True)  # has not reported yet
    app = SimpleNamespace(definitions_delivery="bundle", agents=[], webviews=[], tables=[table], tasks=[], joins=[join])

    report(app)

    [fields] = join.patched
    assert set(fields) == {"leftTable", "rightTable"}
    assert fields["leftTable"]["status"] == "LeftTableFound"
    assert fields["rightTable"]["status"] == "RightTableNotFound"
    assert posted == []


@pytest.mark.parametrize("changes, warned", [(True, True), (False, False)])
def test_joins_are_warned_when_their_app_stops_delivering_bundles(posted, changes, warned):
    join = reported_join()
    app = SimpleNamespace(definitions_delivery="components", agents=[], webviews=[], tables=[], tasks=[], joins=[join])

    report(app, changes=changes)

    assert (("warn", "NotDelivered") in posted) is warned


def test_a_switch_to_components_names_the_joins_it_leaves_out(monkeypatch):
    events = []
    monkeypatch.setattr(handler, "_post_app_event", lambda *args: events.append(args[3:6]))
    app = SimpleNamespace(agents=[], webviews=[], tables=[], tasks=[], joins=[reported_join()])

    handler._post_delivery_events(app, APP, "ns", {}, Delivery("components", "bundle", "annotation"), Mock())
    handler._post_delivery_events(app, APP, "ns", {}, Delivery("bundle", "components", "annotation"), Mock())

    [(_, reason, to_components), (_, _, to_bundle)] = events
    assert reason == "DefinitionsDeliveryChanged"
    assert app.joins[0].cluster in to_components and "not delivered" in to_components
    assert "KasprJoins" not in to_bundle


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


def test_an_app_without_components_reports_no_delivery_change(monkeypatch):
    """Both modes render its pod template alike, so its StatefulSet always reads as
    components mode: a bundle annotation must not report a change on every reconciliation."""
    events = []
    monkeypatch.setattr(handler, "_post_app_event", lambda *args: events.append(args[4]))
    app = app_with(components=[], annotations={d.DELIVERY_ANNOTATION: "bundle"})
    live = app.render_stateful_set(d.BUNDLE)

    delivery = app.resolve_definitions_delivery(live)
    handler._post_delivery_events(app, APP, "ns", {}, delivery, Mock())

    assert delivery.mode == d.BUNDLE
    assert events == []
