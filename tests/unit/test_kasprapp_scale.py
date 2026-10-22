"""Unit tests for the KasprApp scale subresource and the status fields it reads."""

import asyncio
import copy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import yaml
from kubernetes_asyncio.client import V1StatefulSetStatus

from kaspr.handlers import kasprapp as handler
from kaspr.resources import KasprApp
from kaspr.types.schemas.kasprapp_spec import KasprAppSpecSchema
from kaspr.types.settings import Settings


CRD_PATH = Path(__file__).resolve().parents[2] / "crds" / "kasprapp.crd.yaml"

APP_SPEC = {
    "replicas": 2,
    "bootstrapServers": "kafka:9092",
    "authentication": {"type": "plain"},
    "storage": {"type": "persistent-claim", "class": "standard", "size": "1Gi", "deleteClaim": True},
}

SELECTOR = "kaspr.io/cluster=test-app,kaspr.io/kind=KasprApp,kaspr.io/name=test-app-app"


@pytest.fixture(autouse=True)
def operator_settings(monkeypatch):
    """Settings normally installed on KasprApp by the operator's startup handler."""
    settings = Settings()
    settings.client_status_check_enabled = False
    monkeypatch.setattr(KasprApp, "conf", settings, raising=False)
    monkeypatch.setattr(KasprApp, "sensor", None, raising=False)
    return settings


@pytest.fixture(autouse=True)
def clean_handler_state():
    handler.app_states.clear()
    yield
    handler.app_states.clear()


def make_app(**spec_overrides):
    spec = KasprAppSpecSchema().load({**APP_SPEC, **spec_overrides})
    app = KasprApp.from_spec("test-app", "KasprApp", "test-ns", spec, {})
    app.logger = Mock()
    return app


@pytest.fixture(scope="module")
def crd_version():
    crd = yaml.safe_load(CRD_PATH.read_text())
    return crd["spec"]["versions"][0]


def test_crd_has_a_scale_subresource_reading_the_status(crd_version):
    assert crd_version["subresources"]["scale"] == {
        "specReplicasPath": ".spec.replicas",
        "statusReplicasPath": ".status.replicas",
        "labelSelectorPath": ".status.selector",
    }
    status = crd_version["schema"]["openAPIV3Schema"]["properties"]["status"]["properties"]
    assert status["replicas"]["type"] == "integer"
    assert status["selector"]["type"] == "string"


def test_crd_defaults_replicas(crd_version):
    """GET /scale fails for an object without spec.replicas, and VPA with it."""
    replicas = crd_version["schema"]["openAPIV3Schema"]["properties"]["spec"]["properties"]["replicas"]
    assert replicas["default"] == KasprApp.DEFAULT_REPLICAS


def test_app_without_replicas_runs_one_replica():
    """The default the CRD now applies, also where the CRD in the cluster predates it."""
    spec = {key: value for key, value in APP_SPEC.items() if key != "replicas"}
    app = KasprApp.from_spec("test-app", "KasprApp", "test-ns", KasprAppSpecSchema().load(spec), {})

    assert app.replicas == KasprApp.DEFAULT_REPLICAS == 1


def test_pod_selector_matches_the_statefulset_selector():
    app = make_app()

    assert app.pod_selector == SELECTOR
    match_labels = app.stateful_set.spec.selector.match_labels
    assert app.pod_selector == ",".join(f"{k}={v}" for k, v in sorted(match_labels.items()))


def test_fetch_app_status_reports_replicas_and_selector():
    app = make_app()
    live = copy.deepcopy(app.stateful_set)
    live.metadata.generation = 1
    live.status = V1StatefulSetStatus(replicas=2, available_replicas=0, observed_generation=1)

    async def fetch_stateful_set(*args, **kwargs):
        return live

    app.fetch_stateful_set = fetch_stateful_set
    status = asyncio.run(app.fetch_app_status())

    assert status["replicas"] == 2
    assert status["selector"] == SELECTOR


class FakeApp:
    """The parts of KasprApp used by update_status."""

    stateful_set_name = "test-app-app"

    def __init__(self, actual_status):
        self.annotations = {}
        self.python_packages = None
        self.static_group_membership_enabled = False
        self.replicas = 2
        self.conf = SimpleNamespace(
            hung_member_detection_enabled=False,
            auto_rebalance_enabled=False,
            client_status_check_enabled=True,
        )
        self.actual_status = actual_status
        self.observed_stateful_set = None

    async def fetch_app_status(self, **kwargs):
        self.observed_stateful_set = SimpleNamespace(metadata=SimpleNamespace(resource_version="1"))
        return copy.deepcopy(self.actual_status)

    def prepare_statefulset_fingerprint(self, stateful_set):
        return "desired"


def run_update_status(monkeypatch, status, actual_status):
    fake_app = FakeApp(actual_status)
    monkeypatch.setattr(handler.KasprAppSpecSchema, "load", lambda self, value: object())
    monkeypatch.setattr(handler.KasprApp, "from_spec", classmethod(lambda cls, *a, **k: fake_app))
    patch = SimpleNamespace(status={})
    asyncio.run(
        handler.update_status(
            name="test-app",
            spec={},
            meta={"generation": 1},
            status=status,
            patch=patch,
            namespace="test-ns",
            annotations={},
            logger=Mock(),
            state=handler.AppRuntimeState(desired_statefulset_fingerprint="desired"),
        )
    )
    return patch.status


ACTUAL = {
    "kasprVersion": "0.11.29",
    "availableMembers": 2,
    "desiredMembers": 2,
    "rolloutInProgress": False,
    "members": [],
    "replicas": 2,
    "selector": SELECTOR,
}


def test_update_status_reports_replicas_and_selector(monkeypatch):
    written = run_update_status(monkeypatch, {"observedGeneration": 1}, ACTUAL)

    assert written["replicas"] == 2
    assert written["selector"] == SELECTOR


def test_update_status_rewrites_only_a_changed_replica_count(monkeypatch):
    current = {"observedGeneration": 1, "replicas": 2, "selector": SELECTOR}

    assert "replicas" not in run_update_status(monkeypatch, current, ACTUAL)
    assert "selector" not in run_update_status(monkeypatch, current, ACTUAL)
    assert run_update_status(monkeypatch, current, {**ACTUAL, "replicas": 3})["replicas"] == 3


def test_on_create_reports_the_selector_before_the_first_status_refresh(monkeypatch):
    created = []

    class CreatedApp:
        reconciliation_paused = False
        pod_selector = SELECTOR

        async def create(self):
            created.append(True)

    async def fake_attach(app, name, namespace, related=None):
        return True

    async def fake_request_reconciliation(name, namespace=None, logger=None, **kwargs):
        pass

    monkeypatch.setattr(handler.KasprAppSpecSchema, "load", lambda self, value: object())
    monkeypatch.setattr(handler.KasprApp, "from_spec", classmethod(lambda cls, *a, **k: CreatedApp()))
    monkeypatch.setattr(handler, "attach_app_related_resources", fake_attach)
    monkeypatch.setattr(handler, "request_reconciliation", fake_request_reconciliation)

    def on_create(status):
        patch = SimpleNamespace(status={})
        asyncio.run(
            handler.on_create(
                spec={}, name="test-app", meta={}, status=status, patch=patch,
                namespace="test-ns", annotations={}, logger=Mock(),
            )
        )
        return patch.status

    assert on_create({}) == {"selector": SELECTOR}
    # Resumed by a restarted operator: nothing to write.
    assert on_create({"selector": SELECTOR}) == {}
    assert created == [True, True]
