# Rebalancing after a subscription change

## Why a rebalance is needed

Kaspr apps use static consumer group membership (KIP-345): each member's `group.instance.id` is
its pod name, so a restarted pod rejoins its group within the session timeout without a
rebalance, and the broker hands it the partitions it held before. That is what makes restarts
cheap. It also means a rollout that changes what an app consumes is not picked up by itself:

| Change | Without a rebalance |
|---|---|
| An agent subscribes to another topic, an agent or table is added | The new topic is assigned to nobody and is never read |
| An agent stops subscribing to a topic, an agent or table is removed | Members get back partitions of a topic they no longer subscribe to. aiokafka refuses such an assignment (`AssertionError: Received an assignment for unsubscribed topic`): the member stops coordinating and heartbeating, and reports itself rebalancing until it is restarted after the broker has dropped it |

Apps that disable static membership (`kaspr.io/disable-static-group-membership: "true"`)
rebalance on their own and are left alone.

## What the operator does

1. **Detects the change.** On every reconciliation the operator compares the app's agents and
   tables with `status.linkedResources`. A change to the topics agents subscribe to (by name or
   pattern) or to the tables (whose changelog topics members consume) sets
   `status.rebalanceRequired` and records the change in `status.rebalance`, including the topics
   it removed. The first time an app's resources are tracked, nothing is compared.
2. **Waits for the rollout.** Agent and table changes roll the app's pods. While the rollout is
   in progress, members are not ready, or the app is scaled to zero, the rebalance stays pending.
   Meanwhile the app's status is refreshed every `REBALANCE_CHECK_INTERVAL_SECONDS` (5 s) rather
   than every `STATUS_UPDATE_INTERVAL_SECONDS` (30 s).
3. **Requests the rebalance from every member.** `POST /signal/rebalance/` makes a member rejoin
   its group. A rejoin rebalances a stable group when it comes from the member the broker made the
   group's leader, or from a member whose metadata changed. A member's `leader` flag in its status
   is Kaspr's own (it owns the leader topic), not the broker's choice, so every member is asked.
4. **Checks that it took.** After `REBALANCE_VERIFY_DELAY_SECONDS` (15 s), once every member
   reports and none is rebalancing, the operator compares their reported assignments with the app's
   subscriptions: every topic its agents subscribe to by name, and every table's changelog
   (`<app>-app-<table>-changelog`), must be actively assigned to some member, and no removed topic
   may be assigned to any. If so, `rebalanceRequired` and `rebalance` are cleared.
5. **Requests again, then gives up.** A settled assignment that still misses topics is requested
   again, up to `REBALANCE_MAX_ATTEMPTS` (3) times. If the rebalance has not taken effect
   `REBALANCE_VERIFY_TIMEOUT_SECONDS` (600 s) after the first request, the operator stops, clears
   `rebalanceRequired`, keeps the findings in `status.rebalance`, and posts a
   `RebalanceNotEffective` warning event. A topic that does not exist is a common cause.
6. **Restarts wedged members sooner.** While a requested rebalance is pending, a member that is
   still rebalancing (and not recovering) past the group's session timeout plus 30 s is treated as
   hung and restarted, instead of after `HUNG_REBALANCING_THRESHOLD_SECONDS` (300 s). By then the
   broker has dropped it, so it joins the group afresh. The session timeout is the app's
   `config.brokerSessionTimeout`, or Kaspr's default of 120 s.

Members of Kaspr versions that do not report their assignment on `/status/` cannot be checked;
for them the first accepted request is taken as success.

## Status

```yaml
status:
  rebalanceRequired: true
  rebalance:
    reason: SubscriptionChanged
    removedTopics: [returns]
    attempts: 1
    requestedAt: "2026-10-20T12:29:37.088000+00:00"
    lastRequestedAt: "2026-10-20T12:29:37.088000+00:00"
    unassignedTopics: null
    staleTopics: null
    message: null
```

Patterns are compared to detect a change but cannot be checked against an assignment: only topics
known by name are.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `AUTO_REBALANCE_ENABLED` | `true` | Rebalance after subscription changes; per app, `kaspr.io/auto-rebalance` |
| `REBALANCE_CHECK_INTERVAL_SECONDS` | `5` | Status refresh interval while a rebalance is pending |
| `REBALANCE_VERIFY_DELAY_SECONDS` | `15` | Time a requested rebalance is given before the assignment is checked |
| `REBALANCE_MAX_ATTEMPTS` | `3` | Requests per change while the settled assignment does not match it |
| `REBALANCE_VERIFY_TIMEOUT_SECONDS` | `600` | Time after the first request after which the operator gives up |

`kaspr.io/rebalance: "true"` asks every member to rejoin at once; it also settles a pending
automatic rebalance, without checking it.
