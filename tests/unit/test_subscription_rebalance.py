"""Unit tests for rebalancing a KasprApp's consumer group after its subscriptions change."""

import asyncio
import copy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import kopf
import pytest

from kaspr.handlers import kasprapp as handler
from kaspr.resources import KasprApp
from kaspr.resources.appcomponent import BaseAppComponent
from kaspr.types.schemas.kasprapp_spec import KasprAppSpecSchema
from kaspr.types.settings import Settings
from kaspr.utils.subscriptions import (
    changelog_topic,
    check_assignment,
    subscribed_topics,
    subscription_change,
)


APP_SPEC = {
    "replicas": 2,
    "bootstrapServers": "kafka:9092",
    "authentication": {"type": "plain"},
    "storage": {"type": "persistent-claim", "class": "standard", "size": "1Gi", "deleteClaim": True},
}


@pytest.fixture(autouse=True)
def operator_settings(monkeypatch):
    settings = Settings()
    monkeypatch.setattr(KasprApp, "conf", settings, raising=False)
    monkeypatch.setattr(KasprApp, "sensor", None, raising=False)
    monkeypatch.setattr(BaseAppComponent, "sensor", None, raising=False)
    return settings


@pytest.fixture(autouse=True)
def clean_handler_state():
    handler.app_states.clear()
    handler.hung_member_tracking.clear()
    yield
    handler.app_states.clear()
    handler.hung_member_tracking.clear()


@pytest.fixture
def warnings(monkeypatch):
    posted = []
    monkeypatch.setattr(kopf, "warn", lambda obj, reason, message: posted.append((obj, reason, message)))
    return posted


def ago(seconds: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


def linked(*agent_topics, tables=()):
    return {
        "agents": [
            {"name": f"agent-{index}", "hash": f"h{index}", "topicName": topics}
            for index, topics in enumerate(agent_topics)
        ],
        "webviews": [],
        "tables": [{"name": f"table-{t}", "hash": "t", "tableName": t} for t in tables],
        "tasks": [],
    }


def member(member_id, actives=None, standbys=None, rebalancing=False, leader=False):
    return {
        "id": member_id,
        "leader": leader,
        "rebalancing": rebalancing,
        "recovering": False,
        "assignment": {"actives": actives or {}, "standbys": standbys or {}},
    }


def app_status(members, **overrides):
    status = {
        "kasprVersion": "0.11.28",
        "availableMembers": len(members),
        "desiredMembers": len(members),
        "rolloutInProgress": False,
        "members": members,
    }
    status.update(overrides)
    return status


class FakeApp:
    """The parts of KasprApp used by update_status."""

    stateful_set_name = "test-app-app"

    def __init__(self, actual_status, accepted=True):
        self.annotations = {}
        self.python_packages = None
        self.static_group_membership_enabled = True
        self.replicas = 2
        self.config = SimpleNamespace(broker_session_timeout=None)
        self.conf = SimpleNamespace(
            hung_member_detection_enabled=True,
            hung_rebalancing_threshold_seconds=300,
            auto_rebalance_enabled=True,
            client_status_check_enabled=True,
            rebalance_verify_delay_seconds=15.0,
            rebalance_max_attempts=3,
            rebalance_verify_timeout_seconds=600.0,
        )
        self.actual_status = actual_status
        self.accepted = accepted
        self.rebalance_calls = []
        self.terminate_calls = []
        self.observed_stateful_set = None

    async def fetch_app_status(self, **kwargs):
        self.observed_stateful_set = SimpleNamespace(metadata=SimpleNamespace(resource_version="1"))
        return copy.deepcopy(self.actual_status)

    def prepare_statefulset_fingerprint(self, stateful_set):
        return "desired"

    async def terminate_member(self, member_id):
        self.terminate_calls.append(member_id)
        return True

    async def request_rebalance(self, status=None):
        self.rebalance_calls.append(status)
        if self.accepted:
            return True, "Rebalance requested on 2 of 2 members"
        return False, "No member accepted the rebalance request"


def use_fake_app(monkeypatch, fake_app):
    monkeypatch.setattr(handler.KasprAppSpecSchema, "load", lambda self, value: object())
    monkeypatch.setattr(
        handler.KasprApp, "from_spec", classmethod(lambda cls, *args, **kwargs: fake_app)
    )


def refresh(status, state, related_resources=None):
    """One status update, returning the status as it is afterwards and what changed."""
    patch = SimpleNamespace(status={})
    asyncio.run(
        handler.update_status(
            name="orders",
            spec={},
            meta={"generation": 1, "uid": "uid-1"},
            status=status,
            patch=patch,
            namespace="test-ns",
            annotations={},
            logger=Mock(),
            related_resources=related_resources,
            state=state,
        )
    )
    after = {**status, **patch.status}
    return {k: v for k, v in after.items() if v is not None}, patch.status


def related(*agent_topics, tables=()):
    return {
        "agents": [
            {
                "metadata": {"name": f"agent-{index}"},
                "spec": {"input": {"topic": {"name": topics}}},
                "status": {"hash": f"h{index}"},
            }
            for index, topics in enumerate(agent_topics)
        ],
        "webviews": [],
        "tables": [
            {"metadata": {"name": f"table-{t}"}, "spec": {"name": t}, "status": {"hash": "t"}}
            for t in tables
        ],
        "tasks": [],
        "success": True,
        "hashes": {"agents": {f"agent-{i}": f"n{i}" for i in range(len(agent_topics))}},
    }


# ---------------------------------------------------------------------------
# What an app subscribes to
# ---------------------------------------------------------------------------


def test_subscribed_topics_are_agent_topics_and_table_changelogs():
    resources = linked(" orders , returns", "payments", tables=["totals"])
    resources["agents"].append({"name": "by-pattern", "topicPattern": "audit-.*"})

    assert subscribed_topics(resources, "shop") == {
        "orders",
        "returns",
        "payments",
        "shop-app-totals-changelog",
    }
    assert changelog_topic("shop", "totals") == "shop-app-totals-changelog"


def test_subscription_change_names_added_and_removed_topics():
    change = subscription_change(linked("orders,returns", tables=["a"]), linked("orders,refunds", tables=["b"]), "shop")

    assert change.added == {"refunds", "shop-app-b-changelog"}
    assert change.removed == {"returns", "shop-app-a-changelog"}
    assert not change.patterns_changed
    assert not subscription_change(linked("orders"), linked("orders"), "shop")


def test_check_assignment_finds_unassigned_and_stale_topics():
    members = [
        member(0, actives={"orders": [0], "leader": [0]}, standbys={"returns": [1]}),
        member(1, actives={"orders": [1]}, standbys={"refunds": [0]}),
    ]

    check = check_assignment(members, {"orders", "refunds"}, ["returns"])

    # A topic held only as a standby is not consumed.
    assert check.unassigned == ["refunds"]
    assert check.stale == ["returns"]
    assert check.reported and check.settled and not check.satisfied


def test_check_assignment_needs_settled_reported_assignments():
    rebalancing = check_assignment([member(0, actives={"orders": [0]}, rebalancing=True)], {"orders"})
    unreported = check_assignment([{"id": 0, "rebalancing": False}], {"orders"})
    satisfied = check_assignment([member(0, actives={"orders": [0, 1]})], {"orders"}, ["orders"])

    assert not rebalancing.settled and not rebalancing.satisfied
    assert not unreported.reported
    # A topic the change removed and added back again is expected, not stale.
    assert satisfied.satisfied


# ---------------------------------------------------------------------------
# Detecting a change
# ---------------------------------------------------------------------------


def test_a_change_records_the_topics_it_removes(monkeypatch):
    fake_app = FakeApp(app_status([member(0), member(1)], rolloutInProgress=True))
    use_fake_app(monkeypatch, fake_app)
    status = {"linkedResources": linked("orders,returns"), "rebalanceRequired": False}

    after, _ = refresh(status, handler.AppRuntimeState(), related_resources=related("orders,refunds"))

    assert after["rebalanceRequired"] is True
    assert after["rebalance"]["removedTopics"] == ["returns"]
    assert after["rebalance"]["attempts"] == 0
    assert fake_app.rebalance_calls == []


def test_a_new_change_keeps_topics_an_earlier_one_removed_unless_added_back(monkeypatch):
    fake_app = FakeApp(app_status([member(0), member(1)], rolloutInProgress=True))
    use_fake_app(monkeypatch, fake_app)
    status = {
        "linkedResources": linked("orders"),
        "rebalanceRequired": True,
        "rebalance": {"removedTopics": ["returns", "refunds"], "attempts": 2},
    }

    after, _ = refresh(status, handler.AppRuntimeState(), related_resources=related("orders,refunds"))

    assert after["rebalance"]["removedTopics"] == ["returns"]
    assert after["rebalance"]["attempts"] == 0


def test_an_app_tracked_without_components_rebalances_for_its_first_agent(monkeypatch):
    fake_app = FakeApp(app_status([member(0), member(1)], rolloutInProgress=True))
    use_fake_app(monkeypatch, fake_app)
    status = {"linkedResources": {"agents": [], "webviews": [], "tables": [], "tasks": []}}

    after, _ = refresh(status, handler.AppRuntimeState(), related_resources=related("orders"))

    # Before, an app whose tracked components were all empty was "first tracked" again.
    assert after["rebalanceRequired"] is True


def test_an_app_never_tracked_starts_tracking_without_a_rebalance(monkeypatch):
    fake_app = FakeApp(app_status([member(0), member(1)]))
    use_fake_app(monkeypatch, fake_app)

    after, _ = refresh({}, handler.AppRuntimeState(), related_resources=related("orders"))

    assert after["linkedResources"]["agents"][0]["topicName"] == "orders"
    assert after["rebalanceRequired"] is False
    assert fake_app.rebalance_calls == []


# ---------------------------------------------------------------------------
# Requesting and checking the rebalance
# ---------------------------------------------------------------------------


def pending_status(attempts=0, requested=None, last=None, removed=(), topics=("orders,refunds",)):
    return {
        "linkedResources": linked(*topics),
        "rebalanceRequired": True,
        "rebalance": {
            "reason": "SubscriptionChanged",
            "removedTopics": list(removed),
            "attempts": attempts,
            "requestedAt": requested,
            "lastRequestedAt": last if last is not None else requested,
        },
    }


STALE = [member(0, actives={"orders": [0]}), member(1, actives={"orders": [1]})]
REBALANCED = [member(0, actives={"orders": [0], "refunds": [0]}), member(1, actives={"orders": [1], "refunds": [1]})]


def test_the_rebalance_is_requested_once_the_rollout_is_over_and_stays_pending(monkeypatch):
    fake_app = FakeApp(app_status(STALE))
    use_fake_app(monkeypatch, fake_app)

    after, _ = refresh(pending_status(), handler.AppRuntimeState())

    assert len(fake_app.rebalance_calls) == 1
    assert after["rebalanceRequired"] is True
    assert after["rebalance"]["attempts"] == 1
    assert after["rebalance"]["requestedAt"] == after["rebalance"]["lastRequestedAt"]


def test_members_that_rebalanced_on_their_own_need_no_request(monkeypatch):
    # A member handed back a topic it stopped consuming leaves its group and rejoins
    # (Kaspr's coordinator patch), so the group may match the change by the time the
    # rollout is over.
    fake_app = FakeApp(app_status(STALE))
    use_fake_app(monkeypatch, fake_app)

    _, changes = refresh(pending_status(removed=["returns"], topics=("orders",)), handler.AppRuntimeState())

    assert fake_app.rebalance_calls == []
    assert changes["rebalanceRequired"] is False
    assert changes["rebalance"] is None


def test_an_app_subscribing_by_pattern_always_gets_a_request(monkeypatch):
    fake_app = FakeApp(app_status(STALE))
    use_fake_app(monkeypatch, fake_app)
    status = pending_status(topics=("orders",))
    status["linkedResources"]["agents"].append({"name": "audit", "hash": "p", "topicPattern": "audit-.*"})

    after, _ = refresh(status, handler.AppRuntimeState())

    assert len(fake_app.rebalance_calls) == 1
    assert after["rebalance"]["attempts"] == 1


def test_a_group_rebalancing_after_the_rollout_is_given_time_to_settle(monkeypatch):
    members = [member(0, actives={"orders": [0], "refunds": [0]}, rebalancing=True), member(1)]
    fake_app = FakeApp(app_status(members))
    use_fake_app(monkeypatch, fake_app)
    state = handler.AppRuntimeState()

    # It may settle on an assignment that matches already.
    refresh(pending_status(), state)
    assert fake_app.rebalance_calls == []

    # Unsettled for as long as a requested rebalance is given: requested anyway.
    state.rebalance_ready_since -= 20
    refresh(pending_status(), state)
    assert len(fake_app.rebalance_calls) == 1


def test_the_settling_time_starts_over_when_members_are_not_ready(monkeypatch):
    rebalancing = [member(0, rebalancing=True), member(1, rebalancing=True)]
    fake_app = FakeApp(app_status(rebalancing))
    use_fake_app(monkeypatch, fake_app)
    state = handler.AppRuntimeState()

    refresh(pending_status(), state)
    state.rebalance_ready_since -= 20
    fake_app.actual_status = app_status(rebalancing, availableMembers=1)
    refresh(pending_status(), state)
    assert state.rebalance_ready_since is None

    fake_app.actual_status = app_status(rebalancing)
    refresh(pending_status(), state)
    assert fake_app.rebalance_calls == []


def test_nothing_is_checked_before_the_rebalance_had_time(monkeypatch):
    fake_app = FakeApp(app_status(STALE))
    use_fake_app(monkeypatch, fake_app)

    after, changes = refresh(pending_status(attempts=1, requested=ago(5)), handler.AppRuntimeState())

    assert fake_app.rebalance_calls == []
    assert "rebalance" not in changes and after["rebalanceRequired"] is True


def test_a_rebalance_that_took_clears_the_pending_rebalance(monkeypatch):
    fake_app = FakeApp(app_status(REBALANCED))
    use_fake_app(monkeypatch, fake_app)

    after, changes = refresh(pending_status(attempts=1, requested=ago(20)), handler.AppRuntimeState())

    assert changes["rebalanceRequired"] is False
    assert changes["rebalance"] is None
    assert fake_app.rebalance_calls == []


def test_a_rebalance_that_did_not_take_is_requested_again(monkeypatch):
    fake_app = FakeApp(app_status(STALE))
    use_fake_app(monkeypatch, fake_app)
    first = ago(40)

    after, _ = refresh(pending_status(attempts=1, requested=first, last=ago(20)), handler.AppRuntimeState())

    assert len(fake_app.rebalance_calls) == 1
    assert after["rebalance"]["attempts"] == 2
    assert after["rebalance"]["requestedAt"] == first
    assert after["rebalance"]["unassignedTopics"] == ["refunds"]
    assert after["rebalanceRequired"] is True


def test_a_removed_topic_still_assigned_is_requested_again(monkeypatch):
    members = [member(0, actives={"orders": [0], "returns": [0]}), member(1, actives={"orders": [1]})]
    fake_app = FakeApp(app_status(members))
    use_fake_app(monkeypatch, fake_app)

    after, _ = refresh(
        pending_status(attempts=1, requested=ago(20), removed=["returns"], topics=("orders",)),
        handler.AppRuntimeState(),
    )

    assert len(fake_app.rebalance_calls) == 1
    assert after["rebalance"]["staleTopics"] == ["returns"]


def test_members_still_rebalancing_are_waited_for(monkeypatch):
    members = [member(0, rebalancing=True), member(1, rebalancing=True)]
    fake_app = FakeApp(app_status(members))
    use_fake_app(monkeypatch, fake_app)

    after, _ = refresh(pending_status(attempts=1, requested=ago(60)), handler.AppRuntimeState())

    assert fake_app.rebalance_calls == []
    assert after["rebalanceRequired"] is True


def test_a_member_that_did_not_report_is_waited_for(monkeypatch):
    fake_app = FakeApp(app_status(REBALANCED[:1], desiredMembers=2, availableMembers=2))
    use_fake_app(monkeypatch, fake_app)

    after, _ = refresh(pending_status(attempts=1, requested=ago(20)), handler.AppRuntimeState())

    assert fake_app.rebalance_calls == []
    assert after["rebalanceRequired"] is True


def test_requests_stop_at_the_maximum_and_the_gaps_are_reported(monkeypatch):
    fake_app = FakeApp(app_status(STALE))
    use_fake_app(monkeypatch, fake_app)

    after, _ = refresh(pending_status(attempts=3, requested=ago(120), last=ago(60)), handler.AppRuntimeState())

    assert fake_app.rebalance_calls == []
    assert after["rebalanceRequired"] is True
    assert after["rebalance"]["unassignedTopics"] == ["refunds"]
    assert "no member is assigned refunds" in after["rebalance"]["message"]


def test_a_rebalance_that_never_takes_is_given_up_with_a_warning(monkeypatch, warnings):
    fake_app = FakeApp(app_status(STALE))
    use_fake_app(monkeypatch, fake_app)

    after, _ = refresh(pending_status(attempts=3, requested=ago(700), last=ago(60)), handler.AppRuntimeState())

    assert after["rebalanceRequired"] is False
    assert after["rebalance"]["unassignedTopics"] == ["refunds"]
    assert "Gave up rebalancing after 3 requests" in after["rebalance"]["message"]
    assert [(obj["metadata"]["name"], reason) for obj, reason, _ in warnings] == [
        ("orders", "RebalanceNotEffective")
    ]


def test_members_that_report_no_assignment_are_trusted_with_the_request(monkeypatch):
    members = [{"id": 0, "leader": True, "rebalancing": False, "recovering": False}, {"id": 1, "rebalancing": False}]
    fake_app = FakeApp(app_status(members))
    use_fake_app(monkeypatch, fake_app)

    _, changes = refresh(pending_status(attempts=1, requested=ago(20)), handler.AppRuntimeState())

    assert changes["rebalanceRequired"] is False
    assert fake_app.rebalance_calls == []


def test_a_request_no_member_accepts_is_tried_again(monkeypatch):
    fake_app = FakeApp(app_status(STALE), accepted=False)
    use_fake_app(monkeypatch, fake_app)

    after, changes = refresh(pending_status(), handler.AppRuntimeState())

    assert len(fake_app.rebalance_calls) == 1
    assert "rebalance" not in changes
    assert after["rebalance"]["attempts"] == 0


def test_an_app_scaled_to_zero_keeps_its_rebalance_pending_without_requests(monkeypatch):
    fake_app = FakeApp(app_status([], availableMembers=0, desiredMembers=0))
    use_fake_app(monkeypatch, fake_app)
    state = handler.AppRuntimeState()

    after, _ = refresh(pending_status(), state)

    assert fake_app.rebalance_calls == []
    assert after["rebalanceRequired"] is True
    assert state.last_rebalance_deferral == "scaled to zero"


def test_status_refreshes_more_often_while_a_rebalance_is_pending():
    conf = SimpleNamespace(status_update_interval_seconds=30.0, rebalance_check_interval_seconds=5.0)

    assert handler._status_refresh_interval({"replicas": 2}, {"rebalanceRequired": True}, conf) == 5.0
    assert handler._status_refresh_interval({"replicas": 0}, {"rebalanceRequired": True}, conf) == 30.0
    assert handler._status_refresh_interval({"replicas": 2}, {"rebalanceRequired": False}, conf) == 30.0


def test_a_manual_rebalance_settles_a_pending_one(monkeypatch):
    fake_app = FakeApp(app_status(STALE))
    use_fake_app(monkeypatch, fake_app)
    patch = kopf.Patch()

    asyncio.run(
        handler.on_rebalance_requested(
            name="orders",
            body={},
            spec={},
            namespace="test-ns",
            annotations={"kaspr.io/rebalance": "true"},
            patch=patch,
            logger=Mock(),
            status={"rebalanceRequired": True, "rebalance": {"attempts": 1}},
        )
    )

    assert patch.status["rebalanceRequired"] is False
    assert patch.status["rebalance"] is None


# ---------------------------------------------------------------------------
# Members wedged by a stale assignment
# ---------------------------------------------------------------------------


def wedged_status(seconds_rebalancing, rebalance=None):
    members = [
        {"id": i, "leader": False, "rebalancing": True, "recovering": False, "lastTransitionTime": ago(seconds_rebalancing)}
        for i in (0, 1)
    ]
    status = {
        "members": members,
        "conditions": [{"type": "Progressing", "status": "False"}],
    }
    if rebalance is not None:
        status.update(rebalanceRequired=True, rebalance=rebalance)
    return status


def detect(app, status, times=3):
    found = []
    for _ in range(times):
        found = asyncio.run(handler._detect_hung_members(status, app, "orders", "test-ns", Mock()))
    return found


def test_members_still_rebalancing_after_a_requested_rebalance_are_hung_past_the_session_timeout():
    app = FakeApp(app_status(STALE))

    # The broker drops a member that stopped heartbeating after the session timeout
    # (120 s by default); restarted after that, the member joins afresh.
    assert detect(app, wedged_status(160, rebalance={"attempts": 1})) == [0, 1]
    handler.hung_member_tracking.clear()
    assert detect(app, wedged_status(100, rebalance={"attempts": 1})) == []


def test_the_shorter_threshold_applies_only_once_a_rebalance_was_requested():
    app = FakeApp(app_status(STALE))

    assert detect(app, wedged_status(160)) == []
    assert detect(app, wedged_status(160, rebalance={"attempts": 0})) == []


def test_the_session_timeout_comes_from_the_app_config():
    app = FakeApp(app_status(STALE))
    app.config = SimpleNamespace(broker_session_timeout=200)

    assert detect(app, wedged_status(160, rebalance={"attempts": 1})) == []


# ---------------------------------------------------------------------------
# KasprApp.request_rebalance
# ---------------------------------------------------------------------------


def make_app():
    spec = KasprAppSpecSchema().load(APP_SPEC)
    app = KasprApp.from_spec("orders", "KasprApp", "test-ns", spec, {})
    app.logger = Mock()
    return app


def test_request_rebalance_asks_every_member():
    app = make_app()
    app.web_client = SimpleNamespace(rebalance=AsyncMock())

    requested, reason = asyncio.run(app.request_rebalance(status=app_status([member(0), member(1)])))

    assert requested is True
    assert sorted(call.args[0] for call in app.web_client.rebalance.await_args_list) == [
        app.prepare_member_url(0),
        app.prepare_member_url(1),
    ]
    assert reason == "Rebalance requested on 2 of 2 members"


def test_request_rebalance_needs_no_leader_and_tolerates_a_member_that_fails():
    app = make_app()

    async def rebalance(url):
        if url == app.prepare_member_url(1):
            raise RuntimeError("connection refused")

    app.web_client = SimpleNamespace(rebalance=AsyncMock(side_effect=rebalance))

    # A member left without a working assignment reports no leader.
    requested, reason = asyncio.run(
        app.request_rebalance(status=app_status([member(0, rebalancing=True), member(1, rebalancing=True)]))
    )

    assert requested is True
    assert reason == "Rebalance requested on 1 of 2 members"


def test_request_rebalance_fails_when_no_member_accepts_or_none_runs():
    app = make_app()
    app.web_client = SimpleNamespace(rebalance=AsyncMock(side_effect=RuntimeError("down")))

    assert asyncio.run(app.request_rebalance(status=app_status([member(0)])))[0] is False
    assert asyncio.run(
        app.request_rebalance(status=app_status([], availableMembers=0, desiredMembers=0))
    ) == (False, "App is scaled to zero")
