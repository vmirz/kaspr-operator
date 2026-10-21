"""Unit tests for the VerticalPodAutoscaler a KasprApp can opt into."""

import asyncio
import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from kubernetes_asyncio.client import ApiException, V1ContainerResizePolicy

import kaspr.resources.kasprapp as kasprapp_module
from kaspr.handlers import kasprapp as handler
from kaspr.resources import KasprApp
from kaspr.types.schemas.kasprapp_spec import KasprAppSpecSchema
from kaspr.types.settings import Settings


APP_SPEC = {
    "replicas": 2,
    "bootstrapServers": "kafka:9092",
    "authentication": {"type": "plain"},
    "storage": {"type": "persistent-claim", "class": "standard", "size": "1Gi", "deleteClaim": True},
    "resources": {"requests": {"cpu": "500m", "memory": "1Gi"}, "limits": {"cpu": "2", "memory": "2Gi"}},
}

OWNER_REF = {
    "apiVersion": "kaspr.io/v1alpha1",
    "kind": "KasprApp",
    "name": "test-app",
    "uid": "uid-app",
    "controller": True,
    "blockOwnerDeletion": True,
}

VPA_RESOURCES = ["verticalpodautoscalers", "verticalpodautoscalers/status", "verticalpodautoscalercheckpoints"]
SCALABLE = ["kasprapps", "kasprapps/status", "kasprapps/scale", "kaspragents"]
NOT_SCALABLE = ["kasprapps", "kasprapps/status", "kaspragents"]


@pytest.fixture(autouse=True)
def operator_settings(monkeypatch):
    """Settings normally installed on KasprApp by the operator's startup handler."""
    monkeypatch.setattr(KasprApp, "conf", Settings(), raising=False)
    monkeypatch.setattr(KasprApp, "sensor", None, raising=False)


@pytest.fixture(autouse=True)
def fresh_discovery():
    KasprApp._api_resources.clear()
    yield
    KasprApp._api_resources.clear()


@pytest.fixture(autouse=True)
def adoption(monkeypatch):
    """kopf.adopt() as it behaves in a handler of the app: the app becomes the owner."""

    def adopt(obj, *args, **kwargs):
        refs = obj.setdefault("metadata", {}).setdefault("ownerReferences", [])
        if not any(ref["uid"] == OWNER_REF["uid"] for ref in refs):
            refs.append(dict(OWNER_REF))

    monkeypatch.setattr(kasprapp_module.kopf, "adopt", adopt)


def api_error(status, message=None):
    error = ApiException(status=status, reason={403: "Forbidden", 404: "Not Found", 422: "Unprocessable Entity", 500: "Internal Server Error"}.get(status, "Error"))
    if message:
        error.body = json.dumps({"kind": "Status", "message": message})
    return error


class FakeCustomObjectsApi:
    """The custom objects API of a cluster, with or without the VPA installed."""

    def __init__(self, vpa_installed=True, scalable=True, live=None, discovery_error=None):
        self.served = {
            ("kaspr.io", "v1alpha1"): SCALABLE if scalable else NOT_SCALABLE,
        }
        if vpa_installed:
            self.served[("autoscaling.k8s.io", "v1")] = VPA_RESOURCES
        self.live = live
        self.discovery_error = discovery_error
        self.discovery_calls = []
        self.get_error = None
        self.create_error = None
        self.created, self.patched, self.deleted = [], [], []

    async def get_api_resources(self, group, version):
        self.discovery_calls.append((group, version))
        if self.discovery_error is not None:
            raise self.discovery_error
        if (group, version) not in self.served:
            raise api_error(404)
        return SimpleNamespace(resources=[SimpleNamespace(name=name) for name in self.served[(group, version)]])

    def _check_vpa_api(self, group, version):
        if (group, version) not in self.served:
            raise api_error(404)

    async def get_namespaced_custom_object(self, group, version, namespace, plural, name):
        self._check_vpa_api(group, version)
        if self.get_error is not None:
            raise self.get_error
        if self.live is None:
            raise api_error(404, f'{plural}.{group} "{name}" not found')
        return copy.deepcopy(self.live)

    async def create_namespaced_custom_object(self, group, version, namespace, plural, body):
        self._check_vpa_api(group, version)
        if self.create_error is not None:
            raise self.create_error
        self.created.append(copy.deepcopy(body))
        return copy.deepcopy(body)

    async def patch_namespaced_custom_object(self, group, version, namespace, plural, name, body, **kwargs):
        self.patched.append((body, kwargs))
        return copy.deepcopy(self.live)

    async def delete_namespaced_custom_object(self, group, version, namespace, plural, name):
        self.deleted.append(name)


def make_app(vpa=None, api=None, **spec_overrides):
    spec = {**APP_SPEC, **spec_overrides}
    if vpa is not None:
        spec["verticalPodAutoscaler"] = vpa
    app = KasprApp.from_spec("test-app", "KasprApp", "test-ns", KasprAppSpecSchema().load(spec), {})
    app.logger = Mock()
    if api is not None:
        app.__dict__["custom_objects_api"] = api
        app._custom_objects_api = api
    return app


def sync(app):
    asyncio.run(app.sync_vpa())
    return app.vpa_condition


def owned_live(app, target_scalable=True):
    """The VPA as the operator created it, read back from the API."""
    target = asyncio.run(app.prepare_vpa_target_ref()) if target_scalable is None else (
        {"apiVersion": "kaspr.io/v1alpha1", "kind": "KasprApp", "name": "test-app"}
        if target_scalable
        else {"apiVersion": "apps/v1", "kind": "StatefulSet", "name": "test-app-app"}
    )
    live = app.prepare_vpa(target)
    live["metadata"]["ownerReferences"] = [dict(OWNER_REF)]
    live["metadata"]["resourceVersion"] = "7"
    return live


# ---------------------------------------------------------------------------
# Spec
# ---------------------------------------------------------------------------


def test_apps_get_no_vpa_unless_they_enable_one():
    assert make_app().vertical_pod_autoscaler is None
    assert make_app().vertical_pod_autoscaler_enabled is False
    # Configuring it is not enough: it must be enabled explicitly.
    assert make_app(vpa={}).vertical_pod_autoscaler_enabled is False
    assert make_app(vpa={"maxAllowed": {"cpu": "2"}}).vertical_pod_autoscaler_enabled is False
    assert make_app(vpa={"enabled": True}).vertical_pod_autoscaler_enabled is True


def test_vpa_defaults():
    conf = make_app(vpa={"enabled": True}).vertical_pod_autoscaler

    assert conf.update_mode == "InPlaceOrRecreate"
    assert conf.controlled_resources == ["cpu"]
    assert conf.controlled_values == "RequestsOnly"
    assert conf.min_replicas is None and conf.min_allowed is None and conf.max_allowed is None


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def test_prepare_vpa_controls_only_the_kaspr_container():
    app = make_app(vpa={"enabled": True})

    vpa = app.prepare_vpa({"apiVersion": "kaspr.io/v1alpha1", "kind": "KasprApp", "name": "test-app"})

    assert vpa["apiVersion"] == "autoscaling.k8s.io/v1"
    assert vpa["kind"] == "VerticalPodAutoscaler"
    assert vpa["metadata"]["name"] == "test-app-app-vpa"
    assert vpa["metadata"]["namespace"] == "test-ns"
    assert vpa["metadata"]["labels"]["kaspr.io/app"] == "test-app"
    assert vpa["metadata"]["annotations"]["kaspr.io/resource-hash"]
    assert vpa["spec"] == {
        "targetRef": {"apiVersion": "kaspr.io/v1alpha1", "kind": "KasprApp", "name": "test-app"},
        "updatePolicy": {"updateMode": "InPlaceOrRecreate"},
        "resourcePolicy": {
            "containerPolicies": [
                {
                    "containerName": "kaspr",
                    "mode": "Auto",
                    "controlledResources": ["cpu"],
                    "controlledValues": "RequestsOnly",
                },
                {"containerName": "*", "mode": "Off"},
            ]
        },
    }


def test_prepare_vpa_passes_the_configured_bounds_and_policy():
    app = make_app(
        vpa={
            "enabled": True,
            "updateMode": "Recreate",
            "minReplicas": 1,
            "controlledResources": ["cpu", "memory"],
            "controlledValues": "RequestsAndLimits",
            "minAllowed": {"cpu": "100m", "memory": "256Mi"},
            "maxAllowed": {"cpu": 2},
        }
    )

    spec = app.prepare_vpa({"apiVersion": "apps/v1", "kind": "StatefulSet", "name": "test-app-app"})["spec"]

    assert spec["updatePolicy"] == {"updateMode": "Recreate", "minReplicas": 1}
    assert spec["resourcePolicy"]["containerPolicies"][0] == {
        "containerName": "kaspr",
        "mode": "Auto",
        "controlledResources": ["cpu", "memory"],
        "controlledValues": "RequestsAndLimits",
        "minAllowed": {"cpu": "100m", "memory": "256Mi"},
        "maxAllowed": {"cpu": 2},
    }


def test_vpa_hash_follows_its_configuration():
    target = {"apiVersion": "kaspr.io/v1alpha1", "kind": "KasprApp", "name": "test-app"}
    first = make_app(vpa={"enabled": True}).prepare_vpa(target)
    same = make_app(vpa={"enabled": True}).prepare_vpa(target)
    other = make_app(vpa={"enabled": True, "maxAllowed": {"cpu": "1"}}).prepare_vpa(target)

    hash_of = lambda vpa: vpa["metadata"]["annotations"]["kaspr.io/resource-hash"]
    assert hash_of(first) == hash_of(same)
    assert hash_of(first) != hash_of(other)


def test_cpu_autoscaling_leaves_the_pod_template_as_it_was():
    """Enabling CPU autoscaling must not roll the app's pods."""
    without = make_app()
    with_cpu = make_app(vpa={"enabled": True})

    assert with_cpu.kaspr_container.resize_policy is None
    assert with_cpu.stateful_set_hash == without.stateful_set_hash


def test_memory_autoscaling_restarts_the_container_on_a_memory_resize():
    app = make_app(vpa={"enabled": True, "controlledResources": ["cpu", "memory"]})

    assert app.kaspr_container.resize_policy == [
        V1ContainerResizePolicy(resource_name="cpu", restart_policy="NotRequired"),
        V1ContainerResizePolicy(resource_name="memory", restart_policy="RestartContainer"),
    ]
    assert app.stateful_set_hash != make_app().stateful_set_hash


def test_disabled_memory_autoscaling_sets_no_resize_policy():
    app = make_app(vpa={"enabled": False, "controlledResources": ["memory"]})

    assert app.kaspr_container.resize_policy is None


# ---------------------------------------------------------------------------
# Synchronization: the Vertical Pod Autoscaler is not installed
# ---------------------------------------------------------------------------


def test_enabled_vpa_without_the_vpa_installed_is_reported_not_created():
    api = FakeCustomObjectsApi(vpa_installed=False)
    app = make_app(vpa={"enabled": True}, api=api)

    condition = sync(app)

    assert condition["type"] == "VerticalPodAutoscalerReady"
    assert condition["status"] == "False"
    assert condition["reason"] == "NotInstalled"
    assert "autoscaling.k8s.io/v1" in condition["message"]
    assert api.created == [] and api.patched == []


def test_app_without_vpa_and_without_the_vpa_installed_asks_for_nothing_more():
    api = FakeCustomObjectsApi(vpa_installed=False)
    app = make_app(api=api)

    assert sync(app) is None
    assert api.discovery_calls == [("autoscaling.k8s.io", "v1")]
    assert api.created == api.patched == api.deleted == []


def test_vpa_installed_later_is_picked_up_after_discovery_expires(monkeypatch):
    api = FakeCustomObjectsApi(vpa_installed=False)
    app = make_app(vpa={"enabled": True}, api=api)
    assert sync(app)["reason"] == "NotInstalled"

    api.served[("autoscaling.k8s.io", "v1")] = VPA_RESOURCES
    # Within the discovery interval the cluster is not asked again.
    assert sync(make_app(vpa={"enabled": True}, api=api))["reason"] == "NotInstalled"
    clock = kasprapp_module.time.monotonic() + KasprApp.API_DISCOVERY_TTL_SECONDS + 1
    monkeypatch.setattr(kasprapp_module.time, "monotonic", lambda: clock)

    assert sync(make_app(vpa={"enabled": True}, api=api))["reason"] == "Configured"
    assert len(api.created) == 1


def test_vpa_api_removed_after_discovery_is_reported_not_installed():
    api = FakeCustomObjectsApi()
    app = make_app(vpa={"enabled": True}, api=api)
    asyncio.run(app.vpa_api_available())  # discovered while installed
    del api.served[("autoscaling.k8s.io", "v1")]

    condition = sync(app)

    assert condition["reason"] == "NotInstalled"
    # Discovery is asked again next time.
    assert ("autoscaling.k8s.io", "v1") not in KasprApp._api_resources


# ---------------------------------------------------------------------------
# Synchronization: creating, updating and deleting
# ---------------------------------------------------------------------------


def test_enabled_vpa_is_created_targeting_the_kasprapp():
    api = FakeCustomObjectsApi()
    app = make_app(vpa={"enabled": True}, api=api)

    condition = sync(app)

    assert condition["status"] == "True" and condition["reason"] == "Configured"
    assert "targets KasprApp test-app" in condition["message"]
    [created] = api.created
    assert created["spec"]["targetRef"] == {"apiVersion": "kaspr.io/v1alpha1", "kind": "KasprApp", "name": "test-app"}
    assert created["metadata"]["ownerReferences"] == [OWNER_REF]


def test_vpa_targets_the_statefulset_while_the_crd_has_no_scale_subresource():
    api = FakeCustomObjectsApi(scalable=False)
    app = make_app(vpa={"enabled": True}, api=api)

    condition = sync(app)

    assert condition["reason"] == "Configured"
    [created] = api.created
    assert created["spec"]["targetRef"] == {"apiVersion": "apps/v1", "kind": "StatefulSet", "name": "test-app-app"}


def test_up_to_date_vpa_is_left_alone():
    api = FakeCustomObjectsApi()
    app = make_app(vpa={"enabled": True}, api=api)
    api.live = owned_live(app)

    assert sync(app)["reason"] == "Configured"
    assert api.created == api.patched == []


def test_live_spec_with_more_fields_than_the_operator_sets_is_up_to_date():
    api = FakeCustomObjectsApi()
    app = make_app(vpa={"enabled": True}, api=api)
    api.live = owned_live(app)
    api.live["spec"]["recommenders"] = [{"name": "default"}]
    api.live["spec"]["resourcePolicy"]["containerPolicies"][1]["controlledValues"] = "RequestsAndLimits"

    sync(app)

    assert api.patched == []


@pytest.mark.parametrize(
    "drift",
    [
        lambda live: live["metadata"]["annotations"].update({"kaspr.io/resource-hash": "older"}),
        lambda live: live["spec"]["updatePolicy"].update({"updateMode": "Off"}),
        lambda live: live["spec"]["resourcePolicy"]["containerPolicies"].pop(),
    ],
    ids=["changed-configuration", "edited-by-hand", "policy-removed"],
)
def test_drifted_vpa_is_restored(drift):
    api = FakeCustomObjectsApi()
    app = make_app(vpa={"enabled": True}, api=api)
    api.live = owned_live(app)
    drift(api.live)
    desired = app.prepare_vpa({"apiVersion": "kaspr.io/v1alpha1", "kind": "KasprApp", "name": "test-app"})

    assert sync(app)["reason"] == "Configured"

    [(ops, kwargs)] = api.patched
    assert kwargs == {"_content_type": "application/json-patch+json"}
    assert ops == [
        {"op": "replace", "path": "/spec", "value": desired["spec"]},
        {
            "op": "add",
            "path": "/metadata/annotations/kaspr.io~1resource-hash",
            "value": desired["metadata"]["annotations"]["kaspr.io/resource-hash"],
        },
    ]


def test_vpa_now_targeting_the_kasprapp_is_patched():
    """The CRD gained its scale subresource after the VPA was created."""
    api = FakeCustomObjectsApi(scalable=True)
    app = make_app(vpa={"enabled": True}, api=api)
    api.live = owned_live(app, target_scalable=False)

    sync(app)

    [(ops, _)] = api.patched
    assert ops[0]["value"]["targetRef"]["kind"] == "KasprApp"


def test_vpa_not_made_by_the_operator_is_left_alone():
    api = FakeCustomObjectsApi()
    app = make_app(vpa={"enabled": True}, api=api)
    api.live = owned_live(app)
    api.live["metadata"]["ownerReferences"] = []
    api.live["spec"]["updatePolicy"]["updateMode"] = "Off"

    condition = sync(app)

    assert condition["status"] == "False" and condition["reason"] == "Conflict"
    assert api.patched == [] and api.deleted == []


def test_disabling_vpa_deletes_the_one_the_operator_made():
    api = FakeCustomObjectsApi()
    api.live = owned_live(make_app(vpa={"enabled": True}))
    app = make_app(vpa={"enabled": False}, api=api)

    assert sync(app) is None
    assert api.deleted == ["test-app-app-vpa"]


def test_removing_the_vpa_configuration_deletes_the_one_the_operator_made():
    api = FakeCustomObjectsApi()
    api.live = owned_live(make_app(vpa={"enabled": True}))
    app = make_app(api=api)

    assert sync(app) is None
    assert api.deleted == ["test-app-app-vpa"]


def test_app_without_vpa_never_deletes_a_vpa_it_does_not_own():
    api = FakeCustomObjectsApi()
    api.live = owned_live(make_app(vpa={"enabled": True}))
    api.live["metadata"]["ownerReferences"] = [{**OWNER_REF, "name": "other-app"}]
    app = make_app(api=api)

    assert sync(app) is None
    assert api.deleted == []


def test_app_without_vpa_and_without_permission_to_read_vpas_stays_quiet():
    api = FakeCustomObjectsApi()
    api.get_error = api_error(403, "verticalpodautoscalers is forbidden")
    app = make_app(api=api)

    assert sync(app) is None
    app.logger.warning.assert_not_called()
    app.logger.error.assert_not_called()


# ---------------------------------------------------------------------------
# Synchronization: failures are reported, never raised
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status, message, reason",
    [
        (403, "verticalpodautoscalers.autoscaling.k8s.io is forbidden", "Forbidden"),
        (422, 'spec.updatePolicy.updateMode: Unsupported value: "InPlaceOrRecreate"', "Invalid"),
        (500, "etcdserver: request timed out", "Error"),
    ],
)
def test_rejected_vpa_is_reported(status, message, reason):
    api = FakeCustomObjectsApi()
    api.create_error = api_error(status, message)
    app = make_app(vpa={"enabled": True}, api=api)

    condition = sync(app)

    assert condition["status"] == "False"
    assert condition["reason"] == reason
    assert message in condition["message"]


def test_forbidden_vpa_says_which_permissions_are_missing():
    api = FakeCustomObjectsApi()
    api.get_error = api_error(403, "forbidden")
    app = make_app(vpa={"enabled": True}, api=api)

    condition = sync(app)

    assert condition["reason"] == "Forbidden"
    assert "verticalpodautoscalers.autoscaling.k8s.io" in condition["message"]


def test_failed_discovery_is_reported_for_an_enabled_vpa():
    api = FakeCustomObjectsApi(discovery_error=api_error(503, "service unavailable"))
    app = make_app(vpa={"enabled": True}, api=api)

    condition = sync(app)

    assert condition["status"] == "False" and condition["reason"] == "Error"
    assert "service unavailable" in condition["message"]


def test_unexpected_error_is_reported_not_raised(monkeypatch):
    api = FakeCustomObjectsApi()
    app = make_app(vpa={"enabled": True}, api=api)

    def broken_adopt(*args, **kwargs):
        raise RuntimeError("no owner")

    monkeypatch.setattr(kasprapp_module.kopf, "adopt", broken_adopt)

    condition = sync(app)

    assert condition["reason"] == "Error"
    assert "no owner" in condition["message"]
    assert api.created == []


def test_vpa_reporting_its_configuration_unsupported_is_reported():
    api = FakeCustomObjectsApi()
    app = make_app(vpa={"enabled": True}, api=api)
    api.live = owned_live(app)
    api.live["status"] = {
        "conditions": [
            {"type": "ConfigUnsupported", "status": "True", "message": "Cannot read targetRef"},
        ]
    }

    condition = sync(app)

    assert condition["status"] == "False" and condition["reason"] == "ConfigUnsupported"
    assert "Cannot read targetRef" in condition["message"]


def test_app_without_requests_is_told_its_pods_are_recreated_once():
    api = FakeCustomObjectsApi()
    app = make_app(vpa={"enabled": True}, api=api, resources=None)

    condition = sync(app)

    assert condition["reason"] == "Configured"
    assert "recreated once" in condition["message"]
    assert "recreated once" not in sync(make_app(vpa={"enabled": True}, api=FakeCustomObjectsApi()))["message"]


def test_discovery_is_shared_and_kept_for_a_while():
    api = FakeCustomObjectsApi()

    for _ in range(3):
        sync(make_app(vpa={"enabled": True}, api=api))

    assert api.discovery_calls == [("autoscaling.k8s.io", "v1"), ("kaspr.io", "v1alpha1")]


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


CONFIGURED = {
    "type": "VerticalPodAutoscalerReady",
    "status": "True",
    "reason": "Configured",
    "message": "VerticalPodAutoscaler test-app-app-vpa targets KasprApp test-app",
}
NOT_INSTALLED = {
    "type": "VerticalPodAutoscalerReady",
    "status": "False",
    "reason": "NotInstalled",
    "message": "The VerticalPodAutoscaler API is not available",
}


def update(status, condition, gen=3):
    status_update, logger = {}, Mock()
    changed = handler._update_vpa_condition(status_update, status, condition, gen, logger)
    return status_update, logger, changed


def test_vpa_condition_is_added_with_the_generation():
    status_update, logger, changed = update({"conditions": [{"type": "Ready", "status": "True"}]}, CONFIGURED)

    [ready, vpa] = status_update["conditions"]
    assert ready == {"type": "Ready", "status": "True"}
    assert {k: vpa[k] for k in CONFIGURED} == CONFIGURED
    assert vpa["observedGeneration"] == 3 and vpa["lastTransitionTime"]
    logger.info.assert_called_once_with(CONFIGURED["message"])
    logger.warning.assert_not_called()
    assert changed == CONFIGURED


def test_vpa_problem_is_warned_about_once():
    status_update, logger, changed = update({"conditions": []}, NOT_INSTALLED)
    logger.warning.assert_called_once_with(NOT_INSTALLED["message"])
    assert changed == NOT_INSTALLED

    _, logger, changed = update({"conditions": status_update["conditions"]}, NOT_INSTALLED)
    logger.warning.assert_not_called()
    assert changed is None


def test_vpa_condition_is_dropped_when_vertical_autoscaling_is_off():
    status_update, _, changed = update({"conditions": [{"type": "Ready"}, {**CONFIGURED, "lastTransitionTime": "t"}]}, None)

    assert status_update["conditions"] == [{"type": "Ready"}]
    assert changed is None
    assert update({"conditions": [{"type": "Ready"}]}, None)[0] == {}


class FakeStatusApp:
    """The parts of KasprApp used by update_status."""

    stateful_set_name = "test-app-app"

    def __init__(self):
        self.annotations = {}
        self.python_packages = None
        self.static_group_membership_enabled = False
        self.replicas = 1
        self.conf = SimpleNamespace(hung_member_detection_enabled=False, auto_rebalance_enabled=False)
        self.observed_stateful_set = None

    async def fetch_app_status(self, **kwargs):
        self.observed_stateful_set = SimpleNamespace(metadata=SimpleNamespace(resource_version="1"))
        return {"kasprVersion": "0.11.29", "availableMembers": 1, "desiredMembers": 1, "rolloutInProgress": False, "members": []}

    def prepare_statefulset_fingerprint(self, stateful_set):
        return "desired"


@pytest.fixture
def posted_events(monkeypatch):
    events = []
    monkeypatch.setattr(
        handler.kopf, "warn", lambda obj, reason, message: events.append(("Warning", obj["metadata"]["name"], reason))
    )
    monkeypatch.setattr(
        handler.kopf, "event", lambda obj, type, reason, message: events.append((type, obj["metadata"]["name"], reason))
    )
    return events


def run_status_update(monkeypatch, status, reconciled=True, condition=NOT_INSTALLED):
    monkeypatch.setattr(handler.KasprAppSpecSchema, "load", lambda self, value: object())
    monkeypatch.setattr(handler.KasprApp, "from_spec", classmethod(lambda cls, *a, **k: FakeStatusApp()))
    state = handler.AppRuntimeState(
        desired_statefulset_fingerprint="desired", vpa_reconciled=reconciled, vpa_condition=condition
    )
    patch = SimpleNamespace(status={})
    asyncio.run(
        handler.update_status(
            name="test-app", spec={}, meta={"generation": 1, "uid": "uid-app"}, status=status,
            patch=patch, namespace="test-ns", annotations={}, logger=Mock(), state=state,
        )
    )
    return patch.status


@pytest.mark.parametrize("reconciled, expected", [(True, True), (False, False)])
def test_update_status_reports_the_vpa_once_it_was_reconciled(monkeypatch, posted_events, reconciled, expected):
    written = run_status_update(monkeypatch, {"observedGeneration": 1}, reconciled=reconciled)

    types = [c["type"] for c in written.get("conditions", [])]
    assert ("VerticalPodAutoscalerReady" in types) is expected
    # Ready and Progressing are still decided as before.
    assert {"Ready", "Progressing"} <= set(types)


def test_update_status_announces_vpa_changes_with_events(monkeypatch, posted_events):
    written = run_status_update(monkeypatch, {"observedGeneration": 1})
    assert posted_events == [("Warning", "test-app", "VerticalPodAutoscalerNotInstalled")]

    # Unchanged on the next refresh: no new event.
    run_status_update(monkeypatch, {"observedGeneration": 1, "conditions": written["conditions"]})
    assert len(posted_events) == 1

    run_status_update(monkeypatch, {"observedGeneration": 1, "conditions": written["conditions"]}, condition=CONFIGURED)
    assert posted_events[-1] == ("Normal", "test-app", "VerticalPodAutoscalerConfigured")
