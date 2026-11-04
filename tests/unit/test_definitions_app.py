"""A KasprApp delivering bundles: its StatefulSet, writing shards and cleaning up."""

import asyncio
import copy
from types import SimpleNamespace

import pytest
from kubernetes_asyncio.client import ApiException, V1OwnerReference

from kaspr.resources import definitions as d
from kaspr.resources.kasprapp import KasprApp
from kaspr.types.settings import Settings
from definitions_fixtures import (
    APP,
    app_with,
    component_config_map,
    pod_mounting,
    shard_config_map,
    webview_doc,
    with_status,
)

APP_UID = "uid-app"
OWNER = {
    "apiVersion": "kaspr.io/v1alpha1",
    "kind": "KasprApp",
    "metadata": {"name": APP, "namespace": "legacy-rendering", "uid": APP_UID},
}


@pytest.fixture(autouse=True)
def operator_settings(monkeypatch):
    monkeypatch.setattr(KasprApp, "conf", Settings(), raising=False)


class FakeCore:
    """The ConfigMap and pod calls of CoreV1Api, over a dict of ConfigMaps."""

    def __init__(self, config_maps=(), pods=()):
        self.config_maps = {cm.metadata.name: cm for cm in config_maps}
        self.pods = list(pods)
        self.created, self.deleted, self.patched = [], [], []
        self.lists = 0
        self.raced = set()  # names another writer creates just before us

    async def list_namespaced_config_map(self, namespace, label_selector=None):
        self.lists += 1
        key, value = label_selector.split("=")
        return SimpleNamespace(
            items=[c for c in self.config_maps.values() if (c.metadata.labels or {}).get(key) == value]
        )

    async def create_namespaced_config_map(self, namespace, body):
        if body.metadata.name in self.raced:
            self.config_maps[body.metadata.name] = copy.deepcopy(body)
            raise ApiException(status=409, reason="Conflict")
        if body.metadata.name in self.config_maps:
            raise ApiException(status=409, reason="Conflict")
        self.config_maps[body.metadata.name] = body
        self.created.append(body)

    async def read_namespaced_config_map(self, name, namespace):
        if name not in self.config_maps:
            raise ApiException(status=404, reason="Not Found")
        return self.config_maps[name]

    async def patch_namespaced_config_map(self, name, namespace, body):
        self.patched.append((name, body))

    async def delete_namespaced_config_map(self, name, namespace, body=None):
        config_map = self.config_maps.get(name)
        if config_map is None:
            raise ApiException(status=404, reason="Not Found")
        uid = body.preconditions.uid if body and body.preconditions else None
        if uid and uid != config_map.metadata.uid:
            raise ApiException(status=409, reason="Conflict")
        del self.config_maps[name]
        self.deleted.append(name)

    async def list_namespaced_pod(self, namespace, label_selector=None):
        return SimpleNamespace(items=self.pods)


class FakeApps:
    def __init__(self, stateful_set=None):
        self.stateful_set = stateful_set
        self.reads = 0

    async def read_namespaced_stateful_set(self, name, namespace):
        self.reads += 1
        if self.stateful_set is None:
            raise ApiException(status=404, reason="Not Found")
        return self.stateful_set


def bundle_app(**kwargs):
    app = app_with(annotations={d.DELIVERY_ANNOTATION: "bundle"}, **kwargs)
    app.definitions_delivery = d.BUNDLE
    app.owner = OWNER
    return app


def use(app, core=None, apps=None):
    app.__dict__["core_v1_api"] = core or FakeCore()
    app.__dict__["apps_v1_api"] = apps or FakeApps()
    return app.__dict__["core_v1_api"], app.__dict__["apps_v1_api"]


# ---------------------------------------------------------------------------
# StatefulSet
# ---------------------------------------------------------------------------


def env(stateful_set):
    return {e.name: e.value for e in stateful_set.spec.template.spec.containers[0].env}


def test_bundle_template_mounts_one_file_and_keeps_every_hash():
    app = app_with()
    components = app.render_stateful_set(d.COMPONENTS)
    bundle = app.render_stateful_set(d.BUNDLE)
    spec = bundle.spec.template.spec

    assert [v.name for v in spec.volumes] == ["kaspr-definitions-0"]
    definitions_mounts = [m for m in spec.containers[0].volume_mounts if m.name.startswith("kaspr-definitions")]
    assert [(m.mount_path, m.sub_path) for m in definitions_mounts] == [
        ("/var/lib/data/definitions/kaspr-definitions-0.yaml", "definitions.yaml")
    ]
    bundle_env, components_env = env(bundle), env(components)
    assert bundle_env.pop("JOINS_HASH") == app.joins_hash
    assert bundle_env == components_env
    assert "JOINS_HASH" not in components_env


def test_render_stateful_set_does_not_change_the_apps_own_mode():
    app = app_with()

    app.render_stateful_set(d.BUNDLE)

    assert app.definitions_delivery == d.COMPONENTS
    assert d.deployed_mode(app.stateful_set) == d.COMPONENTS


def test_desired_definitions_config_maps_follow_the_mode():
    app = app_with()

    assert app.desired_definitions_config_maps == {
        c.config_map_name for c in [*app.agents, *app.webviews, *app.tables, *app.tasks]
    }
    app.definitions_delivery = d.BUNDLE
    assert app.desired_definitions_config_maps == {s.name for s in app.definition_shards}


def test_resolve_definitions_delivery_follows_the_operator_default(monkeypatch):
    monkeypatch.setattr(KasprApp, "conf", Settings(definitions_delivery_default="bundle"), raising=False)
    app = app_with()

    delivery = app.resolve_definitions_delivery(None)

    assert delivery.mode == app.definitions_delivery == d.BUNDLE


def test_an_invalid_operator_default_keeps_components():
    conf = Settings(definitions_delivery_default="everything")

    assert conf.definitions_delivery_default == d.COMPONENTS
    assert conf.invalid_definitions_delivery_default == "everything"


def test_shard_budget_is_clamped():
    assert Settings(definitions_bundle_shard_bytes=1).definitions_bundle_shard_bytes == 64 * 1024
    assert Settings(definitions_bundle_shard_bytes=10**9).definitions_bundle_shard_bytes == 1_000_000


# ---------------------------------------------------------------------------
# Writing shards
# ---------------------------------------------------------------------------


def test_missing_shards_are_created_immutable_and_owned_by_the_app():
    app = bundle_app()
    core, _ = use(app)

    listed = asyncio.run(app.sync_definition_shards())

    assert listed == []
    [created] = core.created
    assert created.metadata.name == app.definition_shards[0].name
    assert created.immutable is True
    assert [(r.kind, r.name, r.uid, r.controller) for r in created.metadata.owner_references] == [
        ("KasprApp", APP, APP_UID, True)
    ]
    assert created.metadata.labels["kaspr.io/app"] == APP
    assert created.metadata.labels["kaspr.io/component"] == "definitions"
    assert app.created_definition_shards == app.definition_shards


def test_existing_shards_are_left_as_they_are():
    app = bundle_app()
    core, _ = use(app)
    asyncio.run(app.sync_definition_shards())
    core.created.clear()

    asyncio.run(app.sync_definition_shards())

    assert core.created == [] and core.patched == []
    assert app.created_definition_shards == []


def test_a_shard_created_meanwhile_is_checked_instead():
    app = bundle_app()
    core, _ = use(app)
    core.raced.add(app.definition_shards[0].name)

    asyncio.run(app.sync_definition_shards())

    assert core.created == [] and core.patched == []


def test_a_shard_without_its_owner_gets_it():
    app = bundle_app()
    core, _ = use(app)
    asyncio.run(app.sync_definition_shards())
    shard = core.config_maps[app.definition_shards[0].name]
    shard.metadata.owner_references = None

    asyncio.run(app.sync_definition_shards())

    [(name, body)] = core.patched
    assert name == shard.metadata.name
    assert body[0]["path"] == "/metadata/ownerReferences"


@pytest.mark.parametrize(
    "tamper",
    [
        lambda cm: setattr(cm, "data", {"definitions.yaml": "agents: []\n"}),
        lambda cm: cm.metadata.labels.pop("kaspr.io/component"),
        lambda cm: setattr(
            cm.metadata,
            "owner_references",
            [V1OwnerReference(api_version="kaspr.io/v1alpha1", kind="KasprApp", name="other", uid="other", controller=True)],
        ),
    ],
    ids=["other data", "not labelled a shard", "owned by another app"],
)
def test_a_foreign_object_under_a_shard_name_stops_the_sync(tamper):
    app = bundle_app()
    core, _ = use(app)
    asyncio.run(app.sync_definition_shards())
    tamper(core.config_maps[app.definition_shards[0].name])

    with pytest.raises(d.DefinitionsConflict):
        asyncio.run(app.sync_definition_shards())
    assert core.patched == []


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


def test_cleanup_deletes_what_no_pod_mounts_once_rolled_out():
    app = bundle_app()
    desired = set(app.desired_definitions_config_maps)
    old_shard, legacy = shard_config_map(f"{APP}-app-definitions-0123456789"), component_config_map("page")
    core, apps = use(
        app,
        core=FakeCore([old_shard, legacy], pods=[pod_mounting(*desired)]),
        apps=FakeApps(with_status(app.stateful_set)),
    )

    plan = asyncio.run(app.clean_up_definitions(d.BUNDLE, desired))

    assert sorted(core.deleted) == sorted([old_shard.metadata.name, legacy.metadata.name])
    assert plan.waiting == []


def test_cleanup_waits_for_the_rollout_and_reads_no_pods_meanwhile():
    app = bundle_app()
    desired = set(app.desired_definitions_config_maps)
    core = FakeCore([shard_config_map(f"{APP}-app-definitions-0123456789")])
    core.list_namespaced_pod = None  # must not be called
    use(app, core=core, apps=FakeApps(with_status(app.stateful_set, current="rev-1")))

    plan = asyncio.run(app.clean_up_definitions(d.BUNDLE, desired))

    assert core.deleted == []
    assert len(plan.waiting) == 1 and plan.reason == "a rollout is in progress"


def test_cleanup_of_a_components_app_without_shards_reads_nothing_else():
    app = app_with()
    desired = set(app.desired_definitions_config_maps)
    core, apps = use(app, core=FakeCore([component_config_map("page")]))

    plan = asyncio.run(app.clean_up_definitions(d.COMPONENTS, desired, config_maps=[component_config_map("page")]))

    assert plan.delete == [] and plan.waiting == []
    assert core.lists == 0 and apps.reads == 0


def test_a_config_map_replaced_before_its_deletion_is_kept():
    app = bundle_app()
    desired = set(app.desired_definitions_config_maps)
    listed = shard_config_map(f"{APP}-app-definitions-0123456789")
    replaced = copy.deepcopy(listed)
    replaced.metadata.uid = "uid-new"
    core, _ = use(app, core=FakeCore([replaced]), apps=FakeApps(with_status(app.stateful_set)))

    plan = asyncio.run(app.clean_up_definitions(d.BUNDLE, desired, config_maps=[listed]))

    assert core.deleted == [] and plan.waiting == [listed]


def test_a_config_map_already_gone_counts_as_deleted():
    app = bundle_app()
    desired = set(app.desired_definitions_config_maps)
    gone = shard_config_map(f"{APP}-app-definitions-0123456789")
    core, _ = use(app, core=FakeCore([]), apps=FakeApps(with_status(app.stateful_set)))

    plan = asyncio.run(app.clean_up_definitions(d.BUNDLE, desired, config_maps=[gone]))

    assert plan.delete == [gone] and plan.waiting == []


def test_more_webviews_than_one_shard_holds_still_mount_every_shard():
    extra = [webview_doc(f"page-{i:02d}", code_bytes=40_000) for i in range(30)]
    app = bundle_app(extra=extra)

    shards = app.definition_shards
    spec = app.stateful_set.spec.template.spec

    assert len(shards) > 1
    assert sorted(v.config_map.name for v in spec.volumes if v.name.startswith("kaspr-definitions")) == sorted(
        s.name for s in shards
    )
