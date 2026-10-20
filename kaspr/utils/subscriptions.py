"""What a KasprApp's members consume, and whether their assignment matches it.

With static group membership (KIP-345) a restarted member rejoins its consumer group
without a rebalance and gets back the partitions it held before. A rollout that
changes the app's subscriptions - an agent's topics, a table added or removed -
therefore leaves the group on its old assignment: an added topic is read by nobody,
and a removed one stays assigned to members that no longer subscribe to it. The
operator rebalances the group after such a rollout, and uses the helpers below to
tell what changed and whether the rebalance took effect, from the assignment every
member reports on its status endpoint.

Topics are known by name only: an agent subscribing with a pattern can change what it
consumes without its pattern changing, so patterns are compared but not verified.
"""

from dataclasses import dataclass, field
from typing import Iterable, List, Mapping, Optional, Set

from kaspr.types.models.kasprapp_resources import KasprAppResources


def changelog_topic(app_name: str, table_name: str) -> str:
    """The changelog topic of a table in an app.

    Faust names it ``<app id>-<table>-changelog``, and a Kaspr app's id is its
    component name, ``<KasprApp name>-app``.
    """
    return f"{KasprAppResources.component_name(app_name)}-{table_name}-changelog"


def agent_topics(agents: Iterable[Mapping]) -> Set[str]:
    """The topics agents subscribe to by name (``topicName``, comma-separated)."""
    topics = set()
    for agent in agents or ():
        for topic in (agent.get("topicName") or "").split(","):
            topic = topic.strip()
            if topic:
                topics.add(topic)
    return topics


def agent_patterns(agents: Iterable[Mapping]) -> Set[str]:
    """The topic patterns agents subscribe to."""
    return {
        agent["topicPattern"].strip()
        for agent in agents or ()
        if (agent.get("topicPattern") or "").strip()
    }


def subscribed_topics(linked_resources: Optional[Mapping], app_name: str) -> Set[str]:
    """Every topic an app consumes by name: its agents' topics and its tables' changelogs."""
    linked = linked_resources or {}
    topics = agent_topics(linked.get("agents"))
    for table in linked.get("tables") or ():
        if table.get("tableName"):
            topics.add(changelog_topic(app_name, table["tableName"]))
    return topics


@dataclass(frozen=True)
class SubscriptionChange:
    """How an app's subscriptions differ between two sets of linked resources."""

    added: Set[str] = field(default_factory=set)
    removed: Set[str] = field(default_factory=set)
    patterns_changed: bool = False

    def __bool__(self) -> bool:
        return bool(self.added or self.removed or self.patterns_changed)


def subscription_change(
    before: Optional[Mapping], after: Optional[Mapping], app_name: str
) -> SubscriptionChange:
    """The topics a change of linked resources adds and removes."""
    old = subscribed_topics(before, app_name)
    new = subscribed_topics(after, app_name)
    return SubscriptionChange(
        added=new - old,
        removed=old - new,
        patterns_changed=agent_patterns((before or {}).get("agents"))
        != agent_patterns((after or {}).get("agents")),
    )


@dataclass(frozen=True)
class AssignmentCheck:
    """Whether the group's assignment, as its members report it, matches the subscriptions."""

    #: Every member reported its assignment.
    reported: bool
    #: No member is rebalancing, so the reported assignment is the group's current one.
    settled: bool
    #: Topics the app subscribes to that no member is assigned.
    unassigned: List[str] = field(default_factory=list)
    #: Topics the app no longer subscribes to that some member is still assigned.
    stale: List[str] = field(default_factory=list)

    @property
    def satisfied(self) -> bool:
        return self.reported and self.settled and not self.unassigned and not self.stale


def check_assignment(
    members: Optional[Iterable[Mapping]],
    expected: Set[str],
    removed: Optional[Iterable[str]] = (),
) -> AssignmentCheck:
    """Compare the members' reported assignments with the topics they should consume.

    Args:
        members: Member statuses as fetched from the app, each with the ``assignment``
            the member reports (``actives`` and ``standbys``, partitions by topic).
        expected: Topics some member must actively consume.
        removed: Topics no member may be assigned any more.
    """
    members = list(members or ())
    if not members or any(not isinstance(m.get("assignment"), Mapping) for m in members):
        return AssignmentCheck(reported=False, settled=False)
    settled = not any(m.get("rebalancing") for m in members)
    actives: Set[str] = set()
    assigned: Set[str] = set()
    for member in members:
        assignment = member["assignment"]
        for kind in ("actives", "standbys"):
            topics = {topic for topic, partitions in (assignment.get(kind) or {}).items() if partitions}
            assigned |= topics
            if kind == "actives":
                actives |= topics
    removed = set(removed or ()) - set(expected)
    return AssignmentCheck(
        reported=True,
        settled=settled,
        unassigned=sorted(set(expected) - actives),
        stale=sorted(removed & assigned),
    )
