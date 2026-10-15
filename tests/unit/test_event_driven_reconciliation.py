"""Unit tests for event-driven reconciliation of KasprApps and their components."""

import asyncio
import copy
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import kopf
import pytest
from kubernetes_asyncio.client import (
    V1ConfigMap,
    V1ObjectMeta,
    V1Pod,
    V1PodList,
    V1StatefulSetStatus,
)

from kaspr.handlers import appcomponent as component_handler
from kaspr.handlers import kasprapp as handler
from kaspr.resources import KasprApp
from kaspr.resources.appcomponent import BaseAppComponent
from kaspr.resources.kasprapp import PodMetadataCache
from kaspr.types.schemas.kasprapp_spec import KasprAppSpecSchema
from kaspr.types.settings import Settings


APP_SPEC = {
    "replicas": 1,
    "bootstrapServers": "kafka:9092",
    "authentication": {"type": "plain"},
    "storage": {"type": "persistent-claim", "class": "standard", "size": "1Gi", "deleteClaim": True},
}


@pytest.fixture(autouse=True)
def operator_settings(monkeypatch):
    """Settings normally installed on KasprApp by the operator's startup handler."""
    settings = Settings()
    monkeypatch.setattr(KasprApp, "conf", settings, raising=False)
    monkeypatch.setattr(KasprApp, "sensor", None, raising=False)
    monkeypatch.setattr(BaseAppComponent, "sensor", None, raising=False)
    return settings


@pytest.fixture(autouse=True)
def clean_handler_state():
    handler.app_states.clear()
    handler.names_in_queue.clear()
    handler.reconciliation_queue.clear()
    handler.component_observations.clear()
    handler.hung_member_tracking.clear()
    handler.reconciliation_requested_at.clear()
    yield
    handler.app_states.clear()
    handler.names_in_queue.clear()
    handler.reconciliation_queue.clear()
    handler.component_observations.clear()
    handler.hung_member_tracking.clear()
    handler.reconciliation_requested_at.clear()


def make_app(name="test-app", namespace="test-ns", annotations=None, **spec_overrides):
    spec = KasprAppSpecSchema().load({**APP_SPEC, **spec_overrides})
    app = KasprApp.from_spec(name, "KasprApp", namespace, spec, annotations or {})
    app.logger = Mock()
    return app


def live_copy(stateful_set, resource_version="100", generation=1, replicas=1):
    """A StatefulSet as the API server would return it after creating `stateful_set`."""
    live = copy.deepcopy(stateful_set)
    live.metadata.resource_version = resource_version
    live.metadata.generation = generation
    live.spec.replicas = replicas
    return live


class FakeApp:
    """The parts of KasprApp used by update_status."""

    stateful_set_name = "test-app-app"

    def __init__(self, actual_status=None, resource_version="1", fingerprint="desired"):
        self.annotations = {}
        self.python_packages = None
        self.static_group_membership_enabled = False
        self.replicas = 1
        self.terminate_calls = []
        self.rebalance_calls = []
        self.conf = SimpleNamespace(
            hung_member_detection_enabled=True,
            hung_rebalancing_threshold_seconds=300,
            auto_rebalance_enabled=True,
            client_status_check_enabled=True,
        )
        self.actual_status = actual_status
        self.resource_version = resource_version
        self.fingerprint = fingerprint
        self.observed_stateful_set = None
        self.fetch_kwargs = []

    async def fetch_app_status(self, **kwargs):
        self.fetch_kwargs.append(kwargs)
        if self.actual_status is None:
            self.observed_stateful_set = None
            return None
        self.observed_stateful_set = SimpleNamespace(
            metadata=SimpleNamespace(resource_version=self.resource_version)
        )
        return copy.deepcopy(self.actual_status)

    def prepare_statefulset_fingerprint(self, stateful_set):
        return self.fingerprint

    async def terminate_member(self, member_id):
        self.terminate_calls.append(member_id)
        return True

    async def request_rebalance(self, status=None):
        self.rebalance_calls.append(status)
        return True, "Rebalance requested successfully"


def healthy_status(**overrides):
    status = {
        "kasprVersion": "0.11.25",
        "availableMembers": 1,
        "desiredMembers": 1,
        "rolloutInProgress": False,
        "members": [{"id": 0, "leader": True, "rebalancing": False, "recovering": False}],
    }
    status.update(overrides)
    return status


def use_fake_app(monkeypatch, fake_app):
    monkeypatch.setattr(handler.KasprAppSpecSchema, "load", lambda self, value: object())
    monkeypatch.setattr(
        handler.KasprApp, "from_spec", classmethod(lambda cls, *args, **kwargs: fake_app)
    )


def run_update_status(status, state, related_resources=None, generation=1):
    patch = SimpleNamespace(status={})
    asyncio.run(
        handler.update_status(
            name="test-app",
            spec={},
            meta={"generation": generation},
            status=status,
            patch=patch,
            namespace="test-ns",
            annotations={},
            logger=Mock(),
            related_resources=related_resources,
            state=state,
        )
    )
    return patch.status


# ---------------------------------------------------------------------------
# Status updates
# ---------------------------------------------------------------------------


def test_status_changes_only_returns_changed_fields():
    current = {
        "observedGeneration": 2,
        "members": [{"id": 0}],
        "pythonPackages": {"cacheMode": "ephemeral"},
        "kasprVersion": "0.11.24",
    }
    update = {
        "observedGeneration": 2,
        "members": [{"id": 0}],
        "pythonPackages": None,
        "kasprVersion": "0.11.25",
        "rebalanceRequired": False,
        "absentAndCleared": None,
    }

    assert handler._status_changes(current, update) == {
        "pythonPackages": None,
        "kasprVersion": "0.11.25",
        "rebalanceRequired": False,
    }


def test_update_status_writes_nothing_when_app_is_unchanged(monkeypatch):
    fake_app = FakeApp(actual_status=healthy_status())
    use_fake_app(monkeypatch, fake_app)
    state = handler.AppRuntimeState()

    first = run_update_status({}, state)
    assert first["observedGeneration"] == 1
    assert first["availableMembers"] == "1/1"
    assert first["rebalanceRequired"] is False

    # The first refresh of a generation reports it as new; the next one as healthy.
    second = run_update_status({**first}, state)
    assert set(second) == {"conditions"}
    ready = next(c for c in second["conditions"] if c["type"] == "Ready")
    assert ready["reason"] == "Healthy"

    third = run_update_status({**first, **second}, state)

    # The old operator re-sent the whole status on every refresh.
    assert third == {}


def test_update_status_passes_pod_cache_kept_in_state(monkeypatch):
    fake_app = FakeApp(actual_status=healthy_status())
    use_fake_app(monkeypatch, fake_app)
    state = handler.AppRuntimeState()

    run_update_status({}, state)

    assert fake_app.fetch_kwargs == [{"pod_cache": state.pod_cache}]


def test_rebalance_required_persists_until_rebalance_succeeds(monkeypatch):
    fake_app = FakeApp(actual_status=healthy_status(rolloutInProgress=True))
    fake_app.static_group_membership_enabled = True
    use_fake_app(monkeypatch, fake_app)
    state = handler.AppRuntimeState()
    status = {
        "linkedResources": {
            "agents": [{"name": "agent-1", "hash": "a", "topicName": "orders"}],
            "webviews": [],
            "tables": [],
            "tasks": [],
        },
        "rebalanceRequired": False,
    }
    related = {
        "agents": [
            {
                "metadata": {"name": "agent-1"},
                "spec": {"input": {"topic": {"name": "orders,returns"}}},
                "status": {"hash": "a"},
            }
        ],
        "webviews": [],
        "tables": [],
        "tasks": [],
        "success": True,
        "hashes": {"agents": {"agent-1": "b"}},
    }

    # The subscription change arrives while its rollout is still in progress.
    changes = run_update_status(status, state, related_resources=related)
    assert changes["rebalanceRequired"] is True
    assert changes["linkedResources"]["agents"][0]["hash"] == "b"
    assert fake_app.rebalance_calls == []
    status = {**status, **changes}

    # Later status refreshes keep the flag until the rollout is over...
    assert "rebalanceRequired" not in run_update_status(status, state)
    assert fake_app.rebalance_calls == []

    # ...and then request the rebalance with the status they already fetched.
    fake_app.actual_status = healthy_status(rolloutInProgress=False)
    changes = run_update_status(status, state)
    assert changes["rebalanceRequired"] is False
    assert len(fake_app.rebalance_calls) == 1
    assert fake_app.rebalance_calls[0]["availableMembers"] == 1


def test_rebalance_required_is_cleared_without_static_membership(monkeypatch):
    fake_app = FakeApp(actual_status=healthy_status())
    use_fake_app(monkeypatch, fake_app)
    related = {"agents": [], "webviews": [], "tables": [], "tasks": [], "success": True}

    changes = run_update_status(
        {"rebalanceRequired": True}, handler.AppRuntimeState(), related_resources=related
    )

    assert changes["rebalanceRequired"] is False


def test_status_refresh_schedules_reconcile_when_statefulset_is_missing(monkeypatch):
    fake_app = FakeApp(actual_status=None)
    use_fake_app(monkeypatch, fake_app)
    state = handler.AppRuntimeState(desired_statefulset_fingerprint="desired")

    async def run():
        await handler.update_status(
            name="test-app", spec={}, meta={"generation": 1}, status={},
            patch=SimpleNamespace(status={}), namespace="test-ns", annotations={},
            logger=Mock(), state=state,
        )
        return asyncio.get_running_loop().time()

    current_time = asyncio.run(run())

    assert state.next_reconcile_reason == "drift"
    assert state.next_reconcile_at <= current_time


def test_status_refresh_schedules_reconcile_when_statefulset_drifted(monkeypatch):
    fake_app = FakeApp(actual_status=healthy_status(), fingerprint="edited-by-hand")
    use_fake_app(monkeypatch, fake_app)
    state = handler.AppRuntimeState(desired_statefulset_fingerprint="desired")

    run_update_status({}, state)

    assert state.next_reconcile_reason == "drift"
    assert state.next_reconcile_at is not None


@pytest.mark.parametrize(
    "state_kwargs, related",
    [
        # Nothing rendered yet to compare with.
        ({}, None),
        # Failing reconciliations are retried on their own schedule.
        ({"desired_statefulset_fingerprint": "desired", "reconcile_failed": True}, None),
        # A full reconciliation has just synced the StatefulSet.
        ({"desired_statefulset_fingerprint": "desired"}, {"agents": [], "webviews": [], "tables": [], "tasks": [], "success": True}),
    ],
)
def test_status_refresh_does_not_schedule_drift_reconcile(monkeypatch, state_kwargs, related):
    fake_app = FakeApp(actual_status=healthy_status(), fingerprint="other")
    use_fake_app(monkeypatch, fake_app)
    state = handler.AppRuntimeState(**state_kwargs)

    run_update_status({}, state, related_resources=related)

    assert state.next_reconcile_at is None


def _packages_fake_app(monkeypatch, evaluations, pods):
    fake_app = FakeApp(actual_status=healthy_status())
    fake_app.python_packages = SimpleNamespace(packages=["six"])
    fake_app.packages_hash = "packages-v1"
    fake_app.namespace = "test-ns"
    fake_app.core_v1_api = object()
    fake_app.labels = SimpleNamespace(
        kasper_label_selectors=lambda: SimpleNamespace(as_dict=lambda: {"kaspr.io/cluster": "test-app"})
    )
    fake_app.list_calls = 0

    async def list_pods(*args, **kwargs):
        fake_app.list_calls += 1
        return pods

    fake_app.list_pods = list_pods

    async def fake_fetch_python_packages_status(app, logger, pods=None):
        evaluations.append(pods)
        return {"cacheMode": "ephemeral"}, {
            "state": fake_app.packages_state,
            "reason": "PackagesInstalled" if fake_app.packages_state == "Ready" else "Installing",
            "message": "",
        }

    monkeypatch.setattr(handler, "fetch_python_packages_status", fake_fetch_python_packages_status)
    use_fake_app(monkeypatch, fake_app)
    return fake_app


def test_python_packages_status_is_reread_only_when_pods_change(monkeypatch):
    evaluations = []
    pods = V1PodList(items=[V1Pod(metadata=V1ObjectMeta(name="test-app-app-0"))])
    fake_app = _packages_fake_app(monkeypatch, evaluations, pods)
    fake_app.packages_state = "Ready"
    state = handler.AppRuntimeState()

    status = run_update_status({}, state)
    assert len(evaluations) == 1
    assert status["pythonPackages"] == {"cacheMode": "ephemeral"}

    # An installation that is Ready on an unchanged StatefulSet is not re-read.
    run_update_status(status, state)
    assert len(evaluations) == 1
    assert fake_app.list_calls == 1

    # Pods changing moves the StatefulSet's resourceVersion.
    fake_app.resource_version = "2"
    run_update_status(status, state)
    assert len(evaluations) == 2


def test_python_packages_status_follows_installation_while_pods_exist(monkeypatch):
    evaluations = []
    pods = V1PodList(items=[V1Pod(metadata=V1ObjectMeta(name="test-app-app-0"))])
    fake_app = _packages_fake_app(monkeypatch, evaluations, pods)
    fake_app.packages_state = "Installing"
    state = handler.AppRuntimeState()

    run_update_status({}, state)
    run_update_status({}, state)

    assert len(evaluations) == 2


def test_python_packages_status_waits_for_pods_of_a_stopped_app(monkeypatch):
    evaluations = []
    fake_app = _packages_fake_app(monkeypatch, evaluations, V1PodList(items=[]))
    fake_app.packages_state = "Installing"
    state = handler.AppRuntimeState()

    run_update_status({}, state)
    run_update_status({}, state)

    # Nothing can change until the StatefulSet creates pods.
    assert len(evaluations) == 1


def test_python_packages_status_reuses_pods_listed_for_members(monkeypatch):
    evaluations = []
    pods = V1PodList(items=[V1Pod(metadata=V1ObjectMeta(name="test-app-app-0"))])
    fake_app = _packages_fake_app(monkeypatch, evaluations, pods)
    fake_app.packages_state = "Ready"
    state = handler.AppRuntimeState()
    original_fetch = fake_app.fetch_app_status

    async def fetch_listing_pods(**kwargs):
        kwargs["pod_cache"].listed_pods = pods
        return await original_fetch(**kwargs)

    fake_app.fetch_app_status = fetch_listing_pods

    run_update_status({}, state)

    assert evaluations == [pods]
    assert fake_app.list_calls == 0


# ---------------------------------------------------------------------------
# Scheduling
# ---------------------------------------------------------------------------


def _run_timer(monkeypatch, settings, prepare=None, annotations=None, status=None, quiet_for=5.0):
    """Run one tick of the KasprApp timer and return the app's runtime state.

    Requests made by `prepare` are aged by `quiet_for` seconds (None keeps them fresh).
    """
    monkeypatch.setattr(handler, "_get_settings", lambda: settings)

    async def run():
        state = handler.get_app_state("test-ns", "test-app")
        if prepare:
            await prepare(state, asyncio.get_running_loop().time())
        if quiet_for is not None:
            for key, (first, last) in list(handler.reconciliation_requested_at.items()):
                handler.reconciliation_requested_at[key] = (first - quiet_for, last - quiet_for)
        await handler.process_reconciliation_requests(
            name="test-app",
            namespace="test-ns",
            spec={},
            meta={"generation": 1},
            status=status or {},
            patch=SimpleNamespace(status={}),
            annotations=annotations or {},
            logger=Mock(),
            stopped=False,
        )
        return state, asyncio.get_running_loop().time()

    return asyncio.run(run())


def test_requested_reconciliation_runs_and_schedules_periodic_resync(monkeypatch):
    settings = Settings(status_update_interval_seconds=30, reconcile_interval_seconds=300)
    seen = []

    async def fake_reconcile(*args, trigger_source=None, state=None, **kwargs):
        seen.append(trigger_source)
        return handler.RECONCILED

    monkeypatch.setattr(handler, "reconcile", fake_reconcile)

    async def prepare(state, now):
        await handler.request_reconciliation("test-app", namespace="test-ns")

    state, current_time = _run_timer(monkeypatch, settings, prepare)

    assert seen == ["queue"]
    assert state.reconcile_failed is False
    assert state.last_status_update_at is not None
    assert state.next_reconcile_reason == "resync"
    assert 300 <= state.next_reconcile_at - current_time <= 331


def test_requests_wait_for_a_quiet_period(monkeypatch):
    calls = []

    async def fake_reconcile(*args, **kwargs):
        calls.append("reconcile")
        return handler.RECONCILED

    monkeypatch.setattr(handler, "reconcile", fake_reconcile)

    async def prepare(state, now):
        await handler.request_reconciliation("test-app", namespace="test-ns")

    _run_timer(monkeypatch, Settings(), prepare, quiet_for=None)

    assert calls == []
    assert handler.reconciliation_queue[("test-ns", "test-app")].qsize() == 1


def test_requests_wait_no_longer_than_the_maximum(monkeypatch):
    calls = []

    async def fake_reconcile(*args, **kwargs):
        calls.append("reconcile")
        return handler.RECONCILED

    monkeypatch.setattr(handler, "reconcile", fake_reconcile)

    async def prepare(state, now):
        # Requests have kept arriving for longer than the maximum wait.
        await handler.request_reconciliation("test-app", namespace="test-ns")
        handler.reconciliation_requested_at[("test-ns", "test-app")] = (
            now - handler.RECONCILE_DEBOUNCE_MAX_SECONDS - 1,
            now,
        )

    _run_timer(monkeypatch, Settings(), prepare, quiet_for=None)

    assert calls == ["reconcile"]
    assert ("test-ns", "test-app") not in handler.reconciliation_requested_at


def test_request_during_reconciliation_is_not_lost(monkeypatch):
    settings = Settings()

    async def fake_reconcile(*args, **kwargs):
        # A component changes while the app is being reconciled.
        await handler.request_reconciliation("test-app", namespace="test-ns")
        return handler.RECONCILED

    monkeypatch.setattr(handler, "reconcile", fake_reconcile)

    async def prepare(state, now):
        await handler.request_reconciliation("test-app", namespace="test-ns")

    _run_timer(monkeypatch, settings, prepare)

    assert handler.reconciliation_queue[("test-ns", "test-app")].qsize() == 1


def test_failed_reconciliation_is_retried_and_status_left_alone(monkeypatch):
    settings = Settings(status_update_interval_seconds=30, reconcile_interval_seconds=300)
    calls = []

    async def fake_reconcile(*args, **kwargs):
        calls.append("reconcile")
        return handler.RETRY

    async def fake_update_status(*args, **kwargs):
        calls.append("update_status")

    monkeypatch.setattr(handler, "reconcile", fake_reconcile)
    monkeypatch.setattr(handler, "update_status", fake_update_status)

    async def prepare(state, now):
        await handler.request_reconciliation("test-app", namespace="test-ns")

    state, current_time = _run_timer(monkeypatch, settings, prepare)

    assert state.reconcile_failed is True
    assert state.next_reconcile_reason == "retry"
    assert state.next_reconcile_at - current_time == pytest.approx(30, abs=1)

    # A failing app keeps its error conditions instead of status refreshes.
    async def make_status_due(state, now):
        state.desired_statefulset_fingerprint = "desired"
        state.last_status_update_at = now - 60
        state.next_reconcile_at = now + 30

    _run_timer(monkeypatch, settings, make_status_due)
    assert calls == ["reconcile"]


def test_permanently_failing_reconciliation_waits_for_a_change(monkeypatch):
    settings = Settings(status_update_interval_seconds=30, reconcile_interval_seconds=300)

    async def fake_reconcile(*args, **kwargs):
        return handler.FAILED_PERMANENTLY

    monkeypatch.setattr(handler, "reconcile", fake_reconcile)

    async def prepare(state, now):
        await handler.request_reconciliation("test-app", namespace="test-ns")

    state, current_time = _run_timer(monkeypatch, settings, prepare)

    assert state.reconcile_failed is True
    assert state.next_reconcile_reason == "resync"
    assert state.next_reconcile_at - current_time >= 300


def test_periodic_resync_can_be_disabled(monkeypatch):
    settings = Settings(reconcile_interval_seconds=0)

    async def fake_reconcile(*args, **kwargs):
        return handler.RECONCILED

    monkeypatch.setattr(handler, "reconcile", fake_reconcile)

    async def prepare(state, now):
        await handler.request_reconciliation("test-app", namespace="test-ns")

    state, _ = _run_timer(monkeypatch, settings, prepare)

    assert state.next_reconcile_at is None


@pytest.mark.parametrize("reason", ["resync", "retry", "drift"])
def test_due_reconciliation_runs_with_its_reason(monkeypatch, reason):
    seen = []

    async def fake_reconcile(*args, trigger_source=None, **kwargs):
        seen.append(trigger_source)
        return handler.RECONCILED

    monkeypatch.setattr(handler, "reconcile", fake_reconcile)

    async def prepare(state, now):
        state.desired_statefulset_fingerprint = "desired"
        state.next_reconcile_at = now - 1
        state.next_reconcile_reason = reason

    _run_timer(monkeypatch, Settings(), prepare)

    assert seen == [reason]


def test_status_is_refreshed_when_due(monkeypatch):
    seen = []

    async def fake_update_status(*args, state=None, related_resources=None, **kwargs):
        seen.append((state, related_resources))

    monkeypatch.setattr(handler, "update_status", fake_update_status)

    async def prepare(state, now):
        state.desired_statefulset_fingerprint = "desired"
        state.next_reconcile_at = now + 300
        state.last_status_update_at = now - 31

    state, current_time = _run_timer(monkeypatch, Settings(status_update_interval_seconds=30), prepare)

    assert seen == [(state, None)]
    assert state.last_status_update_at == pytest.approx(current_time, abs=1)


def test_status_is_not_refreshed_while_reconciliation_is_paused(monkeypatch):
    seen = []

    async def fake_update_status(*args, **kwargs):
        seen.append("update_status")

    monkeypatch.setattr(handler, "update_status", fake_update_status)

    async def prepare(state, now):
        state.desired_statefulset_fingerprint = "desired"
        state.next_reconcile_at = now + 300
        state.last_status_update_at = now - 31

    _run_timer(
        monkeypatch,
        Settings(),
        prepare,
        annotations={"kaspr.io/pause-reconciliation": "true"},
    )

    assert seen == []


def test_first_tick_without_request_schedules_fallback_reconciliation(monkeypatch):
    calls = []

    async def fake_reconcile(*args, **kwargs):
        calls.append("reconcile")
        return handler.RECONCILED

    monkeypatch.setattr(handler, "reconcile", fake_reconcile)

    state, current_time = _run_timer(monkeypatch, Settings(status_update_interval_seconds=30))

    assert calls == []
    assert state.next_reconcile_at - current_time == pytest.approx(30, abs=1)


# ---------------------------------------------------------------------------
# Component events
# ---------------------------------------------------------------------------


def _component_body(uid="uid-1", app="app-a", generation=1, labels=None, namespace="test-ns", topic="orders", status=None):
    body = {
        "kind": "KasprAgent",
        "metadata": {
            "uid": uid,
            "name": "agent-1",
            "namespace": namespace,
            "generation": generation,
            "labels": {"kaspr.io/app": app, **(labels or {})},
        },
        "spec": {"input": {"topic": {"name": topic}}},
    }
    if status is not None:
        body["status"] = status
    return body


@pytest.fixture
def requested(monkeypatch):
    calls = []

    async def fake_request_reconciliation(name, namespace=None, **kwargs):
        calls.append((namespace, name))

    monkeypatch.setattr(handler, "request_reconciliation", fake_request_reconciliation)
    return calls


def notify(event_type, body):
    asyncio.run(handler.notify_component_event(event_type, body, Mock()))


def test_added_component_reconciles_its_app(requested):
    notify("ADDED", _component_body())

    assert requested == [("test-ns", "app-a")]


def test_component_status_updates_do_not_reconcile_its_app(requested):
    notify(None, _component_body())
    requested.clear()

    # The component's own status patch. Without a status subresource, it also
    # increments the component's generation.
    notify("MODIFIED", _component_body(generation=2, status={"hash": "h"}))

    assert requested == []


def test_component_spec_change_reconciles_its_app(requested):
    notify(None, _component_body())
    requested.clear()

    notify("MODIFIED", _component_body(generation=2, topic="returns"))

    assert requested == [("test-ns", "app-a")]


def test_component_label_change_reconciles_its_app(requested):
    notify(None, _component_body())
    requested.clear()

    # Labels are rendered into the component's config map, hence its hash.
    notify("MODIFIED", _component_body(labels={"team": "orders"}))

    assert requested == [("test-ns", "app-a")]


def test_component_moved_between_apps_reconciles_both(requested):
    notify(None, _component_body(app="app-a"))
    requested.clear()

    notify("MODIFIED", _component_body(app="app-b"))

    assert sorted(requested) == [("test-ns", "app-a"), ("test-ns", "app-b")]


def test_deleted_component_reconciles_its_app(requested):
    notify(None, _component_body())
    requested.clear()

    notify("DELETED", _component_body())

    assert requested == [("test-ns", "app-a")]
    assert handler.component_observations == {}


def test_deleted_component_unknown_to_its_app_is_ignored(requested):
    notify("DELETED", _component_body())

    assert requested == []


def test_component_its_app_was_reconciled_without_is_forgotten(requested):
    notify(None, _component_body(uid="deleted"))
    notify(None, _component_body(uid="kept"))
    requested.clear()

    # The app's reconciliation no longer lists the deleted component...
    handler._record_component_observations(
        {"agents": [_component_body(uid="kept")], "webviews": [], "tables": [], "tasks": []},
        "test-ns",
        "app-a",
    )
    assert set(handler.component_observations) == {"kept"}

    # ...so its (late) deletion event triggers nothing more.
    notify("DELETED", _component_body(uid="deleted"))
    assert requested == []


def test_components_read_by_a_reconciliation_trigger_no_repeat(requested):
    # The app's reconciliation lists its components itself...
    handler._record_component_observations(
        {"agents": [_component_body()], "webviews": [], "tables": [], "tasks": []},
        "test-ns",
        "app-a",
    )

    # ...so seeing them in the operator's own listing (e.g. at startup) adds nothing.
    notify(None, _component_body())
    assert requested == []

    notify("MODIFIED", _component_body(generation=2, topic="returns"))
    assert requested == [("test-ns", "app-a")]


def test_component_without_app_label_is_ignored(requested):
    body = _component_body()
    body["metadata"]["labels"] = {}

    notify("ADDED", body)

    assert requested == []


# ---------------------------------------------------------------------------
# Component app status
# ---------------------------------------------------------------------------


def _component(app_status=None, deleting=False, name="agent-1"):
    owner = {
        "apiVersion": "kaspr.io/v1alpha1",
        "kind": "KasprAgent",
        "metadata": {"name": name, "namespace": "test-ns", "uid": f"uid-{name}"},
    }
    if deleting:
        owner["metadata"]["deletionTimestamp"] = "2026-10-15T00:00:00Z"
    if app_status is not None:
        owner["status"] = {"app": {"name": "app-a", "status": app_status}}
    component = SimpleNamespace(
        owner=owner,
        app_name="app-a",
        KIND="KasprAgent",
        cluster=name,
        namespace="test-ns",
        patched=[],
    )

    async def patch_app_status(status):
        component.patched.append(status)
        return {"status": {"app": {"name": "app-a", "status": status}}}

    component.patch_app_status = patch_app_status
    return component


@pytest.fixture
def posted_events(monkeypatch):
    events = []
    monkeypatch.setattr(kopf, "event", lambda obj, **kw: events.append(("event", obj["metadata"]["name"], kw["reason"])))
    monkeypatch.setattr(kopf, "warn", lambda obj, **kw: events.append(("warn", obj["metadata"]["name"], kw["reason"])))
    return events


def test_app_reports_itself_to_components_that_could_not_find_it(posted_events):
    not_found = _component(handler.APP_NOT_FOUND, name="not-found")
    found = _component(handler.APP_FOUND, name="found")
    unreported = _component(None, name="unreported")
    deleting = _component(handler.APP_NOT_FOUND, deleting=True, name="deleting")

    asyncio.run(
        handler._report_app_status_to_components(
            [not_found, found, unreported, deleting], handler.APP_FOUND, Mock()
        )
    )

    assert not_found.patched == [handler.APP_FOUND]
    assert found.patched == unreported.patched == deleting.patched == []
    assert posted_events == [("event", "not-found", handler.APP_FOUND)]


def test_no_event_for_component_deleted_before_its_status_update(posted_events):
    gone = _component(handler.APP_NOT_FOUND)

    async def patch_app_status(status):
        return None

    gone.patch_app_status = patch_app_status

    asyncio.run(handler._report_app_status_to_components([gone], handler.APP_FOUND, Mock()))

    assert posted_events == []


def test_on_delete_reports_app_not_found_to_components(monkeypatch, posted_events):
    found = _component(handler.APP_FOUND)

    async def fake_fetch_related_resources(name, namespace):
        return {"agents": [], "webviews": [], "tables": [], "tasks": [], "success": True}

    async def fake_attach(app, name, namespace, related=None):
        app.with_agents([found])
        app.with_webviews([])
        app.with_tables([])
        app.with_tasks([])
        return True

    monkeypatch.setattr(handler, "fetch_app_related_resources", fake_fetch_related_resources)
    monkeypatch.setattr(handler, "attach_app_related_resources", fake_attach)

    asyncio.run(handler.on_delete("app-a", namespace="test-ns", logger=Mock()))

    assert found.patched == [handler.APP_NOT_FOUND]
    assert posted_events == [("warn", "agent-1", handler.APP_NOT_FOUND)]


# ---------------------------------------------------------------------------
# KasprApp change handlers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "diff, expected",
    [
        ((("add", ("metadata", "annotations", "kaspr.io/rebalance"), None, "true"),), True),
        ((("remove", ("metadata", "annotations", "kaspr.io/rebalance"), "true", None),), True),
        ((("add", ("metadata", "annotations"), None, {"kaspr.io/rebalance": "true"}),), True),
        ((("change", ("spec", "replicas"), 1, 2),), False),
        ((("add", ("metadata", "annotations", "kaspr.io/auto-rebalance"), None, "false"),), False),
        ((("add", ("metadata", "annotations"), None, {"kaspr.io/rebalance": "true", "x": "y"}),), False),
    ],
)
def test_only_annotations_changed(diff, expected):
    assert handler._only_annotations_changed(diff, {"kaspr.io/rebalance"}) is expected


def test_update_handler_requests_reconciliation(requested):
    asyncio.run(
        handler.on_update_reconcile(
            name="app-a", namespace="test-ns", diff=(("change", ("spec", "replicas"), 1, 2),), logger=Mock()
        )
    )

    assert requested == [("test-ns", "app-a")]


def test_update_handler_ignores_rebalance_requests(requested):
    asyncio.run(
        handler.on_update_reconcile(
            name="app-a",
            namespace="test-ns",
            diff=(("add", ("metadata", "annotations", "kaspr.io/rebalance"), None, "true"),),
            logger=Mock(),
        )
    )

    assert requested == []


def test_manual_rebalance_clears_pending_rebalance(monkeypatch):
    fake_app = FakeApp()
    use_fake_app(monkeypatch, fake_app)
    patch = kopf.Patch()

    asyncio.run(
        handler.on_rebalance_requested(
            name="app-a",
            body={},
            spec={},
            namespace="test-ns",
            annotations={"kaspr.io/rebalance": "true"},
            patch=patch,
            logger=Mock(),
            status={"rebalanceRequired": True},
        )
    )

    assert patch.status["rebalanceRequired"] is False
    assert patch.metadata.annotations["kaspr.io/rebalance"] is None


# ---------------------------------------------------------------------------
# Component handlers
# ---------------------------------------------------------------------------


class FakeComponent:
    app_name = "app-a"
    cluster = "agent-1"
    config_map_name = "agent-1-agent"
    hash = "hash-1"

    def __init__(self):
        self.synced = 0

    def validate(self):
        pass

    async def synchronize(self):
        self.synced += 1


def run_component(monkeypatch, status, app_exists=True, component=None):
    component = component or FakeComponent()

    class FakeKasprApp:
        @staticmethod
        def default():
            return SimpleNamespace(fetch=AsyncMock(return_value={"kind": "KasprApp"} if app_exists else None))

    monkeypatch.setattr(component_handler, "KasprApp", FakeKasprApp)
    patch = kopf.Patch()
    asyncio.run(
        component_handler.reconcile_component(
            component,
            body={"metadata": {"name": "agent-1"}},
            status=status,
            patch=patch,
            namespace="test-ns",
            generation=1,
            reason="update",
            logger=Mock(),
        )
    )
    return dict(patch.get("status", {})), component


def test_component_reports_its_app_and_config_map(monkeypatch, posted_events):
    status, component = run_component(monkeypatch, status={})

    assert component.synced == 1
    assert status == {
        "app": {"name": "app-a", "status": "AppFound"},
        "configMap": "agent-1-agent",
        "hash": "hash-1",
    }
    assert posted_events == [("event", "agent-1", "AppFound")]


def test_unchanged_component_writes_no_status_and_posts_no_event(monkeypatch, posted_events):
    current = {
        "app": {"name": "app-a", "status": "AppFound"},
        "configMap": "agent-1-agent",
        "hash": "hash-1",
    }

    status, _ = run_component(monkeypatch, status=current)

    assert status == {}
    assert posted_events == []


def test_component_without_app_warns_on_every_reconciliation(monkeypatch, posted_events):
    current = {
        "app": {"name": "app-a", "status": "AppNotFound"},
        "configMap": "agent-1-agent",
        "hash": "hash-1",
    }

    status, _ = run_component(monkeypatch, status=current, app_exists=False)

    assert status == {}
    assert posted_events == [("warn", "agent-1", "AppNotFound")]


def test_component_without_app_label_fails_permanently(monkeypatch, posted_events):
    component = FakeComponent()

    def validate():
        raise kopf.PermanentError("Missing required label: kaspr.io/app")

    component.validate = validate

    with pytest.raises(kopf.PermanentError):
        run_component(monkeypatch, status={}, component=component)
    assert component.synced == 0


# ---------------------------------------------------------------------------
# KasprApp resource
# ---------------------------------------------------------------------------


def test_statefulset_watch_fields_include_hash_annotation():
    app = make_app()
    desired = app.stateful_set
    stale = live_copy(desired)
    stale.metadata.annotations = {app.RESOURCE_HASH_ANNOTATION: "stale"}

    assert app.prepare_statefulset_watch_fields(desired)["metadata"] == {
        "annotations": {app.RESOURCE_HASH_ANNOTATION: desired.metadata.annotations[app.RESOURCE_HASH_ANNOTATION]}
    }
    assert app.prepare_statefulset_watch_fields(stale) != app.prepare_statefulset_watch_fields(desired)


def test_statefulset_hash_annotation_patch():
    app = make_app()
    desired_hash = app.stateful_set.metadata.annotations[app.RESOURCE_HASH_ANNOTATION]

    annotated = live_copy(app.stateful_set)
    assert app.prepare_statefulset_hash_annotation_patch(annotated) == [
        {"op": "add", "path": "/metadata/annotations/kaspr.io~1resource-hash", "value": desired_hash}
    ]

    bare = live_copy(app.stateful_set)
    bare.metadata.annotations = None
    assert app.prepare_statefulset_hash_annotation_patch(bare) == [
        {"op": "add", "path": "/metadata/annotations", "value": {}},
        {"op": "add", "path": "/metadata/annotations/kaspr.io~1resource-hash", "value": desired_hash},
    ]


def _sync_stateful_set(app, live):
    patches = []

    async def fetch_stateful_set(*args, **kwargs):
        return live

    async def patch_stateful_set(api, name, namespace, stateful_set):
        patches.append(stateful_set)

    app.fetch_stateful_set = fetch_stateful_set
    app.patch_stateful_set = patch_stateful_set
    app.sensor = Mock()
    asyncio.run(app.sync_stateful_set())
    return patches


def test_sync_stateful_set_skips_patch_when_up_to_date():
    app = make_app()

    assert _sync_stateful_set(app, live_copy(app.stateful_set)) == []


def test_sync_stateful_set_patches_rendering_changes_outside_watch_fields():
    """e.g. a component's definition changed, which only changes its hash env var."""
    app = make_app()
    live = live_copy(app.stateful_set)
    live.metadata.annotations = {app.RESOURCE_HASH_ANNOTATION: "rendered-by-older-spec"}

    patches = _sync_stateful_set(app, live)

    assert len(patches) == 1
    ops = {op["path"]: op for op in patches[0]}
    assert ops["/spec/template"]["value"] is app.stateful_set.spec.template
    assert ops["/metadata/annotations/kaspr.io~1resource-hash"]["value"] == (
        app.stateful_set.metadata.annotations[app.RESOURCE_HASH_ANNOTATION]
    )


def test_statefulset_fingerprint_ignores_replica_count_owned_by_hpa():
    app = make_app()
    desired = app.prepare_statefulset_fingerprint(app.stateful_set)

    assert app.prepare_statefulset_fingerprint(live_copy(app.stateful_set, replicas=3)) == desired
    # Scaling up from zero still needs the operator.
    assert app.prepare_statefulset_fingerprint(live_copy(app.stateful_set, replicas=0)) != desired


def test_statefulset_fingerprint_of_stopped_app_requires_zero_replicas():
    app = make_app(replicas=0)
    desired = app.prepare_statefulset_fingerprint(app.stateful_set)

    assert app.prepare_statefulset_fingerprint(live_copy(app.stateful_set, replicas=0)) == desired
    assert app.prepare_statefulset_fingerprint(live_copy(app.stateful_set, replicas=1)) != desired


def _stateful_set_with_status(
    app, generation, observed_generation, current=1, updated=1, current_revision="rev-1", update_revision="rev-1"
):
    live = live_copy(app.stateful_set, generation=generation)
    live.status = V1StatefulSetStatus(
        replicas=1,
        available_replicas=1,
        current_replicas=current,
        updated_replicas=updated,
        observed_generation=observed_generation,
        current_revision=current_revision,
        update_revision=update_revision,
    )
    return live


@pytest.mark.parametrize(
    "status_kwargs, expected",
    [
        ({"generation": 2, "observed_generation": 2}, False),
        # The controller has not seen the new spec yet.
        ({"generation": 3, "observed_generation": 2}, True),
        # As observed while the first old pod is replaced: no replica counts at all.
        (
            {"generation": 3, "observed_generation": 3, "current": None, "updated": None, "update_revision": "rev-2"},
            True,
        ),
        ({"generation": 3, "observed_generation": 3, "current": 1, "updated": 0, "update_revision": "rev-2"}, True),
        # Done: the update revision became the current one.
        ({"generation": 3, "observed_generation": 3, "current_revision": "rev-2", "update_revision": "rev-2"}, False),
    ],
)
def test_rollout_in_progress_until_all_pods_run_the_new_revision(operator_settings, status_kwargs, expected):
    operator_settings.client_status_check_enabled = False
    app = make_app()
    live = _stateful_set_with_status(app, **status_kwargs)

    async def fetch_stateful_set(*args, **kwargs):
        return live

    app.fetch_stateful_set = fetch_stateful_set
    status = asyncio.run(app.fetch_app_status())

    assert status["rolloutInProgress"] is expected
    assert app.observed_stateful_set is live


def test_member_statuses_reuse_pods_until_statefulset_changes():
    app = make_app()
    created = datetime(2026, 10, 15, tzinfo=timezone.utc)
    pods = V1PodList(
        items=[V1Pod(metadata=V1ObjectMeta(name="test-app-app-0", uid="uid-0", creation_timestamp=created))]
    )
    list_calls = []

    async def list_pods(*args, **kwargs):
        list_calls.append(args)
        return pods

    app.list_pods = list_pods
    app.web_client = SimpleNamespace(get_status=AsyncMock(return_value={"leader": True}))
    cache = PodMetadataCache()

    first = asyncio.run(app.fetch_all_member_statuses(1, pod_cache=cache, stateful_set_version="10"))
    second = asyncio.run(app.fetch_all_member_statuses(1, pod_cache=cache, stateful_set_version="10"))
    asyncio.run(app.fetch_all_member_statuses(1, pod_cache=cache, stateful_set_version="11"))

    assert len(list_calls) == 2
    assert first[0]["podUID"] == second[0]["podUID"] == "uid-0"
    assert cache.listed_pods is pods


def test_member_statuses_without_cache_always_list_pods():
    app = make_app()
    list_pods = AsyncMock(return_value=V1PodList(items=[]))
    app.list_pods = list_pods
    app.web_client = SimpleNamespace(get_status=AsyncMock(return_value={"leader": True}))

    asyncio.run(app.fetch_all_member_statuses(1))
    asyncio.run(app.fetch_all_member_statuses(1))

    assert list_pods.await_count == 2


def test_request_rebalance_uses_given_status():
    app = make_app()
    app.fetch_app_status = AsyncMock()
    app.web_client = SimpleNamespace(rebalance=AsyncMock())
    status = healthy_status()

    requested, _ = asyncio.run(app.request_rebalance(status=status))

    assert requested is True
    app.fetch_app_status.assert_not_awaited()
    app.web_client.rebalance.assert_awaited_once()


def test_sync_component_config_maps_lists_config_maps_once():
    app = make_app()
    synced = []

    def component(name):
        stub = SimpleNamespace(config_map_name=f"{name}-agent")

        async def sync_config_map(actual):
            synced.append((name, actual))

        stub.sync_config_map = sync_config_map
        return stub

    existing = V1ConfigMap(metadata=V1ObjectMeta(name="a-agent"))
    app.with_agents([component("a"), component("b")])
    app.with_webviews([])
    app.with_tables([])
    app.with_tasks([])
    app.list_config_maps = AsyncMock(return_value=[existing])

    asyncio.run(app.sync_component_config_maps())

    app.list_config_maps.assert_awaited_once_with(
        app.core_v1_api, "test-ns", label_selector="kaspr.io/app=test-app"
    )
    assert synced == [("a", existing), ("b", None)]


def test_sync_component_config_maps_without_components_reads_nothing():
    app = make_app()
    app.with_agents([])
    app.with_webviews([])
    app.with_tables([])
    app.with_tasks([])
    app.list_config_maps = AsyncMock()

    asyncio.run(app.sync_component_config_maps())

    app.list_config_maps.assert_not_awaited()


# ---------------------------------------------------------------------------
# Component resources
# ---------------------------------------------------------------------------


class _Component(BaseAppComponent):
    KIND = "KasprAgent"
    COMPONENT_TYPE = "KasprAgent"
    PLURAL_NAME = "kaspragents"
    kaspr_resource = SimpleNamespace(component_name=lambda name: name)

    def __init__(self):
        super().__init__(
            name="agent-1",
            kind=self.KIND,
            namespace="test-ns",
            component_type=self.COMPONENT_TYPE,
            labels={self.KASPR_APP_NAME_LABEL: "app-a"},
        )
        self.config_map_name = "agent-1-agent"
        self.file_name = "agent-1.yaml"
        self.file_data = "name: agent-1\n"
        self.app_components = None
        self.sensor = Mock()


def test_sync_config_map_with_known_actual_skips_read():
    component = _Component()
    component.fetch_config_map = AsyncMock()
    component.patch_config_map = AsyncMock()

    asyncio.run(component.sync_config_map(actual=copy.deepcopy(component.config_map)))

    component.fetch_config_map.assert_not_awaited()
    component.patch_config_map.assert_not_awaited()


def test_sync_config_map_creates_missing_config_map_owned_by_component(monkeypatch):
    component = _Component()
    component.owner = {
        "apiVersion": "kaspr.io/v1alpha1",
        "kind": "KasprAgent",
        "metadata": {"name": "agent-1", "namespace": "test-ns", "uid": "uid-1", "labels": {}},
    }
    component.fetch_config_map = AsyncMock()
    component.create_config_map = AsyncMock()

    asyncio.run(component.sync_config_map(actual=None))

    component.fetch_config_map.assert_not_awaited()
    component.create_config_map.assert_awaited_once()
    owner_refs = component.config_map.metadata.owner_references
    assert [(ref.kind, ref.name, ref.uid) for ref in owner_refs] == [("KasprAgent", "agent-1", "uid-1")]


def test_component_hash_does_not_depend_on_adoption():
    """The KasprApp puts component hashes in its pods; adopting must not change them."""
    owner = {
        "apiVersion": "kaspr.io/v1alpha1",
        "kind": "KasprAgent",
        "metadata": {"name": "agent-1", "namespace": "test-ns", "uid": "uid-1", "labels": {}},
    }
    expected = _Component().hash

    adopted = _Component()
    adopted.owner = owner
    adopted.unite()

    assert adopted.config_map.metadata.owner_references
    assert adopted.hash == expected


def _custom_objects_api(main_result=None, status_result=None, error=None):
    api = SimpleNamespace(
        patch_namespaced_custom_object=AsyncMock(return_value=main_result, side_effect=error),
        patch_namespaced_custom_object_status=AsyncMock(return_value=status_result),
    )
    return api


def _patch_app_status(api):
    component = _Component()
    component.__dict__["custom_objects_api"] = api
    return asyncio.run(component.patch_app_status("AppFound"))


EXPECTED_PATCH = dict(
    group="kaspr.io",
    version="v1alpha1",
    namespace="test-ns",
    plural="kaspragents",
    name="agent-1",
    body={"status": {"app": {"name": "app-a", "status": "AppFound"}}},
    _content_type="application/merge-patch+json",
)


def test_patch_app_status_without_status_subresource_patches_the_object():
    """Component CRDs have no status subresource: their status is part of the object."""
    patched = {"status": {"app": {"name": "app-a", "status": "AppFound"}, "hash": "h"}}
    api = _custom_objects_api(main_result=patched)

    assert _patch_app_status(api) is patched
    api.patch_namespaced_custom_object.assert_awaited_once_with(**EXPECTED_PATCH)
    api.patch_namespaced_custom_object_status.assert_not_awaited()


def test_patch_app_status_with_status_subresource_patches_the_subresource():
    # With a status subresource, the API server drops status changes made to the object.
    api = _custom_objects_api(main_result={"status": {"app": {"name": "app-a", "status": "AppNotFound"}}}, status_result={"ok": True})

    assert _patch_app_status(api) == {"ok": True}
    api.patch_namespaced_custom_object_status.assert_awaited_once_with(**EXPECTED_PATCH)


def test_patch_app_status_of_deleted_component_returns_none():
    from kubernetes_asyncio.client import ApiException

    api = _custom_objects_api(error=ApiException(status=404, reason="Not Found"))

    assert _patch_app_status(api) is None
