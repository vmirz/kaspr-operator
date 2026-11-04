"""Definitions bundles: shards, names, documents, the delivery mode, and cleanup planning."""

import copy

import pytest
import yaml
from kubernetes_asyncio.client import V1ResourceRequirements

from kaspr.resources import definitions as d
from kaspr.resources.kasprapp import KasprApp
from kaspr.types.settings import Settings
from definitions_fixtures import (
    APP,
    app_with,
    component_config_map,
    config_map,
    per_component_items,
    pod_mounting,
    shard_config_map,
    webview_doc,
    with_status,
)


@pytest.fixture(autouse=True)
def operator_settings(monkeypatch):
    monkeypatch.setattr(KasprApp, "conf", Settings(), raising=False)


def kinds(app):
    return {
        "agents": app.agents,
        "webviews": app.webviews,
        "tables": app.tables,
        "tasks": app.tasks,
        "joins": app.joins,
    }


# ---------------------------------------------------------------------------
# Shards
# ---------------------------------------------------------------------------


def test_one_shard_holds_every_component_as_its_own_config_map_does():
    app = app_with()
    shards = d.build_shards(app.component_name, kinds(app), d.DEFAULT_SHARD_BYTES)

    assert len(shards) == 1
    document = yaml.safe_load(shards[0].document)
    expected = per_component_items(app)
    for kind, specs in expected.items():
        by_name = lambda items: sorted(items, key=lambda spec: spec["name"])
        assert by_name(document[kind]) == by_name(specs), kind
    assert set(document) == set(expected)
    assert shards[0].components == sum(len(specs) for specs in expected.values())
    assert app.joins, "the example app has a join, which bundles deliver"


def test_kinds_are_sorted_by_name_whatever_the_listing_order():
    app = app_with()
    reversed_kinds = {kind: list(reversed(items)) for kind, items in kinds(app).items()}

    forward = d.build_shards(app.component_name, kinds(app), d.DEFAULT_SHARD_BYTES)
    backward = d.build_shards(app.component_name, reversed_kinds, d.DEFAULT_SHARD_BYTES)

    assert [s.document for s in forward] == [s.document for s in backward]
    document = yaml.safe_load(forward[0].document)
    for kind, specs in document.items():
        assert [spec["name"] for spec in specs] == sorted(spec["name"] for spec in specs)


def test_shard_names_are_the_app_and_the_document_digest():
    app = app_with()
    shard = d.build_shards(app.component_name, kinds(app), d.DEFAULT_SHARD_BYTES)[0]

    assert shard.name.startswith(f"{APP}-app-definitions-")
    assert shard.name == d.shard_name(app.component_name, shard.document)
    assert len(shard.name.rsplit("-", 1)[1]) == 10


def test_a_changed_component_is_a_new_shard_name():
    before = app_with(extra=[webview_doc("status")])
    after = app_with(extra=[webview_doc("status", code_bytes=300)])

    first = d.build_shards(before.component_name, kinds(before), d.DEFAULT_SHARD_BYTES)
    second = d.build_shards(after.component_name, kinds(after), d.DEFAULT_SHARD_BYTES)

    assert first[0].name != second[0].name


def test_webviews_spill_into_further_shards_and_everything_else_stays_in_the_first():
    extra = [webview_doc(f"page-{i:02d}", code_bytes=20_000) for i in range(12)]
    app = app_with(extra=extra)
    budget = 64 * 1024

    shards = d.build_shards(app.component_name, kinds(app), budget)

    assert len(shards) > 1
    first = yaml.safe_load(shards[0].document)
    for kind in d.CORE_KINDS:
        assert len(first.get(kind) or []) == len(kinds(app)[kind]), kind
    for shard in shards[1:]:
        assert set(yaml.safe_load(shard.document)) == {"webviews"}
    webview_names = [
        spec["name"] for shard in shards for spec in yaml.safe_load(shard.document).get("webviews", [])
    ]
    assert webview_names == sorted(w.cluster for w in app.webviews)
    assert all(shard.size <= budget + 25_000 for shard in shards[1:])
    assert [shard.index for shard in shards] == list(range(len(shards)))
    assert len({shard.name for shard in shards}) == len(shards)


def test_a_shard_over_the_hard_limit_fails(monkeypatch):
    app = app_with()
    monkeypatch.setattr(d, "HARD_LIMIT_BYTES", 1000)

    with pytest.raises(d.DefinitionsTooLarge):
        d.build_shards(app.component_name, kinds(app), d.DEFAULT_SHARD_BYTES)


def test_an_app_without_components_has_no_shards():
    app = app_with(components=[])

    assert d.build_shards(app.component_name, kinds(app), d.DEFAULT_SHARD_BYTES) == []


def test_shard_config_map_is_immutable_labelled_and_holds_the_document():
    app = app_with()
    shard = d.build_shards(app.component_name, kinds(app), d.DEFAULT_SHARD_BYTES)[0]

    cm = d.prepare_shard_config_map(shard, "ns", {"kaspr.io/app": APP, "x": "y"})

    assert cm.immutable is True
    assert cm.metadata.name == shard.name
    assert cm.metadata.labels == {"kaspr.io/app": APP, "x": "y", "kaspr.io/component": "definitions"}
    assert cm.metadata.annotations == {
        "kaspr.io/definitions-shard": "0",
        "kaspr.io/definitions-components": str(shard.components),
    }
    assert cm.data == {"definitions.yaml": shard.document}


def test_each_shard_is_one_volume_and_one_subpath_mount():
    extra = [webview_doc(f"page-{i:02d}", code_bytes=20_000) for i in range(12)]
    app = app_with(extra=extra)
    shards = d.build_shards(app.component_name, kinds(app), 64 * 1024)

    volumes = d.prepare_shard_volumes(shards)
    mounts = d.prepare_shard_volume_mounts(shards, "/defs")

    assert [v.name for v in volumes] == [f"kaspr-definitions-{s.index}" for s in shards]
    assert [v.config_map.name for v in volumes] == [s.name for s in shards]
    assert all(v.config_map.items[0].key == "definitions.yaml" for v in volumes)
    assert [(m.name, m.mount_path, m.sub_path, m.read_only) for m in mounts] == [
        (f"kaspr-definitions-{s.index}", f"/defs/kaspr-definitions-{s.index}.yaml", "definitions.yaml", True)
        for s in shards
    ]


# ---------------------------------------------------------------------------
# Delivery mode
# ---------------------------------------------------------------------------


def rendered(app, mode):
    return app.render_stateful_set(mode)


def test_deployed_mode_reads_the_template_volumes():
    app = app_with()

    assert d.deployed_mode(rendered(app, d.COMPONENTS)) == d.COMPONENTS
    assert d.deployed_mode(rendered(app, d.BUNDLE)) == d.BUNDLE


def test_template_change_pending_sees_definitions_and_image_changes_only():
    app = app_with()
    live = rendered(app, d.COMPONENTS)

    assert not d.template_change_pending(live, rendered(app_with(), d.COMPONENTS))
    assert d.template_change_pending(
        live, rendered(app_with(extra=[webview_doc("new-page")]), d.COMPONENTS)
    )
    other_image = copy.deepcopy(live)
    other_image.spec.template.spec.containers[0].image = "kasprio/kaspr:9.9.9"
    assert d.template_change_pending(live, other_image)
    # Not detected on purpose: the API server may rewrite such fields.
    other_resources = copy.deepcopy(live)
    other_resources.spec.template.spec.containers[0].resources = V1ResourceRequirements(
        limits={"cpu": "1"}
    )
    assert not d.template_change_pending(live, other_resources)


@pytest.mark.parametrize(
    "annotation, default, deployed, changing, expected",
    [
        ("bundle", "components", "components", False, ("bundle", "annotation")),
        ("components", "bundle", "bundle", False, ("components", "annotation")),
        (" Bundle ", "components", None, False, ("bundle", "annotation")),
        (None, "components", None, False, ("components", "default")),
        (None, "bundle", None, False, ("bundle", "default")),
        (None, "bundle", "bundle", False, ("bundle", "default")),
        (None, "components", "components", True, ("components", "default")),
        (None, "bundle", "components", False, ("components", "deployed")),
        (None, "bundle", "components", True, ("bundle", "default")),
        (None, "components", "bundle", False, ("bundle", "deployed")),
        (None, "components", "bundle", True, ("components", "default")),
        ("sideways", "components", "bundle", False, ("bundle", "deployed")),
    ],
)
def test_resolve_delivery(annotation, default, deployed, changing, expected):
    app = app_with()
    live = rendered(app, deployed) if deployed else None
    target = app_with(extra=[webview_doc("new-page")]) if changing else app
    annotations = {d.DELIVERY_ANNOTATION: annotation} if annotation is not None else {}

    delivery = d.resolve_delivery(annotations, default, live, target.render_stateful_set)

    assert (delivery.mode, delivery.reason) == expected
    assert delivery.deployed == deployed
    assert delivery.invalid_annotation == ("sideways" if annotation == "sideways" else None)
    assert delivery.changes == (deployed is not None and deployed != delivery.mode)


def test_resolve_delivery_renders_only_when_the_default_differs_from_the_deployed_mode():
    app = app_with()
    live = rendered(app, d.COMPONENTS)

    def render(mode):
        raise AssertionError("no rendering needed")

    assert d.resolve_delivery({}, d.COMPONENTS, live, render).mode == d.COMPONENTS
    assert d.resolve_delivery({d.DELIVERY_ANNOTATION: "bundle"}, d.COMPONENTS, live, render).mode == d.BUNDLE


def test_definitions_outgrowing_the_deployed_bundle_take_the_default():
    app = app_with()
    live = rendered(app, d.BUNDLE)

    def render(mode):
        raise d.DefinitionsTooLarge("too large")

    delivery = d.resolve_delivery({}, d.COMPONENTS, live, render)

    assert (delivery.mode, delivery.reason) == (d.COMPONENTS, "default")


def annotated(value):
    return {"metadata": {"annotations": {d.DELIVERY_ANNOTATION: value}}}


@pytest.mark.parametrize(
    "app, deployed, default, expected",
    [
        # An app that does not exist: its components write their ConfigMaps, as before.
        (None, None, d.BUNDLE, False),
        # The annotation decides, whatever the pods run.
        (annotated("bundle"), d.COMPONENTS, d.COMPONENTS, True),
        (annotated("components"), d.BUNDLE, d.BUNDLE, False),
        # Without a valid annotation, the mode the pods run.
        ({"metadata": {}}, d.BUNDLE, d.COMPONENTS, True),
        ({"metadata": {}}, d.COMPONENTS, d.BUNDLE, False),
        (annotated("nonsense"), d.BUNDLE, d.COMPONENTS, True),
        # Without pods yet, the default the app will be created with.
        ({"metadata": {}}, None, d.BUNDLE, True),
        ({}, None, d.COMPONENTS, False),
    ],
)
def test_app_delivers_bundles(app, deployed, default, expected):
    stateful_set = rendered(app_with(), deployed) if deployed else None

    assert d.app_delivers_bundles(app, stateful_set, default) is expected


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


def test_cleanup_candidates_in_bundle_mode():
    desired = {"app-definitions-new"}
    config_maps = [
        shard_config_map("app-definitions-new"),
        shard_config_map("app-definitions-old"),
        component_config_map("page"),
        component_config_map("worker", kind="KasprAgent", suffix="-agent"),
        config_map(f"{APP}-app-config", labels={"kaspr.io/app": APP}, owner_kind="KasprApp", owner_name=APP),
        config_map("users-own", labels={"kaspr.io/app": APP}),
        shard_config_map("other-definitions-x", app="other-app"),
        component_config_map("theirs", app="other-app"),
        config_map("misnamed", labels={"kaspr.io/app": APP}, owner_kind="KasprWebView", owner_name="page"),
    ]

    names = [c.metadata.name for c in d.cleanup_candidates(APP, d.BUNDLE, desired, config_maps)]

    assert names == ["app-definitions-old", "page-webview", "worker-agent"]


def test_cleanup_candidates_in_components_mode_are_shards_only():
    config_maps = [
        shard_config_map("app-definitions-old"),
        component_config_map("page"),
        config_map("users-own", labels={"kaspr.io/app": APP}),
    ]

    names = [
        c.metadata.name
        for c in d.cleanup_candidates(APP, d.COMPONENTS, {"page-webview"}, config_maps)
    ]

    assert names == ["app-definitions-old"]


@pytest.fixture
def bundle_app_and_set():
    app = app_with(annotations={d.DELIVERY_ANNOTATION: "bundle"})
    app.definitions_delivery = d.BUNDLE
    return app, set(app.desired_definitions_config_maps), app.stateful_set


def test_nothing_is_deleted_without_a_stateful_set():
    plan = d.plan_cleanup([shard_config_map("old")], {"new"}, None, [])

    assert plan.delete == [] and len(plan.waiting) == 1
    assert plan.reason == "the StatefulSet does not exist"


def test_nothing_is_deleted_before_the_template_mounts_the_new_definitions(bundle_app_and_set):
    app, desired, stateful_set = bundle_app_and_set
    old_template = with_status(app.render_stateful_set(d.COMPONENTS))

    plan = d.plan_cleanup([shard_config_map("old")], desired, old_template, [])

    assert plan.delete == []
    assert plan.reason == "the pod template does not mount the new definitions yet"


@pytest.mark.parametrize(
    "status",
    [
        dict(generation=3, observed=2),
        dict(current="rev-1", update="rev-2"),
        dict(replicas=3, updated=2),
    ],
    ids=["generation not observed", "revisions differ", "pods not updated"],
)
def test_nothing_is_deleted_during_a_rollout(bundle_app_and_set, status):
    app, desired, stateful_set = bundle_app_and_set

    plan = d.plan_cleanup([shard_config_map("old")], desired, with_status(stateful_set, **status), [])

    assert plan.delete == []
    assert plan.reason == "a rollout is in progress"


def test_unused_config_maps_go_once_the_rollout_is_complete(bundle_app_and_set):
    app, desired, stateful_set = bundle_app_and_set
    old, legacy, mounted = shard_config_map("old"), component_config_map("page"), shard_config_map("held")

    plan = d.plan_cleanup(
        [old, legacy, mounted],
        desired,
        with_status(stateful_set),
        [pod_mounting(*desired), pod_mounting("held")],
    )

    assert plan.delete == [old, legacy]
    assert plan.waiting == [mounted]
    assert plan.reason == "a pod still mounts them"


def test_a_scaled_to_zero_app_is_rolled_out():
    # The API omits zero counts, so the client reads them as None.
    app = app_with()
    stateful_set = with_status(app.stateful_set, replicas=0, updated=None)

    assert d.rollout_complete(stateful_set)
