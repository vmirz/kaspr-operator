"""Unit tests for the HorizontalPodAutoscaler a KasprApp owns."""

import asyncio
import copy
from unittest.mock import Mock

import pytest
from kubernetes_asyncio.client import V1OwnerReference

from kaspr.resources import KasprApp
from kaspr.types.schemas.kasprapp_spec import KasprAppSpecSchema
from kaspr.types.settings import Settings


APP_SPEC = {
    "replicas": 2,
    "bootstrapServers": "kafka:9092",
    "authentication": {"type": "plain"},
    "storage": {"type": "persistent-claim", "class": "standard", "size": "1Gi", "deleteClaim": True},
}

OWNER = V1OwnerReference(
    api_version="kaspr.io/v1alpha1",
    kind="KasprApp",
    name="test-app",
    uid="uid-app",
    controller=True,
    block_owner_deletion=True,
)


@pytest.fixture(autouse=True)
def operator_settings(monkeypatch):
    """Settings normally installed on KasprApp by the operator's startup handler."""
    monkeypatch.setattr(KasprApp, "conf", Settings(), raising=False)


def make_app(**spec_overrides):
    spec = KasprAppSpecSchema().load({**APP_SPEC, **spec_overrides})
    app = KasprApp.from_spec("test-app", "KasprApp", "test-ns", spec, {})
    app.logger = Mock()
    app.sensor = Mock()
    return app


def adopted(app):
    """The app as unite() leaves it: its HPA is owned by the KasprApp."""
    app.hpa.metadata.owner_references = [OWNER]
    return app


def sync_hpa(app, live):
    patches, created = [], []

    async def fetch_hpa(*args, **kwargs):
        return live

    async def create_hpa(api, namespace, hpa):
        created.append(hpa)

    async def patch_hpa(api, name, namespace, hpa):
        patches.append(hpa)

    app.fetch_hpa = fetch_hpa
    app.create_hpa = create_hpa
    app.patch_hpa = patch_hpa
    asyncio.run(app.sync_hpa())
    return patches, created


def test_patch_replicas_adopts_the_hpa_it_creates_again(monkeypatch):
    """Scaling up from zero creates the HPA again; it must not be left without an owner."""
    app = make_app()
    calls = []

    async def record(name):
        calls.append(name)

    monkeypatch.setattr(app, "unite", lambda: calls.append("unite"))
    monkeypatch.setattr(app, "sync_hpa", lambda: record("hpa"))
    monkeypatch.setattr(app, "sync_stateful_set", lambda: record("stateful_set"))

    asyncio.run(app.patch_replicas())

    assert calls == ["unite", "hpa", "stateful_set"]


def test_sync_hpa_adds_the_owner_an_existing_hpa_lacks():
    app = adopted(make_app())
    live = copy.deepcopy(app.hpa)
    live.metadata.owner_references = None

    patches, created = sync_hpa(app, live)

    assert created == []
    assert patches == [[{"op": "add", "path": "/metadata/ownerReferences", "value": [OWNER]}]]
    app.sensor.on_resource_drift_detected.assert_called_once()
    assert app.sensor.on_resource_drift_detected.call_args.args[-1] == ["metadata.ownerReferences"]


def test_sync_hpa_appends_the_owner_to_other_owner_references():
    app = adopted(make_app())
    other = V1OwnerReference(api_version="v1", kind="Thing", name="other", uid="uid-other")
    live = copy.deepcopy(app.hpa)
    live.metadata.owner_references = [other]

    patches, _ = sync_hpa(app, live)

    assert patches == [[{"op": "add", "path": "/metadata/ownerReferences/-", "value": OWNER}]]


def test_sync_hpa_repairs_the_owner_together_with_spec_drift():
    app = adopted(make_app())
    live = copy.deepcopy(app.hpa)
    live.metadata.owner_references = None
    live.spec.max_replicas = 5

    patches, _ = sync_hpa(app, live)

    assert len(patches) == 1
    paths = [op["path"] for op in patches[0]]
    assert "/spec/maxReplicas" in paths
    assert paths[-1] == "/metadata/ownerReferences"
    assert app.sensor.on_resource_drift_detected.call_args.args[-1] == [
        "spec",
        "metadata.ownerReferences",
    ]


def test_sync_hpa_leaves_an_owned_up_to_date_hpa_alone():
    app = adopted(make_app())

    patches, created = sync_hpa(app, copy.deepcopy(app.hpa))

    assert patches == [] and created == []
    app.sensor.on_resource_drift_detected.assert_not_called()


def test_sync_hpa_creates_a_missing_hpa_with_its_owner():
    app = adopted(make_app())

    patches, created = sync_hpa(app, None)

    assert patches == []
    assert [hpa.metadata.owner_references for hpa in created] == [[OWNER]]
