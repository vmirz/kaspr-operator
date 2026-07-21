"""Unit tests for KasprApp handler related-resource monitoring."""

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

from kubernetes_asyncio.client import ApiException
from kubernetes_asyncio.client import V1ConfigMap, V1ObjectMeta

from kaspr.handlers import kasprapp as handler
from kaspr.resources.appcomponent import BaseAppComponent


class _StopFlag:
    def __init__(self):
        self.stopped = False
        self.wait_calls = []

    def __bool__(self):
        return self.stopped

    async def wait(self, seconds=None):
        self.wait_calls.append(seconds)
        self.stopped = True
        return True


class _FakeApp:
    def __init__(self, stop_flag):
        self.stop_flag = stop_flag
        self.tasks = None
        self.patched = False

    def with_agents(self, agents):
        self.agents = agents

    def with_webviews(self, webviews):
        self.webviews = webviews

    def with_tables(self, tables):
        self.tables = tables

    def with_tasks(self, tasks):
        self.tasks = tasks

    async def patch_volume_mounted_resources(self):
        self.patched = True
        self.stop_flag.stopped = True


class _DummyComponent(BaseAppComponent):
    KIND = "KasprAgent"
    COMPONENT_TYPE = "KasprAgent"
    PLURAL_NAME = "kaspragents"
    kaspr_resource = SimpleNamespace(component_name=lambda name: name)

    def __init__(self):
        super().__init__(
            name="dummy-agent",
            kind=self.KIND,
            namespace="test-namespace",
            component_type=self.COMPONENT_TYPE,
            labels={self.KASPR_APP_NAME_LABEL: "test-app"},
        )
        self.config_map_name = "dummy-agent"
        self.file_name = "dummy-agent.yaml"
        self.file_data = "name: dummy-agent\n"
        self.app_components = None


def test_monitor_related_resources_uses_task_schema(monkeypatch):
    stop_flag = _StopFlag()
    fake_app = _FakeApp(stop_flag)
    seen = {}
    task_spec = {
        "name": "develop-sweep-observations",
        "schedule": {"interval": "5m"},
        "processors": {"pipeline": [], "operations": []},
    }

    async def fake_fetch_related_resources(name, namespace):
        return {
            "agents": [],
            "webviews": [],
            "tables": [],
            "tasks": [
                {
                    "metadata": {
                        "name": "develop-sweep-observations",
                        "labels": {"kaspr.io/app": name},
                    },
                    "spec": task_spec,
                }
            ],
            "success": True,
        }

    class FakeTaskSchema:
        def load(self, value):
            seen["task_spec"] = value
            return {"parsed": True, "name": value["name"]}

    monkeypatch.setattr(handler, "fetch_app_related_resources", fake_fetch_related_resources)
    monkeypatch.setattr(handler.KasprAppSpecSchema, "load", lambda self, value: object())
    monkeypatch.setattr(
        handler.KasprApp,
        "from_spec",
        classmethod(lambda cls, *args, **kwargs: fake_app),
    )
    monkeypatch.setattr(handler, "KasprTaskSpecSchema", FakeTaskSchema)
    monkeypatch.setattr(
        handler.KasprTask,
        "from_spec",
        staticmethod(
            lambda name, kind, namespace, spec_model, labels: {
                "name": name,
                "spec_model": spec_model,
                "labels": labels,
            }
        ),
    )

    asyncio.run(
        handler.monitor_related_resources(
            stopped=stop_flag,
            name="develop-materializer-control-plane",
            body={},
            spec={},
            meta={},
            labels={},
            annotations={},
            status={},
            namespace="kafka-sql",
            patch={},
            logger=Mock(),
        )
    )

    assert seen["task_spec"] == task_spec
    assert fake_app.patched is True
    assert fake_app.tasks == [
        {
            "name": "develop-sweep-observations",
            "spec_model": {"parsed": True, "name": "develop-sweep-observations"},
            "labels": {"kaspr.io/app": "develop-materializer-control-plane"},
        }
    ]
    assert stop_flag.wait_calls == [10]


def test_patch_resource_skips_missing_queue():
    patch = SimpleNamespace(status={})

    asyncio.run(handler.patch_resource(name="missing-app", patch=patch))

    assert patch.status == {}


def test_process_reconciliation_requests_skips_missing_queue(monkeypatch):
    handler.names_in_queue.add("missing-app")
    reconcile_calls = []

    async def fake_reconcile(*args, **kwargs):
        reconcile_calls.append(True)

    monkeypatch.setattr(handler, "reconcile", fake_reconcile)

    asyncio.run(
        handler.process_reconciliation_requests(
            name="missing-app",
            namespace="test-namespace",
            spec={},
            meta={},
            status={},
            patch=SimpleNamespace(status={}),
            annotations={},
            logger=Mock(),
            stopped=False,
        )
    )

    assert reconcile_calls == []
    assert "missing-app" not in handler.names_in_queue


def test_on_delete_cleans_up_global_state(monkeypatch):
    app_name = "delete-me"
    handler.reconciliation_queue[app_name].put_nowait(app_name)
    handler.patch_request_queues[app_name].put_nowait({"field": "status", "value": {}})
    _ = handler.reconciliation_locks[app_name]
    handler.names_in_queue.add(app_name)
    handler.hung_member_tracking[(app_name, 0)] = 1

    asyncio.run(handler.on_delete(app_name))

    assert app_name not in handler.reconciliation_queue
    assert app_name not in handler.patch_request_queues
    assert app_name not in handler.reconciliation_locks
    assert app_name not in handler.names_in_queue
    assert (app_name, 0) not in handler.hung_member_tracking


def test_prepare_config_map_patch_updates_hash_annotation():
    component = _DummyComponent()

    patch = component.prepare_config_map_patch(component.config_map)

    assert {
        "op": "replace",
        "path": "/metadata/annotations",
        "value": component.config_map.metadata.annotations,
    } in patch
    assert {
        "op": "replace",
        "path": "/data",
        "value": component.config_map.data,
    } in patch
    assert component.config_map.metadata.annotations["kaspr.io/resource-hash"] == component.hash


def test_prepare_config_map_hash_ignores_resource_hash_annotation():
    component = _DummyComponent()

    expected_hash = component.prepare_config_map_hash(component.config_map)
    component.config_map.metadata.annotations["kaspr.io/resource-hash"] = "stale-hash"

    assert component.prepare_config_map_hash(component.config_map) == expected_hash


def test_synchronize_calls_unite_before_creating_config_map(monkeypatch):
    component = _DummyComponent()
    calls = []

    async def fake_fetch_config_map(*args, **kwargs):
        return None

    async def fake_create_config_map(*args, **kwargs):
        calls.append("create")

    def fake_unite():
        calls.append("unite")

    component.sensor = Mock()
    component.sensor.on_resource_sync_start.return_value = object()

    monkeypatch.setattr(component, "fetch_config_map", fake_fetch_config_map)
    monkeypatch.setattr(component, "create_config_map", fake_create_config_map)
    monkeypatch.setattr(component, "unite", fake_unite)

    asyncio.run(component.synchronize())

    assert calls == ["unite", "create"]


def test_synchronize_patches_stale_hash_annotation_when_data_matches(monkeypatch):
    component = _DummyComponent()
    patches = []

    actual_config_map = V1ConfigMap(
        metadata=V1ObjectMeta(
            name=component.config_map_name,
            namespace=component.namespace,
            annotations={"kaspr.io/resource-hash": "stale-hash"},
        ),
        data=component.config_map.data,
    )

    async def fake_fetch_config_map(*args, **kwargs):
        return actual_config_map

    async def fake_patch_config_map(*args, **kwargs):
        patches.append(kwargs["config_map"])

    component.sensor = Mock()
    component.sensor.on_resource_sync_start.return_value = object()

    monkeypatch.setattr(component, "fetch_config_map", fake_fetch_config_map)
    monkeypatch.setattr(component, "patch_config_map", fake_patch_config_map)

    asyncio.run(component.synchronize())

    assert len(patches) == 1
    assert {
        "op": "replace",
        "path": "/metadata/annotations",
        "value": component.config_map.metadata.annotations,
    } in patches[0]
    assert {
        "op": "replace",
        "path": "/data",
        "value": component.config_map.data,
    } in patches[0]


def test_on_error_stringifies_api_exception_message():
    patch = SimpleNamespace(status={})
    error = ApiException(status=422, reason="Unprocessable Entity")
    error.body = (
        '{"message":"StatefulSet.apps \"develop-materializer-manual-orders-app\" '
        'is invalid: spec.template.spec.initContainers[0].volumeMounts[1].name: '
        'Not found: \"github-ssh\""}'
    )

    handler.on_error(error, spec={}, meta={"generation": 1}, status={}, patch=patch)

    progressing = next(
        cond for cond in patch.status["conditions"] if cond["type"] == "Progressing"
    )
    assert isinstance(progressing["message"], str)
    assert "Kubernetes API error (422): Unprocessable Entity" in progressing["message"]
    assert 'Not found: "github-ssh"' in progressing["message"]


def test_on_error_stringifies_generic_exception():
    patch = SimpleNamespace(status={})

    handler.on_error(
        ValueError("broken spec"),
        spec={},
        meta={"generation": 1},
        status={},
        patch=patch,
    )

    progressing = next(
        cond for cond in patch.status["conditions"] if cond["type"] == "Progressing"
    )
    assert progressing["message"] == "broken spec"


def test_on_create_requests_reconciliation(monkeypatch):
    calls = []

    class FakeApp:
        reconciliation_paused = False

        async def create(self):
            calls.append("create")

    async def fake_request_reconciliation(name, namespace=None, logger=None, **kwargs):
        calls.append(("request_reconciliation", name, namespace))

    monkeypatch.setattr(handler.KasprAppSpecSchema, "load", lambda self, value: object())
    monkeypatch.setattr(
        handler.KasprApp,
        "from_spec",
        classmethod(lambda cls, *args, **kwargs: FakeApp()),
    )
    monkeypatch.setattr(handler, "request_reconciliation", fake_request_reconciliation)

    asyncio.run(
        handler.on_create(
            spec={},
            name="test-app",
            meta={},
            status={},
            patch=SimpleNamespace(status={}),
            namespace="test-namespace",
            annotations={},
            logger=Mock(),
        )
    )

    assert calls == ["create", ("request_reconciliation", "test-app", "test-namespace")]