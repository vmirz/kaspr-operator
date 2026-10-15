import asyncio
import hashlib
import kopf
import random
import time
import json
import base64
from dataclasses import dataclass, field
from logging import Logger
from collections import defaultdict
from typing import Any, List, Dict, Mapping, Optional, Tuple
from datetime import datetime, timezone, timedelta
from kubernetes_asyncio.client import ApiException
from kubernetes_asyncio.stream import WsApiClient
from kubernetes_asyncio.client import CoreV1Api
from kaspr.types.schemas.kasprapp_spec import (
    KasprAppSpecSchema,
)
from kaspr.types.models import KasprAppSpec
from kaspr.types.schemas import (
    KasprAgentSpecSchema,
    KasprTaskSpecSchema,
    KasprWebViewSpecSchema,
    KasprTableSpecSchema,
)
from kaspr.resources import KasprApp, KasprAgent, KasprWebView, KasprTable, KasprTask
from kaspr.resources.kasprapp import PodMetadataCache
from kaspr.types.settings import Settings
from kaspr.utils.helpers import upsert_condition, deep_compare_dict, now
from kaspr.utils.errors import convert_api_exception
from kaspr.utils.python_packages import compute_packages_hash

APP_KIND = "KasprApp"

AGENTS_UPDATED = "AgentsUpdated"
WEBVIEWS_UPDATED = "WebviewsUpdated"
TABLES_UPDATED = "TablesUpdated"

# Status values a component reports for its KasprApp (see the component handlers).
APP_NOT_FOUND = "AppNotFound"
APP_FOUND = "AppFound"

# KasprApps are identified by (namespace, name) in all per-app structures below.
AppKey = Tuple[Optional[str], str]

# Use a set to track which apps are already queued
names_in_queue = set()
# The actual queue for ordered processing
reconciliation_queue: Dict[AppKey, asyncio.Queue] = defaultdict(asyncio.Queue)
# Locks to prevent race conditions when enqueueing reconciliation requests
reconciliation_locks: Dict[AppKey, asyncio.Lock] = defaultdict(asyncio.Lock)
# Loop times of the first and the latest request for each queued reconciliation
reconciliation_requested_at: Dict[AppKey, Tuple[float, float]] = {}

# A queued reconciliation waits until requests stop arriving for this long (but no
# longer than the maximum), so a burst of changes is reconciled once, e.g. when many
# components are applied together or seen at operator startup.
RECONCILE_DEBOUNCE_SECONDS = 1.0
RECONCILE_DEBOUNCE_MAX_SECONDS = 10.0
# Track consecutive hung member detections: (app_name, member_id) -> consecutive_count
hung_member_tracking: Dict[tuple[str, int], int] = {}

TRUTHY = ("true", "1", "yes", "True", "Yes", "YES")


def _loop_time() -> float:
    return asyncio.get_running_loop().time()


@dataclass
class AppRuntimeState:
    """What the operator remembers about one KasprApp between handler runs.

    Reconciliation is driven by events (KasprApp and component changes). This state
    schedules the work that has no event: status refreshes, retries of failed
    reconciliations, and the periodic drift check.
    """

    # Loop time at which the next full reconciliation is due, and why.
    next_reconcile_at: Optional[float] = None
    next_reconcile_reason: str = "resync"
    last_status_update_at: Optional[float] = None
    # True while the last full reconciliation did not complete; the status of a
    # failing app is left to the retries so their error conditions stay visible.
    reconcile_failed: bool = False
    # Fingerprint of the StatefulSet as rendered by the last full reconciliation.
    desired_statefulset_fingerprint: Optional[str] = None
    pod_cache: PodMetadataCache = field(default_factory=PodMetadataCache)
    # (StatefulSet resourceVersion, packages hash, generation) of the last packages
    # evaluation, with what it found.
    packages_key: Optional[Tuple] = None
    packages_state: Optional[str] = None
    packages_had_pods: bool = False
    last_rebalance_deferral: Optional[str] = None

    def schedule_reconcile(self, delay: float, reason: str):
        """Schedule a full reconciliation, keeping an earlier one if already due sooner."""
        when = _loop_time() + delay
        if self.next_reconcile_at is None or when < self.next_reconcile_at:
            self.next_reconcile_at = when
            self.next_reconcile_reason = reason


app_states: Dict[AppKey, AppRuntimeState] = {}


def get_app_state(namespace: Optional[str], name: str) -> AppRuntimeState:
    """Return the runtime state of a KasprApp, creating it on first use."""
    state = app_states.get((namespace, name))
    if state is None:
        state = app_states[(namespace, name)] = AppRuntimeState()
    return state


def get_sensor():
    """Get sensor from KasprApp class.
    
    Returns:
        Sensor instance or None
    """
    return getattr(KasprApp, 'sensor', None)


async def fetch_app_related_resources(name: str, namespace: str) -> Dict[str, any]:
    """Fetch all resources related to a KasprApp in parallel.

    Args:
        name: The name of the KasprApp
        namespace: The namespace of the KasprApp

    Returns:
        Dictionary with keys: 'agents', 'webviews', 'tables', 'tasks', 'success'
        Each resource key contains a list of resource items
        'success' is True only if ALL fetches succeeded
    """
    agent_task, webview_task, table_task, task_task = await asyncio.gather(
        KasprAgent.default().search(namespace, apps=[name]),
        KasprWebView.default().search(namespace, apps=[name]),
        KasprTable.default().search(namespace, apps=[name]),
        KasprTask.default().search(namespace, apps=[name]),
        return_exceptions=True,
    )

    # Track whether all fetches succeeded
    all_succeeded = True
    
    # Handle potential errors and extract items
    def extract_items(result, resource_type: str):
        nonlocal all_succeeded
        if isinstance(result, Exception):
            # Log error but return empty list to allow partial results
            all_succeeded = False
            return []
        return result.get("items", []) if result else []

    return {
        "agents": extract_items(agent_task, "agents"),
        "webviews": extract_items(webview_task, "webviews"),
        "tables": extract_items(table_task, "tables"),
        "tasks": extract_items(task_task, "tasks"),
        "success": all_succeeded,
    }


def _component_from_item(resource_cls, schema_cls, item: Dict, namespace: str):
    """Build a component resource from its custom resource as listed from the API."""
    component = resource_cls.from_spec(
        item["metadata"]["name"],
        resource_cls.KIND,
        namespace,
        schema_cls().load(item["spec"]),
        dict(item["metadata"]["labels"]),
    )
    # The app may (re)create the component's config map, which must still be
    # owned by the component rather than by the app being handled.
    component.owner = item
    return component


async def attach_app_related_resources(
    app: KasprApp, name: str, namespace: str, related: Optional[Dict] = None
) -> bool:
    """Attach the app's agents, webviews, tables, and tasks to the app model.

    Args:
        related: Components as returned by fetch_app_related_resources; fetched
            when omitted.

    Returns False when any component fetch failed, in which case the attached
    collections are incomplete and must not be used to render the pod template.
    """
    if related is None:
        related = await fetch_app_related_resources(name, namespace)

    app.with_agents(
        [
            _component_from_item(KasprAgent, KasprAgentSpecSchema, item, namespace)
            for item in related["agents"]
        ]
    )
    app.with_webviews(
        [
            _component_from_item(KasprWebView, KasprWebViewSpecSchema, item, namespace)
            for item in related["webviews"]
        ]
    )
    app.with_tables(
        [
            _component_from_item(KasprTable, KasprTableSpecSchema, item, namespace)
            for item in related["tables"]
        ]
    )
    app.with_tasks(
        [
            _component_from_item(KasprTask, KasprTaskSpecSchema, item, namespace)
            for item in related["tasks"]
        ]
    )
    return related["success"]


async def request_reconciliation(name, namespace: str = None, **kwargs):
    """Request reconciliation for the KasprApp.

    Enqueues the request only if it's not already in the queue.
    This prevents duplicate processing while preserving order.
    Uses a lock to ensure atomicity of the check-and-add operation.
    """
    key = (namespace, name)
    async with reconciliation_locks[key]:
        current_time = _loop_time()
        first_requested_at, _ = reconciliation_requested_at.get(key, (current_time, None))
        reconciliation_requested_at[key] = (first_requested_at, current_time)
        if key not in names_in_queue:
            names_in_queue.add(key)
            await reconciliation_queue[key].put(name)
            
            # Instrument queue operation
            sensor = get_sensor()
            if sensor and namespace:
                queue_depth = reconciliation_queue[key].qsize()
                sensor.on_reconcile_queued(name, name, namespace, queue_depth)


def on_error(error, spec, meta, status, patch, **_):
    """Handle errors during reconciliation."""
    gen = meta.get("generation", 0)
    conds = (status or {}).get("conditions", [])
    error_message = _stringify_error(error)
    conds = upsert_condition(
        conds,
        {
            "type": "Progressing",
            "status": "False",
            "reason": "Error",
            "message": error_message,
            "observedGeneration": gen,
        },
    )
    conds = upsert_condition(
        conds,
        {
            "type": "Ready",
            "status": "False",
            "reason": "Error",
            "message": "Kaspr app not ready",
            "observedGeneration": gen,
        },
    )
    patch.status["conditions"] = conds


def _stringify_error(error) -> str:
    """Convert exceptions to JSON-serializable status messages."""
    if not error:
        return "Reconcile failed; see events/logs"

    if isinstance(error, ApiException):
        prefix = f"Kubernetes API error ({error.status}): {error.reason}"
        try:
            if error.body:
                body = json.loads(error.body)
                message = body.get("message") or body.get("status")
                if message:
                    return f"{prefix} - {message}"
        except (TypeError, ValueError, AttributeError):
            pass
        return prefix

    return str(error)


def _resource_hash(resource: Dict, hashes: Optional[Mapping[str, str]]) -> str:
    """Return a component's hash, preferring one computed from its current spec.

    A component reports its hash in its status only after its own handler ran, which
    can be later than the reconciliation its change triggered.
    """
    name = resource["metadata"]["name"]
    if hashes and name in hashes:
        return hashes[name]
    return resource.get("status", {}).get("hash", "")


def _extract_agent_info(
    resources: List, hashes: Optional[Mapping[str, str]] = None
) -> List[Dict]:
    """Extract agent info including subscription-relevant fields.
    
    Args:
        resources: List of agent resource dictionaries
        hashes: Hashes computed from the agents' specs, by agent name
        
    Returns:
        List of agent info dicts with name, hash, topicName, and topicPattern
    """
    result = []
    for resource in resources:
        info = {
            "name": resource["metadata"]["name"],
            "hash": _resource_hash(resource, hashes),
        }
        # Extract subscription-affecting fields from input.topic
        input_spec = resource.get("spec", {}).get("input", {})
        topic_spec = input_spec.get("topic", {})
        if topic_spec:
            # topic.name (string, can be comma-separated) or topic.pattern (string)
            if "name" in topic_spec:
                info["topicName"] = topic_spec["name"]
            if "pattern" in topic_spec:
                info["topicPattern"] = topic_spec["pattern"]
        result.append(info)
    return result


def _extract_table_info(
    resources: List, hashes: Optional[Mapping[str, str]] = None
) -> List[Dict]:
    """Extract table info including subscription-relevant fields.
    
    Args:
        resources: List of table resource dictionaries
        hashes: Hashes computed from the tables' specs, by table name
        
    Returns:
        List of table info dicts with name, hash, and tableName
    """
    result = []
    for resource in resources:
        info = {
            "name": resource["metadata"]["name"],
            "hash": _resource_hash(resource, hashes),
        }
        # Extract table name which determines the changelog topic
        table_name = resource.get("spec", {}).get("name")
        if table_name:
            info["tableName"] = table_name
        result.append(info)
    return result


def _extract_basic_info(
    resources: List, hashes: Optional[Mapping[str, str]] = None
) -> List[Dict]:
    """Extract name and hash for resources without subscription impact.
    
    Args:
        resources: List of resource dictionaries
        hashes: Hashes computed from the resources' specs, by resource name
        
    Returns:
        List of basic info dicts with name and hash
    """
    return [
        {
            "name": resource["metadata"]["name"],
            "hash": _resource_hash(resource, hashes),
        }
        for resource in resources
    ]


def _detect_agent_subscription_changes(
    current_agents: List[Dict],
    new_agents: List[Dict],
    app_name: str,
    logger: Logger
) -> bool:
    """Detect if agent subscription-affecting changes occurred.
    
    Compares the set of topics subscribed across all agents. A subscription change
    only occurs if the collective set of topics/patterns differs, not just if the
    number of agents changes (since multiple agents can subscribe to the same topics).
    
    Args:
        current_agents: Current agent info from status
        new_agents: New agent info from cluster
        app_name: Name of the KasprApp
        logger: Logger instance
        
    Returns:
        True if subscription-affecting changes detected
    """
    def extract_topic_subscriptions(agents: List[Dict]) -> tuple[set, set]:
        """Extract sets of topic names and patterns from agents.
        
        Returns:
            Tuple of (topic_names_set, topic_patterns_set)
        """
        topic_names = set()
        topic_patterns = set()
        
        for agent in agents:
            # Handle topic names (comma-separated string)
            topic_name = agent.get("topicName")
            if topic_name:
                # Split comma-separated topics and add each to the set
                for topic in topic_name.split(","):
                    stripped = topic.strip()
                    if stripped:
                        topic_names.add(stripped)
            
            # Handle topic patterns
            topic_pattern = agent.get("topicPattern")
            if topic_pattern:
                topic_patterns.add(topic_pattern.strip())
        
        return topic_names, topic_patterns
    
    # Extract topic subscriptions from both states
    current_names, current_patterns = extract_topic_subscriptions(current_agents)
    new_names, new_patterns = extract_topic_subscriptions(new_agents)
    
    # Compare the sets of subscribed topics
    if current_names != new_names:
        added_names = new_names - current_names
        removed_names = current_names - new_names
        logger.info(
            f"Topic name subscriptions changed for {app_name}. "
            f"Added: {added_names or 'none'}, Removed: {removed_names or 'none'}"
        )
        return True
    
    if current_patterns != new_patterns:
        added_patterns = new_patterns - current_patterns
        removed_patterns = current_patterns - new_patterns
        logger.info(
            f"Topic pattern subscriptions changed for {app_name}. "
            f"Added: {added_patterns or 'none'}, Removed: {removed_patterns or 'none'}"
        )
        return True
    
    return False


def _detect_table_subscription_changes(
    current_tables: List[Dict],
    new_tables: List[Dict],
    app_name: str,
    logger: Logger
) -> bool:
    """Detect if table subscription-affecting changes occurred.
    
    Args:
        current_tables: Current table info from status
        new_tables: New table info from cluster
        app_name: Name of the KasprApp
        logger: Logger instance
        
    Returns:
        True if subscription-affecting changes detected
    """
    if len(new_tables) != len(current_tables):
        logger.info(f"Table count changed for {app_name}: {len(current_tables)} -> {len(new_tables)}")
        return True
    
    # Create maps by name for comparison
    current_tables_map = {t["name"]: t for t in current_tables}
    new_tables_map = {t["name"]: t for t in new_tables}

    # Check for new or modified tables
    for table_name, new_table in new_tables_map.items():
        current_table = current_tables_map.get(table_name)
        if not current_table:
            logger.info(f"New table detected: {table_name}")
            return True

        # Compare table name (which determines changelog topic)
        new_table_name = new_table.get("tableName")
        current_table_name = current_table.get("tableName")

        if new_table_name != current_table_name:
            logger.info(f"Table {table_name} name changed: {current_table_name} -> {new_table_name}")
            return True

    # Check for removed tables
    for table_name in current_tables_map:
        if table_name not in new_tables_map:
            logger.info(f"Table removed: {table_name}")
            return True
    
    return False


def _update_basic_status_fields(
    status_update: Dict,
    _status: Dict,
    _actual_status: Dict,
    app,
    logger: Logger
):
    """Update basic status fields like kasprVersion, availableMembers, etc.
    
    Args:
        status_update: Dictionary to accumulate status updates
        _status: Current status from CRD
        _actual_status: Actual status from cluster
        app: KasprApp instance
        logger: Logger instance
    """
    # Always update kasprVersion if changed
    if _actual_status.get("kasprVersion") and _actual_status[
        "kasprVersion"
    ] != _status.get("kasprVersion"):
        status_update["kasprVersion"] = _actual_status["kasprVersion"]

    if (
        _actual_status.get("availableMembers") is not None
        and _actual_status.get("desiredMembers") is not None
    ):
        availableMembers = f"{_actual_status['availableMembers']}/{_actual_status['desiredMembers']}"
        if availableMembers != _status.get("availableMembers"):
            status_update["availableMembers"] = availableMembers

    # Update members status with lastTransitionTime tracking
    if _actual_status.get("members") is not None:
        current_members = _status.get("members", [])
        current_members_map = {m.get("id"): m for m in current_members if m.get("id") is not None}
        
        updated_members = []
        for new_member in _actual_status["members"]:
            member_id = new_member.get("id")
            current_member = current_members_map.get(member_id, {})
            
            # Check if any state has changed (leader, rebalancing, recovering)
            leader_changed = new_member.get("leader") != current_member.get("leader")
            rebalancing_changed = new_member.get("rebalancing") != current_member.get("rebalancing")
            recovering_changed = new_member.get("recovering") != current_member.get("recovering")
            state_changed = leader_changed or rebalancing_changed or recovering_changed
            pod_uid_changed = (
                bool(new_member.get("podUID"))
                and new_member.get("podUID") != current_member.get("podUID")
            )
            pod_creation_changed = (
                bool(new_member.get("podCreationTime"))
                and new_member.get("podCreationTime") != current_member.get("podCreationTime")
            )
            incarnation_changed = pod_uid_changed or pod_creation_changed
            
            # Build filtered member object with only desired properties
            filtered_member = {
                "id": member_id,
                "leader": new_member.get("leader"),
                "rebalancing": new_member.get("rebalancing"),
                "recovering": new_member.get("recovering"),
            }

            if new_member.get("podUID"):
                filtered_member["podUID"] = new_member.get("podUID")
            if new_member.get("podCreationTime"):
                filtered_member["podCreationTime"] = new_member.get("podCreationTime")
            
            # Preserve or update lastTransitionTime
            if state_changed or incarnation_changed or "lastTransitionTime" not in current_member:
                # State changed or first time seeing this member - update timestamp
                filtered_member["lastTransitionTime"] = now()
                
                # Log specific state changes
                if state_changed:
                    changes = []
                    if leader_changed:
                        changes.append(f"leader: {current_member.get('leader')} -> {new_member.get('leader')}")
                    if rebalancing_changed:
                        changes.append(f"rebalancing: {current_member.get('rebalancing')} -> {new_member.get('rebalancing')}")
                    if recovering_changed:
                        changes.append(f"recovering: {current_member.get('recovering')} -> {new_member.get('recovering')}")
                    logger.info(f"Member {member_id} state changed: {', '.join(changes)}")
                elif incarnation_changed:
                    logger.info(
                        f"Member {member_id} pod incarnation changed: "
                        f"podUID {current_member.get('podUID')} -> {new_member.get('podUID')}"
                    )
            else:
                # No state change - preserve existing timestamp
                filtered_member["lastTransitionTime"] = current_member.get("lastTransitionTime")
            
            updated_members.append(filtered_member)
        
        # Only update if members actually changed
        if not deep_compare_dict({"members": updated_members}, {"members": current_members}):
            status_update["members"] = updated_members

    if _actual_status.get("rolloutInProgress") is not None and _actual_status.get(
        "rolloutInProgress"
    ) != _status.get("rolloutInProgress"):
        status_update["rolloutInProgress"] = _actual_status["rolloutInProgress"]

    # Aggregate rebalancing status from members
    # Format: "<count of rebalancing members>/<available members>"
    if _actual_status.get("members") is not None:
        rebalancing_count = sum(
            1 for member in _actual_status["members"] if member.get("rebalancing", False)
        )
        available_members = _actual_status.get("availableMembers", 0)
        rebalancing_members = f"{rebalancing_count}/{available_members}"
        if rebalancing_members != _status.get("rebalancingMembers"):
            status_update["rebalancingMembers"] = rebalancing_members


def _is_rollout_complete(conds: List[Dict]) -> bool:
    """Check if rollout is complete by examining Progressing condition.
    
    Returns True if Progressing condition status is False.
    """
    for cond in conds:
        if cond.get("type") == "Progressing":
            return cond.get("status") == "False"
    return False


async def _detect_hung_members(
    _status: Dict,
    app: KasprApp,
    name: str,
    namespace: str,
    logger: Logger
) -> List[int]:
    """Detect members hung in rebalancing state.
    
    Identifies members that meet ALL criteria:
    - rebalancing=true AND recovering=false
    - lastTransitionTime > threshold seconds ago
    - App's Progressing condition is False (rollout complete)
    - Detected as hung for 3 consecutive checks
    
    Threshold can be overridden per-app via annotation:
    kaspr.io/hung-rebalancing-threshold-seconds: "600"
    
    Returns:
        List of hung member IDs ready for termination
    """
    # Check if hung member detection is enabled
    detection_enabled = app.conf.hung_member_detection_enabled
    
    # Check app-level annotation override
    if app.annotations:
        app_detection_enabled = app.annotations.get("kaspr.io/hung-member-detection-enabled")
        if app_detection_enabled is not None:
            detection_enabled = app_detection_enabled.lower() in TRUTHY
    
    if not detection_enabled:
        logger.debug("Hung member detection is disabled")
        return []
    
    # Check if rollout is complete
    conds = _status.get("conditions", [])
    if not _is_rollout_complete(conds):
        logger.debug("Skipping hung member detection - rollout in progress")
        # Clear tracking for this app since rollout is in progress
        keys_to_remove = [key for key in hung_member_tracking.keys() if key[0] == name]
        for key in keys_to_remove:
            del hung_member_tracking[key]
        return []
    
    # Get threshold from annotation or use default
    threshold_seconds = app.conf.hung_rebalancing_threshold_seconds
    if app.annotations:
        annotation_threshold = app.annotations.get(
            "kaspr.io/hung-rebalancing-threshold-seconds"
        )
        if annotation_threshold:
            try:
                threshold_seconds = int(annotation_threshold)
                logger.debug(
                    f"Using per-app hung rebalancing threshold: {threshold_seconds}s"
                )
            except ValueError:
                logger.warning(
                    f"Invalid hung-rebalancing-threshold-seconds annotation value: {annotation_threshold}, using default: {threshold_seconds}s"
                )
    
    threshold_time = datetime.now(timezone.utc) - timedelta(seconds=threshold_seconds)
    members = _status.get("members", [])
    
    # Track current hung members for this check
    current_hung_members = set()
    members_to_terminate = []
    
    for member in members:
        member_id = member.get("id")
        tracking_key = (name, member_id)
        
        if (
            member.get("rebalancing") is True
            and member.get("recovering") is False
        ):
            # Check if member has assignments (for info logging only)
            assignment = member.get("assignment", {})
            actives = assignment.get("actives", {})
            standbys = assignment.get("standbys", {})
            
            if not actives and not standbys:
                # Member has no assignments but still eligible for hung detection
                logger.info(f"Member {member_id} has no assignments but meets other hung criteria")
            
            last_transition = member.get("lastTransitionTime")
            if last_transition:
                try:
                    transition_dt = datetime.fromisoformat(
                        last_transition.replace("Z", "+00:00")
                    )
                    if transition_dt < threshold_time:
                        # Member appears hung, increment consecutive count
                        current_hung_members.add(member_id)
                        consecutive_count = hung_member_tracking.get(tracking_key, 0) + 1
                        hung_member_tracking[tracking_key] = consecutive_count
                        
                        # Calculate hung duration
                        hung_duration = (datetime.now(timezone.utc) - transition_dt).total_seconds()
                        
                        logger.warning(
                            f"Member {member_id} detected as hung ({consecutive_count}/3) - "
                            f"rebalancing for {threshold_seconds}+ seconds"
                        )
                        
                        # Instrument hung member detection
                        sensor = get_sensor()
                        if sensor:
                            sensor.on_hung_member_detected(
                                name, namespace, member_id, consecutive_count, hung_duration
                            )
                        
                        # Only terminate after 3 consecutive detections
                        if consecutive_count >= 3:
                            members_to_terminate.append(member_id)
                    else:
                        # Member is rebalancing but not past threshold yet
                        hung_member_tracking.pop(tracking_key, None)
                except (ValueError, AttributeError) as e:
                    logger.warning(
                        f"Failed to parse lastTransitionTime for member {member_id}: {e}"
                    )
                    hung_member_tracking.pop(tracking_key, None)
        else:
            # Member is not in hung state, reset tracking
            hung_member_tracking.pop(tracking_key, None)
    
    # Clean up tracking for members that are no longer hung
    # (they may have recovered or been terminated)
    keys_to_remove = [
        key for key in hung_member_tracking.keys()
        if key[0] == name and key[1] not in current_hung_members
    ]
    for key in keys_to_remove:
        del hung_member_tracking[key]
    
    if members_to_terminate:
        logger.warning(
            f"Members ready for termination after 3 consecutive hung detections: {members_to_terminate}"
        )
    
    return members_to_terminate


async def _terminate_hung_members(
    app: KasprApp,
    hung_member_ids: List[int],
    name: str,
    namespace: str,
    logger: Logger
):
    """Terminate pods for hung members.
    
    Limits termination to max 5 at a time to prevent overwhelming
    the Kafka cluster with simultaneous rebalances.
    
    Args:
        app: KasprApp instance
        hung_member_ids: List of member IDs to terminate
        name: KasprApp name
        namespace: Kubernetes namespace
        logger: Logger instance
        memo: Kopf memo containing sensor
    """
    if not hung_member_ids:
        return
    
    # Limit to max 5 members per cycle to avoid overwhelming the cluster
    max_concurrent_terminations = 5
    members_to_terminate = hung_member_ids[:max_concurrent_terminations]
    
    if len(hung_member_ids) > max_concurrent_terminations:
        logger.info(
            f"Limiting termination to {max_concurrent_terminations} members this cycle. "
            f"Remaining {len(hung_member_ids) - max_concurrent_terminations} will be handled in next cycle."
        )
    
    # Delete selected pods in parallel with 15 second timeout
    try:
        await asyncio.wait_for(
            asyncio.gather(
                *[app.terminate_member(member_id) for member_id in members_to_terminate],
                return_exceptions=True
            ),
            timeout=120.0
        )
        
        # Instrument member terminations
        sensor = get_sensor()
        if sensor:
            for member_id in members_to_terminate:
                sensor.on_member_terminated(name, namespace, member_id, "hung")
    except asyncio.TimeoutError:
        logger.error("Timeout waiting for hung member pod deletions to complete (15s limit exceeded)")


def _update_linked_resources_status(
    status_update: Dict,
    _status: Dict,
    app: KasprApp,
    related_resources: Dict,
    name: str,
    logger: Logger
) -> bool:
    """Update linkedResources status and detect subscription changes.
    
    Args:
        status_update: Dictionary to accumulate status updates
        _status: Current status from CRD
        app: KasprApp instance
        related_resources: Related resources fetched from cluster
        name: KasprApp name
        logger: Logger instance
        
    Returns:
        True if subscription-affecting changes detected
    """
    # A required rebalance stays pending until a rebalance is requested
    # successfully (see _attempt_auto_rebalance), which usually has to wait for
    # the rollout carrying the new subscriptions to finish.
    if not app.static_group_membership_enabled:
        # Dynamic group membership rebalances on its own.
        if _status.get("rebalanceRequired"):
            status_update["rebalanceRequired"] = False
        return False

    # Only evaluate subscription changes if fetch was fully successful
    # to avoid false positives from empty lists due to fetch failures
    fetch_succeeded = related_resources.get("success", False)
    if not fetch_succeeded:
        logger.warning(f"Skipping subscription change detection for {name} - resource fetch failed")
        return False

    hashes = related_resources.get("hashes") or {}
    agents_info = _extract_agent_info(related_resources["agents"], hashes.get("agents"))
    webviews_info = _extract_basic_info(related_resources["webviews"], hashes.get("webviews"))
    tables_info = _extract_table_info(related_resources["tables"], hashes.get("tables"))
    tasks_info = _extract_basic_info(related_resources["tasks"], hashes.get("tasks"))

    # Get current resources from status
    current_resources = _status.get("linkedResources", {})
    
    # Check if this is the first time tracking resources (migration safety)
    # If linkedResources doesn't exist or is empty, initialize without triggering rebalance
    is_first_tracking = not current_resources or not any(
        current_resources.get(key) for key in ["agents", "tables", "webviews", "tasks"]
    )

    if is_first_tracking:
        # First time tracking - initialize status without triggering rebalance
        status_update["linkedResources"] = {
            "agents": agents_info,
            "webviews": webviews_info,
            "tables": tables_info,
            "tasks": tasks_info,
        }
        logger.info(f"Initialized linkedResources tracking for {name} (no rebalance triggered)")
        return False

    # Check if any resources changed (using deep comparison for nested structures)
    resources_changed = (
        not deep_compare_dict(
            {"agents": agents_info}, {"agents": current_resources.get("agents", [])}
        )
        or not deep_compare_dict(
            {"webviews": webviews_info},
            {"webviews": current_resources.get("webviews", [])},
        )
        or not deep_compare_dict(
            {"tables": tables_info}, {"tables": current_resources.get("tables", [])}
        )
        or not deep_compare_dict(
            {"tasks": tasks_info}, {"tasks": current_resources.get("tasks", [])}
        )
    )

    subscription_changed = False
    change_details = []
    
    if resources_changed:
        status_update["linkedResources"] = {
            "agents": agents_info,
            "webviews": webviews_info,
            "tables": tables_info,
            "tasks": tasks_info,
        }

        # Surgical detection: only check subscription-affecting changes
        current_agents = current_resources.get("agents", [])
        if _detect_agent_subscription_changes(current_agents, agents_info, name, logger):
            subscription_changed = True
            change_details.append("agent topic subscriptions")
        
        if not subscription_changed:
            current_tables = current_resources.get("tables", [])
            if _detect_table_subscription_changes(current_tables, tables_info, name, logger):
                subscription_changed = True
                change_details.append("table changelog topics")

        # Mark rebalance required if subscriptions changed
        if subscription_changed:
            status_update["rebalanceRequired"] = True
            logger.info(
                f"Subscription change detected for {name}: {', '.join(change_details)} - marking rebalance required"
            )
    
    return subscription_changed


def _update_conditions(
    status_update: Dict,
    _status: Dict,
    _actual_status: Dict,
    gen: int,
    cur_gen: int,
    app,
    hung_member_ids: List[int] = None
):
    """Update status conditions based on reconciliation state.
    
    Args:
        status_update: Dictionary to accumulate status updates
        _status: Current status from CRD
        _actual_status: Actual status from cluster
        gen: Current generation
        cur_gen: Current observed generation
        app: KasprApp instance
        hung_member_ids: List of member IDs hung in rebalancing (if any)
    """
    # Start with conditions already in status_update (e.g., PythonPackagesReady)
    # or fall back to current status conditions
    conds = status_update.get("conditions", _status.get("conditions", []))
    
    # If hung members detected, override Ready condition
    if hung_member_ids:
        conds = upsert_condition(
            conds,
            {
                "type": "Progressing",
                "status": "False",
                "reason": "ReconcileComplete",
                "message": "All resources are in desired state",
                "observedGeneration": gen,
            },
        )
        conds = upsert_condition(
            conds,
            {
                "type": "Ready",
                "status": "False",
                "reason": "HungMembers",
                "message": f"Members {hung_member_ids} hung in rebalancing state - terminating pods",
                "observedGeneration": gen,
            },
        )
        status_update["conditions"] = conds
        return
    
    # Normal condition updates

    # If we are reconciling a new generation, set Progressing True, Ready False
    if cur_gen != gen:
        conds = upsert_condition(
            conds,
            {
                "type": "Progressing",
                "status": "True",
                "reason": "NewSpec",
                "message": "Reconciling desired state",
                "observedGeneration": gen,
            },
        )
        conds = upsert_condition(
            conds,
            {
                "type": "Ready",
                "status": "False",
                "reason": "NotReady",
                "message": "Rollout in progress",
                "observedGeneration": gen,
            },
        )
    # If everything is healthy, set Progressing False, Ready True
    elif _actual_status["availableMembers"] == app.replicas:
        conds = upsert_condition(
            conds,
            {
                "type": "Progressing",
                "status": "False",
                "reason": "ReconcileComplete",
                "message": "All resources are in desired state",
                "observedGeneration": gen,
            },
        )
        conds = upsert_condition(
            conds,
            {
                "type": "Ready",
                "status": "True",
                "reason": "Healthy",
                "message": "App is ready",
                "observedGeneration": gen,
            },
        )
    # If not healthy, keep Progressing True, Ready False
    else:
        conds = upsert_condition(
            conds,
            {
                "type": "Progressing",
                "status": "True",
                "reason": "Reconciling",
                "message": "Waiting for resources to become ready",
                "observedGeneration": gen,
            },
        )
        conds = upsert_condition(
            conds,
            {
                "type": "Ready",
                "status": "False",
                "reason": "NotReady",
                "message": "Kaspr app not ready",
                "observedGeneration": gen,
            },
        )

    status_update["conditions"] = conds


async def _attempt_auto_rebalance(
    status_update: Dict,
    _status: Dict,
    _actual_status: Dict,
    annotations: Dict,
    app: KasprApp,
    name: str,
    namespace: str,
    logger: Logger,
    state: Optional[AppRuntimeState] = None,
):
    """Attempt automatic rebalance if required and conditions are met.
    
    This function calls app.request_rebalance() directly rather than using the
    kaspr.io/rebalance annotation mechanism for performance and simplicity:
    - Half the API calls (no annotation patch operations)
    - No race conditions between handlers
    - Simpler control flow within single status update
    - rebalanceRequired flag provides natural retry mechanism
    
    Does not raise errors to avoid rolling back status patches. The rebalanceRequired
    flag will persist and trigger retry on next status update cycle.
    
    Args:
        status_update: Dictionary to accumulate status updates
        _status: Current status from CRD
        _actual_status: Actual status from cluster
        annotations: KasprApp annotations
        app: KasprApp instance
        name: KasprApp name
        namespace: Kubernetes namespace
        logger: Logger instance
        memo: Kopf memo containing sensor
    """
    if not status_update.get("rebalanceRequired", _status.get("rebalanceRequired")):
        return
    
    # Check operator-level config
    auto_rebalance_enabled = app.conf.auto_rebalance_enabled

    # Check app-level annotation override
    app_auto_rebalance = annotations.get("kaspr.io/auto-rebalance")
    if app_auto_rebalance is not None:
        auto_rebalance_enabled = app_auto_rebalance.lower() in TRUTHY

    if not auto_rebalance_enabled:
        logger.debug(f"Automatic rebalance disabled for {name}")
        return

    # Check prerequisites for rebalance
    can_rebalance = (
        not _actual_status.get("rolloutInProgress")
        and _actual_status.get("availableMembers") == _actual_status.get("desiredMembers")
        and app.conf.client_status_check_enabled
    )

    if can_rebalance:
        # Instrument rebalance start
        sensor = get_sensor()
        sensor_state = None
        if sensor:
            sensor_state = sensor.on_rebalance_triggered(name, namespace, "subscription_change")
        
        rebalance_start_time = time.time()
        success = False
        if state is not None:
            state.last_rebalance_deferral = None
        
        try:
            logger.info(f"Attempting automatic rebalance for {name} due to subscription changes")
            requested, reason = await app.request_rebalance(status=_actual_status)

            if requested:
                # Clear the flag on successful rebalance
                status_update["rebalanceRequired"] = False
                success = True
                logger.info(f"Automatic rebalance completed successfully for {name}")
            else:
                # Rebalance not ready, keep flag set for retry on next status update
                logger.warning(f"Automatic rebalance not ready for {name}: {reason}")

        except Exception as e:
            # Log error but don't raise to avoid rolling back status patches
            # The rebalanceRequired flag remains set and will trigger retry
            logger.error(f"Automatic rebalance failed for {name}: {e}")
            logger.exception(e)
        finally:
            # Instrument rebalance complete
            if sensor and sensor_state is not None:
                duration = time.time() - rebalance_start_time
                sensor.on_rebalance_complete(name, namespace, sensor_state, success, duration)
    else:
        # Prerequisites not met, log details
        # Flag remains set and will retry when conditions improve
        reasons = []
        if _actual_status.get("rolloutInProgress"):
            reasons.append("rollout in progress")
        if _actual_status.get("availableMembers") != _actual_status.get("desiredMembers"):
            reasons.append(f"members not ready ({_actual_status.get('availableMembers')}/{_actual_status.get('desiredMembers')})")
        if not app.conf.client_status_check_enabled:
            reasons.append("client status check disabled")

        deferral = ", ".join(reasons)
        if state is None or state.last_rebalance_deferral != deferral:
            logger.info(f"Automatic rebalance deferred for {name}: {deferral}")
        else:
            logger.debug(f"Automatic rebalance deferred for {name}: {deferral}")
        if state is not None:
            state.last_rebalance_deferral = deferral


async def fetch_python_packages_status(
    app: KasprApp, logger: Logger, pods=None
) -> tuple[Optional[Dict], Optional[Dict]]:
    """Fetch Python packages installation status from pods.
    
    Supports two modes:
    1. Shared cache (PVC): All pods share storage, check marker files
    2. emptyDir: Per-pod ephemeral storage, check init container status only
    
    Args:
        app: KasprApp instance
        logger: Logger instance
        pods: The app's pods (V1PodList) if already listed; listed when omitted
        
    Returns:
        Tuple of (metadata_dict, state_dict):
        - metadata_dict: Contains hash, installed, cacheMode, lastInstallTime, 
          installDuration, installedBy, warnings (goes into status.pythonPackages)
        - state_dict: Contains state, reason, message, error for condition creation
        Returns (None, None) if unable to determine status or packages not configured
    """
    if not app.python_packages:
        return None, None
    
    cache = getattr(app.python_packages, 'cache', None)
    cache_enabled = cache.enabled if cache and hasattr(cache, 'enabled') else app.DEFAULT_PACKAGES_CACHE_ENABLED
    
    # Determine cache mode - use user-friendly names for status reporting
    cache_mode = "persistent" if cache_enabled else "ephemeral"
    
    # For emptyDir mode, we can only check init container status (no shared marker file)
    is_emptydir = not cache_enabled
    
    # Compute packages hash once and reuse throughout (only for cache mode)
    packages_hash = compute_packages_hash(app.python_packages) if cache_enabled else None
    
    try:
        # List pods for this app
        if pods is None:
            pods = await app.list_pods(app.core_v1_api, app.namespace, app.labels.kasper_label_selectors().as_dict())
        
        if not pods or not pods.items:
            # No pods yet
            metadata = {
                "cacheMode": cache_mode,
            }
            if packages_hash:
                metadata["hash"] = packages_hash
            
            state_info = {
                "state": "Installing",
                "reason": "Installing",
                "message": f"Installing packages ({cache_mode} mode)",
            }
            return metadata, state_info
        
        # Find pod with init container
        # For cache mode: prefer pod with matching hash
        # For emptyDir: any pod with init container is fine
        target_pod = None
        
        if cache_enabled and packages_hash:
            # Cache mode: Find pod with init container matching the current packages hash
            # This ensures we check the status of the LATEST package installation attempt,
            # not a stale pod with old packages during rolling updates
            for pod in pods.items:
                if pod.status and pod.status.init_container_statuses:
                    for init_status in pod.status.init_container_statuses:
                        if init_status.name == "install-packages":
                            # Check if this pod's init container has the current packages hash
                            pod_hash = None
                            if pod.spec and pod.spec.init_containers:
                                for init_container in pod.spec.init_containers:
                                    if init_container.name == "install-packages":
                                        if init_container.env:
                                            for env_var in init_container.env:
                                                if env_var.name == "PACKAGES_HASH":
                                                    pod_hash = env_var.value
                                                    break
                                        break
                            
                            # If this pod has the current hash, use it
                            if pod_hash == packages_hash:
                                target_pod = pod
                                break
                if target_pod:
                    break
        
        # If no pod with current hash found (or emptyDir mode), use any pod with install-packages init container
        if not target_pod:
            for pod in pods.items:
                if pod.status and pod.status.init_container_statuses:
                    for init_status in pod.status.init_container_statuses:
                        if init_status.name == "install-packages":
                            target_pod = pod
                            break
                if target_pod:
                    break
        
        if not target_pod:
            # Pods exist but no init container found yet
            metadata = {
                "cacheMode": cache_mode,
            }
            if packages_hash:
                metadata["hash"] = packages_hash
            
            state_info = {
                "state": "Installing",
                "reason": "Installing",
                "message": f"Installing packages ({cache_mode} mode)",
            }
            return metadata, state_info
        
        # Check init container status
        init_container_status = None
        if target_pod.status and target_pod.status.init_container_statuses:
            for init_status in target_pod.status.init_container_statuses:
                if init_status.name == "install-packages":
                    init_container_status = init_status
                    break
        
        if not init_container_status:
            metadata = {
                "cacheMode": cache_mode,
            }
            if packages_hash:
                metadata["hash"] = packages_hash
            
            state_info = {
                "state": "Installing",
                "reason": "Installing",
                "message": f"Installing packages ({cache_mode} mode)",
            }
            return metadata, state_info
        
        # Check if init container is waiting (CrashLoopBackOff, retrying, etc.)
        if init_container_status.state and init_container_status.state.waiting:
            waiting_reason = init_container_status.state.waiting.reason or "Waiting"
            waiting_message = init_container_status.state.waiting.message or ""
            
            # If it's in CrashLoopBackOff or error state, it means installation failed and is retrying
            if waiting_reason in ["CrashLoopBackOff", "Error", "ErrImagePull", "ImagePullBackOff"]:
                # Try to get more detailed error from terminated state (last run)
                error_details = waiting_message
                if init_container_status.last_state and init_container_status.last_state.terminated:
                    if init_container_status.last_state.terminated.message:
                        error_details = init_container_status.last_state.terminated.message
                
                error_msg = f"Installation failed: {error_details}" if error_details else "Package installation failed (retrying)"
                
                metadata = {
                    "cacheMode": cache_mode,
                }
                if packages_hash:
                    metadata["hash"] = packages_hash
                
                state_info = {
                    "state": "Failed",
                    "reason": "InstallationFailed", 
                    "message": error_msg,
                    "error": error_msg,
                }
                return metadata, state_info
            else:
                # Other waiting states (e.g., PodInitializing) - treat as Installing
                metadata = {
                    "cacheMode": cache_mode,
                }
                if packages_hash:
                    metadata["hash"] = packages_hash
                
                state_info = {
                    "state": "Installing",
                    "reason": "Installing",
                    "message": f"Installing packages ({cache_mode} mode, status: {waiting_reason})",
                }
                return metadata, state_info
        
        # Check if init container failed (terminated with non-zero exit code)
        if init_container_status.state and init_container_status.state.terminated:
            if init_container_status.state.terminated.exit_code != 0:
                error_msg = init_container_status.state.terminated.message or "Package installation failed"
                metadata = {
                    "cacheMode": cache_mode,
                }
                if packages_hash:
                    metadata["hash"] = packages_hash
                
                state_info = {
                    "state": "Failed",
                    "reason": "InstallationFailed",
                    "message": error_msg,
                    "error": error_msg,
                }
                return metadata, state_info
        
        # Check if init container is still running
        if init_container_status.state and init_container_status.state.running:
            metadata = {
                "cacheMode": cache_mode,
            }
            if packages_hash:
                metadata["hash"] = packages_hash
            
            state_info = {
                "state": "Installing",
                "reason": "Installing",
                "message": f"Installing packages ({cache_mode} mode)",
            }
            return metadata, state_info
        
        # Init container completed successfully
        if init_container_status.state and init_container_status.state.terminated and init_container_status.state.terminated.exit_code == 0:
            # For emptyDir mode, we can't read marker files (they're pod-local)
            # Just report success based on init container completion
            if is_emptydir:
                num_packages = len(app.python_packages.packages)
                metadata = {
                    "cacheMode": cache_mode,
                    "installed": app.python_packages.packages,
                    "warnings": ["Ephemeral storage: packages reinstalled on every pod start"],
                }
                state_info = {
                    "state": "Ready",
                    "reason": "PackagesInstalled",
                    "message": f"Successfully installed {num_packages} package{'s' if num_packages != 1 else ''} (emptyDir mode)",
                }
                return metadata, state_info
            
            # For cache mode, try to read marker file
            try:
                # Read marker file from the pod
                marker_file = f"/opt/kaspr/packages/.installed-{packages_hash}"
                
                # Check if marker file exists and also list all marker files to detect hash mismatches
                # Use base64 encoding to avoid any shell/websocket string interpretation issues
                exec_command = [
                    '/bin/sh', '-c', 
                    f'if [ -f "{marker_file}" ]; then base64 "{marker_file}"; else echo "__MARKER_NOT_FOUND__"; fi; echo "__MARKER_LIST__"; ls -1 /opt/kaspr/packages/.installed-* 2>/dev/null || true'
                ]
                
                async with WsApiClient() as ws_api:
                    v1_ws = CoreV1Api(api_client=ws_api)
                    resp = await v1_ws.connect_get_namespaced_pod_exec(
                        target_pod.metadata.name,
                        app.namespace,
                        command=exec_command,
                        stderr=True,
                        stdin=False,
                        stdout=True,
                        tty=False,
                        _preload_content=True
                    )
                
                # Split response into marker file content and list of marker files
                marker_content = None
                existing_markers = []
                if resp:
                    parts = resp.split("__MARKER_LIST__")
                    marker_content = parts[0].strip()
                    if len(parts) > 1:
                        marker_list = parts[1].strip()
                        if marker_list:
                            existing_markers = [line.strip() for line in marker_list.split('\n') if line.strip()]
                
                # Check if the expected marker file was found
                if not marker_content or marker_content == "__MARKER_NOT_FOUND__":
                    logger.debug(f"Marker file {marker_file} not found in pod {target_pod.metadata.name}")
                    
                    # Check if there's an old marker file (different hash)
                    if existing_markers:
                        logger.info(f"Found old marker files in pod {target_pod.metadata.name}, packages are being updated")
                        # Old packages installed, new ones pending - report as Installing
                        metadata = {
                            "hash": packages_hash,
                            "cacheMode": cache_mode,
                        }
                        state_info = {
                            "state": "Installing",
                            "reason": "PackagesUpdating",
                            "message": f"Updating packages to hash {packages_hash[:8]}...",
                        }
                        return metadata, state_info
                    else:
                        # No marker files at all - this is unusual but init succeeded
                        logger.warning(f"Init container succeeded but no marker files found in pod {target_pod.metadata.name}")
                        metadata = {
                            "hash": packages_hash,
                            "cacheMode": cache_mode,
                            "warnings": ["Installation completed but marker file not found"],
                        }
                        state_info = {
                            "state": "Ready",
                            "reason": "PackagesInstalled",
                            "message": "Packages installed (marker file not found)",
                        }
                        return metadata, state_info
                
                # Found the marker file with the expected hash - decode it
                try:
                    decoded = base64.b64decode(marker_content).decode('utf-8')
                except Exception as e:
                    logger.warning(f"Failed to decode base64 response from pod {target_pod.metadata.name}: {e}")
                    metadata = {
                        "hash": packages_hash,
                        "cacheMode": cache_mode,
                        "warnings": ["Unable to decode marker file"],
                    }
                    state_info = {
                        "state": "Ready",
                        "reason": "PackagesInstalled",
                        "message": "Packages installed (unable to decode marker file)",
                    }
                    return metadata, state_info
                
                # Parse marker file JSON
                if not decoded:
                    logger.warning(f"Empty marker file in pod {target_pod.metadata.name}")
                    metadata = {
                        "hash": packages_hash,
                        "cacheMode": cache_mode,
                        "warnings": ["Marker file is empty"],
                    }
                    state_info = {
                        "state": "Ready",
                        "reason": "PackagesInstalled",
                        "message": "Packages installed (empty marker file)",
                    }
                    return metadata, state_info
                
                marker_data = json.loads(decoded)
                installed_packages = marker_data.get("packages", [])
                num_packages = len(installed_packages)
                
                metadata = {
                    "hash": packages_hash,
                    "installed": installed_packages,
                    "lastInstallTime": marker_data.get("install_time"),
                    "installDuration": marker_data.get("duration"),
                    "installedBy": marker_data.get("pod_name"),
                    "cacheMode": cache_mode,
                    "warnings": None
                }
                state_info = {
                    "state": "Ready",
                    "reason": "PackagesInstalled",
                    "message": f"Successfully installed {num_packages} package{'s' if num_packages != 1 else ''} in {marker_data.get('duration', 'unknown')}",
                }
                return metadata, state_info
                
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse marker file JSON from pod {target_pod.metadata.name}: {e}")
                metadata = {
                    "hash": packages_hash,
                    "cacheMode": cache_mode,
                    "warnings": ["Installation completed but marker file is invalid"],
                }
                state_info = {
                    "state": "Ready",
                    "reason": "PackagesInstalled",
                    "message": "Packages installed (invalid marker file)",
                }
                return metadata, state_info
            except Exception as e:
                # Marker file read failed but init succeeded - report as Ready with limited info
                error_str = str(e)
                
                # Provide user-friendly error messages for common issues
                if "403" in error_str or "Forbidden" in error_str:
                    warning_msg = "Unable to read installation details (missing pod/exec permission)"
                    logger.warning(
                        f"Failed to read marker file from pod {target_pod.metadata.name}: "
                        f"Permission denied (403). Service account needs pods/exec permission. "
                        f"Full error: {e}"
                    )
                elif "401" in error_str or "Unauthorized" in error_str:
                    warning_msg = "Unable to read installation details (authentication failed)"
                    logger.warning(f"Failed to read marker file from pod {target_pod.metadata.name}: Unauthorized. Full error: {e}")
                elif "404" in error_str or "Not Found" in error_str:
                    warning_msg = "Unable to read installation details (pod not found)"
                    logger.warning(f"Failed to read marker file from pod {target_pod.metadata.name}: Pod not found. Full error: {e}")
                else:
                    warning_msg = f"Unable to read installation details: {error_str[:100]}"
                    logger.warning(f"Failed to read marker file from pod {target_pod.metadata.name}: {e}")
                
                metadata = {
                    "cacheMode": cache_mode,
                    "warnings": [warning_msg],
                }
                if packages_hash:
                    metadata["hash"] = packages_hash
                
                state_info = {
                    "state": "Ready",
                    "reason": "PackagesInstalled",
                    "message": "Packages installed (details unavailable)",
                }
                return metadata, state_info
        
        # Fallback
        metadata = {
            "cacheMode": cache_mode,
        }
        if packages_hash:
            metadata["hash"] = packages_hash
        
        state_info = {
            "state": "Installing",
            "reason": "Installing",
            "message": f"Installing packages ({cache_mode} mode)",
        }
        return metadata, state_info
        
    except Exception as e:
        logger.error(f"Error fetching Python packages status: {e}")
        metadata = {}
        if packages_hash:
            metadata["hash"] = packages_hash
        state_info = {
            "state": "Unknown",
            "reason": "StatusUnknown",
            "message": f"Unable to determine package status: {str(e)}",
            "error": str(e),
        }
        return metadata, state_info


def create_python_packages_condition(state_info: Optional[Dict], gen: int) -> Optional[Dict]:
    """Create PythonPackagesReady condition from state info.
    
    Args:
        state_info: Dictionary with state, reason, message, error keys
        gen: Observed generation for the condition
        
    Returns:
        Condition dictionary or None if no state_info provided
    """
    if not state_info:
        return None
    
    state = state_info.get("state")
    if not state:
        return None
    
    # Map state to condition status
    if state == "Ready":
        status = "True"
    elif state in ("Installing", "Failed"):
        status = "False"
    else:  # Unknown
        status = "Unknown"
    
    return {
        "type": "PythonPackagesReady",
        "status": status,
        "reason": state_info.get("reason", state),
        "message": state_info.get("message", f"Python packages {state.lower()}"),
        "observedGeneration": gen,
    }


def _status_changes(current: Mapping[str, Any], update: Mapping[str, Any]) -> Dict[str, Any]:
    """Return the entries of a status update whose values differ from the current status."""
    changes = {}
    for key, value in update.items():
        current_value = current.get(key)
        if value is None:
            if current_value is not None:
                changes[key] = None
        elif current_value is None or not deep_compare_dict(current_value, value):
            changes[key] = value
    return changes


def _packages_evaluation_due(state: AppRuntimeState, packages_key: Tuple) -> bool:
    """Whether the Python packages status must be read from the app's pods again.

    Packages are installed while pods start, which also changes the StatefulSet.
    An installation that has not reached Ready is followed on every refresh for as
    long as there are pods to report on.
    """
    if state.packages_key != packages_key:
        return True
    return state.packages_state != "Ready" and state.packages_had_pods


def _check_statefulset_drift(
    state: AppRuntimeState, app: KasprApp, stateful_set, logger: Logger
):
    """Schedule a reconciliation if the StatefulSet no longer matches the desired state.

    Compares the StatefulSet read for the status against the one rendered by the
    last reconciliation, so a deleted or modified StatefulSet is repaired at the
    next status refresh without reading anything more from the API.
    """
    if state.desired_statefulset_fingerprint is None or state.reconcile_failed:
        return
    if stateful_set is None:
        reason = f"StatefulSet {app.stateful_set_name} is missing"
    elif (
        app.prepare_statefulset_fingerprint(stateful_set)
        != state.desired_statefulset_fingerprint
    ):
        reason = f"StatefulSet {app.stateful_set_name} differs from the desired state"
    else:
        return
    logger.info(f"{reason}; scheduling reconciliation.")
    state.schedule_reconcile(0, "drift")


async def update_status(
    name,
    spec,
    meta,
    status,
    patch,
    namespace,
    annotations,
    logger: Logger,
    related_resources: Optional[Dict] = None,
    state: Optional[AppRuntimeState] = None,
    **kwargs,
):
    """Update KasprApp status based on the actual state of the app.
    
    Batches all status updates into a single atomic patch operation to prevent
    conflicts and improve consistency. Only fields whose values changed are
    patched, so refreshing the status of an unchanged app writes nothing.

    Args:
        related_resources: The app's components as fetched by the reconciliation
            calling this. Linked resources are only re-evaluated when given. Without
            them this is a status refresh, which also checks the StatefulSet for drift.
        state: What the operator remembers about this app between refreshes.
    """
    spec_model: KasprAppSpec = KasprAppSpecSchema().load(spec)
    app = KasprApp.from_spec(
        name, APP_KIND, namespace, spec_model, annotations, logger=logger
    )
    _status = status or {}
    if state is None:
        state = AppRuntimeState()
    try:
        gen = meta.get("generation", 0)
        cur_gen = _status.get("observedGeneration")

        # Build status update dictionary atomically
        status_update = {}
        
        # Always update observedGeneration to match the current generation
        status_update["observedGeneration"] = gen

        # Pods are listed again only when the StatefulSet changed since the last refresh.
        state.pod_cache.listed_pods = None
        try:
            _actual_status = await app.fetch_app_status(pod_cache=state.pod_cache)
        except Exception as e:
            logger.error(f"Failed to fetch app status: {e}")
            return

        if related_resources is None:
            _check_statefulset_drift(state, app, app.observed_stateful_set, logger)

        if not _actual_status:
            return

        # Build all status updates atomically before patching
        _update_basic_status_fields(status_update, _status, _actual_status, app, logger)
        if related_resources is not None:
            _update_linked_resources_status(status_update, _status, app, related_resources, name, logger)
        if "rebalanceRequired" not in status_update and "rebalanceRequired" not in _status:
            status_update["rebalanceRequired"] = False
        
        # Update Python packages status if configured
        if app.python_packages:
            packages_key = (
                app.observed_stateful_set.metadata.resource_version,
                app.packages_hash,
                gen,
            )
            pods = None
            if _packages_evaluation_due(state, packages_key):
                pods = state.pod_cache.listed_pods
                if pods is None:
                    try:
                        pods = await app.list_pods(
                            app.core_v1_api,
                            app.namespace,
                            app.labels.kasper_label_selectors().as_dict(),
                        )
                    except Exception as e:
                        logger.warning(f"Failed to list pods for Python packages status: {e}")
            if pods is not None:
                packages_metadata, packages_state_info = await fetch_python_packages_status(
                    app, logger, pods=pods
                )
                state.packages_key = packages_key
                state.packages_state = (packages_state_info or {}).get("state")
                state.packages_had_pods = bool(pods.items)
            else:
                packages_metadata = packages_state_info = None
            if packages_metadata and packages_state_info:
                current_packages_status = _status.get("pythonPackages", {})
                current_conds = _status.get("conditions", [])
                
                # Find current PythonPackagesReady condition
                current_pkg_cond = next((c for c in current_conds if c.get("type") == "PythonPackagesReady"), None)
                current_pkg_state = packages_state_info.get("state")
                prev_pkg_state = current_pkg_cond.get("reason") if current_pkg_cond else None
                
                # Instrument package installation completion for metrics
                if current_pkg_state in ("Ready", "Failed") and prev_pkg_state != current_pkg_state:
                    sensor = get_sensor()
                    if sensor:
                        success = current_pkg_state == "Ready"
                        error_type = None
                        
                        if not success:
                            # Extract error type from error message
                            error_msg = packages_state_info.get("error", "")
                            if "timeout" in error_msg.lower():
                                error_type = "timeout"
                            elif "network" in error_msg.lower() or "connection" in error_msg.lower():
                                error_type = "network"
                            elif "invalid" in error_msg.lower() or "not found" in error_msg.lower():
                                error_type = "invalid_package"
                            else:
                                error_type = "unknown"
                        
                        # Create synthetic state with duration from marker file
                        install_duration = packages_metadata.get("installDuration")
                        if install_duration and success:
                            # installDuration is a string like "45.2s", parse it
                            try:
                                duration_seconds = float(install_duration.rstrip('s'))
                                synthetic_state = {
                                    'start_time': time.time() - duration_seconds
                                }
                            except (ValueError, AttributeError):
                                synthetic_state = None
                        else:
                            synthetic_state = None
                        
                        sensor.on_package_install_complete(
                            name,
                            namespace,
                            synthetic_state,
                            success,
                            error_type
                        )
                
                # Update metadata if changed
                if packages_metadata != current_packages_status:
                    status_update["pythonPackages"] = packages_metadata
                
                # Create/update PythonPackagesReady condition
                pkg_condition = create_python_packages_condition(packages_state_info, gen)
                if pkg_condition:
                    # Get or initialize conditions
                    conds = status_update.get("conditions", _status.get("conditions", []))
                    conds = upsert_condition(conds, pkg_condition)
                    status_update["conditions"] = conds
                    if prev_pkg_state != pkg_condition["reason"]:
                        logger.info(f"PythonPackagesReady condition: status={pkg_condition['status']}, reason={pkg_condition['reason']}")
        else:
            state.packages_key = None
            # Python packages spec was removed - clear status and condition if they exist
            if "pythonPackages" in _status:
                status_update["pythonPackages"] = None
                logger.info("Python packages removed from spec, clearing status")
            
            # Remove PythonPackagesReady condition
            current_conds = _status.get("conditions", [])
            if any(c.get("type") == "PythonPackagesReady" for c in current_conds):
                conds = [c for c in current_conds if c.get("type") != "PythonPackagesReady"]
                status_update["conditions"] = conds
                logger.info("Python packages removed from spec, clearing PythonPackagesReady condition")

        # Detect hung rebalancing members against the effective status snapshot,
        # including freshly computed member transition timestamps.
        effective_status = dict(_status)
        effective_status.update(status_update)
        hung_member_ids = await _detect_hung_members(effective_status, app, name, namespace, logger)
        
        _update_conditions(status_update, _status, _actual_status, gen, cur_gen, app, hung_member_ids)
        await _attempt_auto_rebalance(
            status_update, _status, _actual_status, annotations, app, name, namespace, logger, state=state
        )

        # Apply the changed status fields in a single atomic operation
        changes = _status_changes(_status, status_update)
        patch.status.update(changes)
        
        # Instrument status update
        sensor = get_sensor()
        if sensor and changes:
            update_fields = list(changes.keys())
            sensor.on_status_update(name, namespace, update_fields)

        # Terminate hung members after status update
        await _terminate_hung_members(app, hung_member_ids, name, namespace, logger)

    except Exception as e:
        logger.exception(e)
    finally:
        # Only the pod metadata is kept between refreshes.
        state.pod_cache.listed_pods = None


async def _report_app_status_to_components(
    components: List, app_status: str, logger: Logger
):
    """Record in each component's status whether its KasprApp exists.

    Components only report on their KasprApp when they are reconciled themselves,
    so the app tells them when it appears or goes away. Components that have not
    reported yet are left to their own handler.
    """
    for component in components:
        owner = component.owner or {}
        if (owner.get("metadata") or {}).get("deletionTimestamp"):
            continue
        reported = (owner.get("status") or {}).get("app") or {}
        desired = {"name": component.app_name, "status": app_status}
        if not reported or reported == desired:
            continue
        try:
            if await component.patch_app_status(app_status) is None:
                continue  # the component is gone
        except Exception as e:
            logger.warning(
                f"Failed to update the app status of {component.KIND} {component.cluster}: {e}"
            )
            continue
        location = f"`{component.namespace or 'default'}` namespace"
        if app_status == APP_FOUND:
            kopf.event(
                owner,
                type="Normal",
                reason=APP_FOUND,
                message=f"KasprApp `{component.app_name}` found in {location}.",
            )
        else:
            kopf.warn(
                owner,
                reason=APP_NOT_FOUND,
                message=f"KasprApp `{component.app_name}` does not exist in {location}.",
            )


RECONCILED = "reconciled"
RETRY = "retry"
FAILED_PERMANENTLY = "failed-permanently"
PAUSED = "paused"


async def reconcile(
    name,
    namespace,
    spec,
    meta,
    status,
    patch,
    annotations,
    logger: Logger,
    trigger_source: str = "manual",
    state: Optional[AppRuntimeState] = None,
    **kwargs,
) -> str:
    """Reconcile the KasprApp, its components' config maps, and its status.

    Returns the outcome: RECONCILED, PAUSED, RETRY when it failed and should be
    retried soon, or FAILED_PERMANENTLY when only a change can fix it.
    """
    # Instrument reconciliation start
    sensor = get_sensor()
    generation = meta.get('generation', 0)
    sensor_state = None
    if sensor:
        sensor_state = sensor.on_reconcile_start(name, name, namespace, generation, trigger_source)
    
    success = True
    error = None
    if state is None:
        state = AppRuntimeState()
    
    spec_model: KasprAppSpec = KasprAppSpecSchema().load(spec)
    app = KasprApp.from_spec(
        name, APP_KIND, namespace, spec_model, annotations, logger=logger
    )
    if app.reconciliation_paused:
        logger.info("Reconciliation is paused.")
        if sensor:
            sensor.on_reconcile_complete(name, name, namespace, sensor_state, True)
        return PAUSED
    try:
        # The pod template mounts one definition volume per related component, so the
        # components must be attached before the StatefulSet is rendered or compared.
        related = await fetch_app_related_resources(name, namespace)
        if not await attach_app_related_resources(app, name, namespace, related=related):
            logger.warning(
                "Skipping reconciliation for %s because one or more component "
                "fetches failed; retrying on the next cycle.",
                name,
            )
            return RETRY
        _record_component_observations(related, namespace, name)
        related["hashes"] = {
            "agents": {agent.cluster: agent.hash for agent in app.agents},
            "webviews": {webview.cluster: webview.hash for webview in app.webviews},
            "tables": {table.cluster: table.hash for table in app.tables},
            "tasks": {task.cluster: task.hash for task in app.tasks},
        }
        logger.debug(f"Reconciling {APP_KIND}/{name} in {namespace} namespace.")
        # Definitions must be current before the StatefulSet rolls pods that mount them.
        await app.sync_component_config_maps()
        await app.synchronize()
        state.desired_statefulset_fingerprint = app.prepare_statefulset_fingerprint(
            app.stateful_set
        )
        logger.debug(f"Reconciled {APP_KIND}/{name} in {namespace} namespace.")
        await _report_app_status_to_components(
            [*app.agents, *app.webviews, *app.tables, *app.tasks], APP_FOUND, logger
        )
        await update_status(
            name,
            spec,
            meta,
            status,
            patch,
            namespace,
            annotations,
            logger,
            related_resources=related,
            state=state,
        )
        return RECONCILED
    except Exception as e:
        success = False
        error = e
        logger.error(f"Unexpected error during reconcilation: {e}")
        logger.exception(e)
        error_patch = _StatusPatch()
        on_error(e, spec, meta, status, error_patch, **kwargs)
        patch.status.update(_status_changes(status or {}, error_patch.status))
        if isinstance(e, kopf.PermanentError):
            return FAILED_PERMANENTLY
        return RETRY
    finally:
        # Instrument reconciliation complete
        if sensor:
            sensor.on_reconcile_complete(name, name, namespace, sensor_state, success, error)


class _StatusPatch:
    """Collects the status written by on_error so only changed fields get patched."""

    def __init__(self):
        self.status = {}


@kopf.on.resume(kind=APP_KIND)
@kopf.on.create(kind=APP_KIND)
async def on_create(
    spec, name, meta, status, patch, namespace, annotations, logger: Logger, **kwargs
):
    """Creates KasprApp resources."""
    spec_model: KasprAppSpec = KasprAppSpecSchema().load(spec)
    app = KasprApp.from_spec(
        name, APP_KIND, namespace, spec_model, annotations, logger=logger
    )
    if app.reconciliation_paused:
        logger.info("Reconciliation is paused.")
        return
    
    # Warn if both image and pythonPackages are specified
    if spec.get('image') and spec.get('pythonPackages'):
        logger.warning(
            f"KasprApp {name} specifies both 'image' and 'pythonPackages'. "
            f"Packages will be installed in addition to custom image. "
            f"Consider using 'pythonPackages' alone for easier maintenance."
        )
    
    try:
        # Render the initial pod template with the component definition volumes already
        # attached, so the first pod does not start without them.
        await attach_app_related_resources(app, name, namespace)
        await app.create()
        await request_reconciliation(name, namespace=namespace, logger=logger)
    except Exception as e:
        logger.error(f"Failed to create KasprApp: {e}")
        on_error(e, spec, meta, status, patch, **kwargs)
        raise


@kopf.on.update(kind=APP_KIND, field="spec.image")
@kopf.on.update(kind=APP_KIND, field="spec.version")
async def on_version_update(
    old,
    new,
    diff,
    spec,
    name,
    meta,
    patch,
    status,
    namespace,
    annotations,
    logger: Logger,
    **kwargs,
):
    spec_model: KasprAppSpec = KasprAppSpecSchema().load(spec)
    app = KasprApp.from_spec(
        name, APP_KIND, namespace, spec_model, annotations, logger=logger
    )
    if app.reconciliation_paused:
        logger.info("Reconciliation is paused.")
        return
    try:
        await app.patch_version()
    except Exception as e:
        logger.error(f"Failed to patch version for KasprApp: {e}")
        on_error(e, spec, meta, status, patch, **kwargs)
        raise


@kopf.on.update(kind=APP_KIND, field="spec.replicas")
async def on_replicas_update(
    body,
    old,
    new,
    diff,
    spec,
    name,
    meta,
    patch,
    status,
    namespace,
    annotations,
    logger: Logger,
    **kwargs,
):
    spec_model: KasprAppSpec = KasprAppSpecSchema().load(spec)
    app = KasprApp.from_spec(
        name, APP_KIND, namespace, spec_model, annotations, logger=logger
    )
    if app.reconciliation_paused:
        logger.info("Reconciliation is paused.")
        return
    try:
        await app.patch_replicas()    
        
    except Exception as e:
        logger.error(f"Failed to patch replicas for KasprApp: {e}")
        on_error(e, spec, meta, status, patch, **kwargs)
        raise


@kopf.on.update(kind=APP_KIND, field="spec.bootstrapServers")
@kopf.on.update(kind=APP_KIND, field="spec.tls")
@kopf.on.update(kind=APP_KIND, field="spec.authentication")
async def on_kafka_credentials_update(
    old,
    new,
    diff,
    spec,
    name,
    meta,
    patch,
    status,
    namespace,
    annotations,
    logger: Logger,
    **kwargs,
):
    spec_model: KasprAppSpec = KasprAppSpecSchema().load(spec)
    app = KasprApp.from_spec(
        name, APP_KIND, namespace, spec_model, annotations, logger=logger
    )
    if app.reconciliation_paused:
        logger.info("Reconciliation is paused.")
        return
    try:
        await app.patch_kafka_credentials()
    except Exception as e:
        logger.error(f"Failed to patch Kafka credentials for KasprApp: {e}")
        on_error(e, spec, meta, status, patch, **kwargs)
        raise


@kopf.on.update(kind=APP_KIND, field="spec.resources")
async def on_resource_requirements_update(
    old,
    new,
    diff,
    spec,
    name,
    meta,
    patch,
    status,
    namespace,
    annotations,
    logger: Logger,
    **kwargs,
):
    spec_model: KasprAppSpec = KasprAppSpecSchema().load(spec)
    app = KasprApp.from_spec(
        name, APP_KIND, namespace, spec_model, annotations, logger=logger
    )
    if app.reconciliation_paused:
        logger.info("Reconciliation is paused.")
        return
    try:
        await app.patch_resource_requirements()
    except Exception as e:
        logger.error(f"Failed to patch resource requirements for KasprApp: {e}")
        on_error(e, spec, meta, status, patch, **kwargs)
        raise


@kopf.on.update(kind=APP_KIND, field="spec.config.web_port")
async def on_web_port_update(
    old,
    new,
    diff,
    spec,
    name,
    meta,
    patch,
    status,
    namespace,
    annotations,
    logger: Logger,
    **kwargs,
):
    spec_model: KasprAppSpec = KasprAppSpecSchema().load(spec)
    app = KasprApp.from_spec(
        name, APP_KIND, namespace, spec_model, annotations, logger=logger
    )
    if app.reconciliation_paused:
        logger.info("Reconciliation is paused.")
        return
    try:
        await app.patch_web_port()
    except Exception as e:
        logger.error(f"Failed to patch web port for KasprApp: {e}")
        on_error(e, spec, meta, status, patch, **kwargs)
        raise


@kopf.on.update(kind=APP_KIND, field="spec.storage.deleteClaim")
async def on_storage_delete_claim_update(
    old,
    new,
    diff,
    spec,
    name,
    meta,
    patch,
    status,
    namespace,
    annotations,
    logger: Logger,
    **kwargs,
):
    spec_model: KasprAppSpec = KasprAppSpecSchema().load(spec)
    app = KasprApp.from_spec(
        name, APP_KIND, namespace, spec_model, annotations, logger=logger
    )
    if app.reconciliation_paused:
        logger.info("Reconciliation is paused.")
        return
    try:
        await app.patch_storage_retention_policy()
    except Exception as e:
        logger.error(f"Failed to patch storage retention policy for KasprApp: {e}")
        on_error(e, spec, meta, status, patch, **kwargs)
        raise


@kopf.on.update(kind=APP_KIND, field="spec.storage.size")
async def on_storage_size_update(
    old,
    new,
    diff,
    spec,
    name,
    meta,
    patch,
    status,
    namespace,
    annotations,
    logger: Logger,
    **kwargs,
):
    spec_model: KasprAppSpec = KasprAppSpecSchema().load(spec)
    app = KasprApp.from_spec(
        name, APP_KIND, namespace, spec_model, annotations, logger=logger
    )
    if app.reconciliation_paused:
        logger.info("Reconciliation is paused.")
        return
    try:
        await app.patch_storage_size()
    except ApiException as e:
        logger.error(f"Failed to patch storage size for KasprApp: {e}")
        on_error(e, spec, meta, status, patch, **kwargs)
        convert_api_exception(e)
    except Exception as e:
        logger.error(f"Failed to patch storage size for KasprApp: {e}")
        on_error(e, spec, meta, status, patch, **kwargs)
        raise


@kopf.on.update(kind=APP_KIND, field="spec.template.serviceAccount")
async def on_template_service_account_updated(
    old,
    new,
    diff,
    spec,
    name,
    meta,
    patch,
    status,
    namespace,
    annotations,
    logger: Logger,
    **kwargs,
):
    spec_model: KasprAppSpec = KasprAppSpecSchema().load(spec)
    app = KasprApp.from_spec(
        name, APP_KIND, namespace, spec_model, annotations, logger=logger
    )
    if app.reconciliation_paused:
        logger.info("Reconciliation is paused.")
        return
    try:
        await app.patch_template_service_account()
    except Exception as e:
        logger.error(f"Failed to patch template service account for KasprApp: {e}")
        on_error(e, spec, meta, status, patch, **kwargs)
        raise


@kopf.on.update(kind=APP_KIND, field="spec.template.pod")
async def on_template_pod_updated(
    old,
    new,
    diff,
    spec,
    name,
    meta,
    patch,
    status,
    namespace,
    annotations,
    logger: Logger,
    **kwargs,
):
    spec_model: KasprAppSpec = KasprAppSpecSchema().load(spec)
    app = KasprApp.from_spec(
        name, APP_KIND, namespace, spec_model, annotations, logger=logger
    )
    if app.reconciliation_paused:
        logger.info("Reconciliation is paused.")
        return

    try:
        await app.patch_template_pod()
    except Exception as e:
        logger.error(f"Failed to patch template pod for KasprApp: {e}")
        on_error(e, spec, meta, status, patch, **kwargs)
        raise


@kopf.on.update(kind=APP_KIND, field="spec.template.service")
async def on_template_service_updated(
    old,
    new,
    diff,
    spec,
    name,
    meta,
    patch,
    status,
    namespace,
    annotations,
    logger: Logger,
    **kwargs,
):
    spec_model: KasprAppSpec = KasprAppSpecSchema().load(spec)
    app = KasprApp.from_spec(
        name, APP_KIND, namespace, spec_model, annotations, logger=logger
    )
    if app.reconciliation_paused:
        logger.info("Reconciliation is paused.")
        return

    try:
        await app.patch_template_service()
    except Exception as e:
        logger.error(f"Failed to patch template service for KasprApp: {e}")
        on_error(e, spec, meta, status, patch, **kwargs)
        raise


@kopf.on.update(kind=APP_KIND, field="spec.config.topic_partitions")
def immutable_config_updated_00(**kwargs):
    raise kopf.PermanentError(
        "Field 'spec.config.topic_partitions' can't change after creation."
    )


@kopf.on.update(kind=APP_KIND, field="spec.config")
async def general_config_update(
    spec, name, meta, patch, status, namespace, annotations, logger: Logger, **kwargs
):
    spec_model: KasprAppSpec = KasprAppSpecSchema().load(spec)
    app = KasprApp.from_spec(
        name, APP_KIND, namespace, spec_model, annotations, logger=logger
    )
    if app.reconciliation_paused:
        logger.info("Reconciliation is paused.")
        return
    try:
        await app.patch_settings()
    except Exception as e:
        logger.error(f"Failed to patch settings for KasprApp: {e}")
        on_error(e, spec, meta, status, patch, **kwargs)
        raise


@kopf.on.update(kind=APP_KIND, field="spec.pythonPackages")
async def on_python_packages_update(
    old, new, spec, name, meta, patch, status, namespace, annotations, logger: Logger, **kwargs
):
    """Handle updates to spec.pythonPackages field.
    
    Detects changes to:
    - Package list (added/removed/changed versions)
    - Cache configuration
    - Install policy
    - Resources
    
    Triggers reconciliation to sync packages.
    """
    logger.info(f"Python packages configuration changed for KasprApp {name}")
    
    spec_model: KasprAppSpec = KasprAppSpecSchema().load(spec)
    app = KasprApp.from_spec(
        name, APP_KIND, namespace, spec_model, annotations, logger=logger
    )
    
    if app.reconciliation_paused:
        logger.info("Reconciliation is paused.")
        return
    
    # Request reconciliation to sync packages
    await request_reconciliation(name, namespace=namespace, logger=logger)

# @kopf.on.validate(kind=APP_KIND, field="spec.storage.deleteClaim")
# def say_hello(warnings: list[str], **_):
#     warnings.append("Verified with the operator's hook.")

# @kopf.on.validate(kind=APP_KIND)
# def validate_storage_class_change(spec, old, **kwargs):
#     if 'storage' in spec and 'storage' in old:
#         if spec['storage'].get('class') != old['storage'].get('class'):
#             raise kopf.AdmissionError("Changing the storage.class field is not allowed.")


def _only_annotations_changed(diff, annotation_keys) -> bool:
    """Whether a kopf diff changes nothing but the given annotations."""
    for _op, path, old, new in diff or ():
        path = tuple(path)
        if path[:2] != ("metadata", "annotations"):
            return False
        if len(path) == 3 and path[2] in annotation_keys:
            continue
        if len(path) == 2:
            old_annotations = {k: v for k, v in (old or {}).items() if k not in annotation_keys}
            new_annotations = {k: v for k, v in (new or {}).items() if k not in annotation_keys}
            if old_annotations == new_annotations:
                continue
        return False
    return True


@kopf.on.update(kind=APP_KIND)
async def on_update_reconcile(name, namespace, diff, logger: Logger, **kwargs):
    """Reconcile the KasprApp after a change to its spec, labels or annotations.

    The field handlers above apply their targeted changes right away; this brings
    the rest of the desired state and the status up to date with the change.
    """
    # Rebalance requests are handled (and the annotation removed) by on_rebalance_requested.
    if _only_annotations_changed(diff, {"kaspr.io/rebalance"}):
        return
    await request_reconciliation(name, namespace)


@kopf.on.delete(kind=APP_KIND)
async def on_delete(name, namespace=None, logger: Logger = None, **kwargs):
    """Handle deletion of KasprApp resources."""
    # Clean up all global state for this resource
    key = (namespace, name)
    reconciliation_queue.pop(key, None)
    reconciliation_locks.pop(key, None)
    reconciliation_requested_at.pop(key, None)
    names_in_queue.discard(key)
    app_states.pop(key, None)
    
    # Clean up hung member tracking
    keys_to_remove = [key for key in hung_member_tracking.keys() if key[0] == name]
    for key in keys_to_remove:
        del hung_member_tracking[key]

    # Let the app's remaining components report that their app is gone.
    if namespace is None or logger is None:
        return
    try:
        related = await fetch_app_related_resources(name, namespace)
        app = KasprApp.default()
        await attach_app_related_resources(app, name, namespace, related=related)
        await _report_app_status_to_components(
            [*app.agents, *app.webviews, *app.tables, *app.tasks], APP_NOT_FOUND, logger
        )
    except Exception as e:
        logger.warning(f"Failed to update the components of deleted KasprApp {name}: {e}")


def _get_settings():
    """Operator settings (set on KasprApp at startup)."""
    conf = getattr(KasprApp, "conf", None)
    return conf if conf is not None else Settings()


@kopf.timer(APP_KIND, initial_delay=3.0, interval=1.5)
async def process_reconciliation_requests(
    name,
    namespace,
    spec,
    meta,
    status,
    patch,
    annotations,
    logger: Logger,
    stopped,
    **kwargs,
):
    """Run the work that is due for this KasprApp, one piece at a time.

    Reconciles the app when a reconciliation was requested (by a change to the app
    or one of its components) or is due for a retry or the periodic drift check.
    Otherwise refreshes the app's status once the status interval has passed. A
    tick with nothing due makes no API calls.
    """
    if stopped:
        return
    key = (namespace, name)
    state = get_app_state(namespace, name)
    conf = _get_settings()
    try:
        current_time = _loop_time()
        if state.next_reconcile_at is None and state.desired_statefulset_fingerprint is None:
            # Fallback in case the request from the resume/create handler never came.
            state.schedule_reconcile(conf.status_update_interval_seconds, "resync")

        trigger_source = None
        queue = reconciliation_queue.get(key)
        if queue is not None and not queue.empty():
            first_requested_at, last_requested_at = reconciliation_requested_at.get(
                key, (current_time, current_time)
            )
            if (
                current_time - last_requested_at < RECONCILE_DEBOUNCE_SECONDS
                and current_time - first_requested_at < RECONCILE_DEBOUNCE_MAX_SECONDS
            ):
                return  # more requests may follow; reconcile them all at once
            queue_start_time = time.time()
            queue.get_nowait()
            # Requests arriving from now on must queue another reconciliation, since
            # this one may already have read the state they are about.
            names_in_queue.discard(key)
            reconciliation_requested_at.pop(key, None)
            queue.task_done()
            trigger_source = "queue"
            
            # Instrument dequeue with wait time
            sensor = get_sensor()
            if sensor:
                wait_time = time.time() - queue_start_time
                sensor.on_reconcile_dequeued(name, name, namespace, wait_time)
        elif state.next_reconcile_at is not None and current_time >= state.next_reconcile_at:
            trigger_source = state.next_reconcile_reason
            
        if trigger_source is not None:
            state.next_reconcile_at = None
            start_time = time.time()
            outcome = await reconcile(
                name,
                namespace,
                spec,
                meta,
                status,
                patch,
                annotations,
                logger,
                trigger_source=trigger_source,
                state=state,
                **kwargs,
            )
            execution_time = time.time() - start_time
            logger.info(
                f"Reconciliation for {name} completed in {execution_time:.2f} seconds"
            )
            state.reconcile_failed = outcome in (RETRY, FAILED_PERMANENTLY)
            if outcome == RECONCILED:
                state.last_status_update_at = _loop_time()
            if outcome == RETRY:
                state.schedule_reconcile(conf.status_update_interval_seconds, "retry")
            elif outcome != PAUSED and conf.reconcile_interval_seconds > 0:
                interval = conf.reconcile_interval_seconds
                state.schedule_reconcile(interval * random.uniform(1.0, 1.1), "resync")
            return

        # Status refreshes follow successful reconciliations; while reconciliation
        # is paused or failing, the app's status is left as it is.
        if (
            state.desired_statefulset_fingerprint is None
            or state.reconcile_failed
            or (annotations or {}).get("kaspr.io/pause-reconciliation", "").lower() == "true"
        ):
            return
        if (
            state.last_status_update_at is not None
            and current_time - state.last_status_update_at < conf.status_update_interval_seconds
        ):
            return
        state.last_status_update_at = current_time
        await update_status(
            name, spec, meta, status, patch, namespace, annotations, logger, state=state
        )
    except asyncio.QueueEmpty:
        pass
    except Exception as e:
        logger.error(f"Error processing reconciliation request: {e}")
        # Ensure we don't get stuck on failed requests
        names_in_queue.discard(key)
        state.schedule_reconcile(conf.status_update_interval_seconds, "retry")


# What the operator last saw of each component (by uid): the KasprApp it belongs to
# and the parts of it that the app renders into its pod template.
component_observations: Dict[str, Tuple] = {}


def _observe_component(body: Mapping) -> Tuple[str, Tuple]:
    """Return a component's uid and what its KasprApp depends on.

    That is the component's spec and labels, which make up its definition. Its
    generation does not do: component resources have no status subresource, so
    their generation also moves with every status update.
    """
    metadata = body.get("metadata") or {}
    namespace = metadata.get("namespace")
    labels = dict(metadata.get("labels") or {})
    uid = metadata.get("uid") or f"{body.get('kind')}/{namespace}/{metadata.get('name')}"
    spec = json.dumps(body.get("spec"), sort_keys=True, separators=(",", ":"), default=str)
    observation = (
        namespace,
        labels.get(KasprApp.KASPR_APP_NAME_LABEL),
        hashlib.sha256(spec.encode()).hexdigest(),
        tuple(sorted(labels.items())),
    )
    return uid, observation


def _record_component_observations(related: Dict, namespace: str, app_name: str):
    """Remember the components a reconciliation of an app read.

    Events about components the app was reconciled with, or reconciled without
    (deleted or moved away), then trigger no repeat reconciliation.
    """
    listed = set()
    for kind in ("agents", "webviews", "tables", "tasks"):
        for item in related.get(kind, []):
            uid, observation = _observe_component(item)
            component_observations[uid] = observation
            listed.add(uid)
    for uid, observation in list(component_observations.items()):
        if observation[:2] == (namespace, app_name) and uid not in listed:
            del component_observations[uid]


async def notify_component_event(event_type: Optional[str], body: Mapping, logger: Logger):
    """Request reconciliation of the KasprApps affected by a component event.

    Components (agents, webviews, tables and tasks) are mounted into their app's
    pods, so the app is reconciled when a component is added, deleted, moved to
    another app, or has its spec or labels changed. Other events, such as status
    updates, and components the app has already reconciled are ignored.
    """
    uid, current = _observe_component(body)
    namespace, app_name = current[0], current[1]

    previous = component_observations.get(uid)
    if event_type == "DELETED":
        component_observations.pop(uid, None)
        if previous is None:
            return  # its app has been reconciled without it already
        affected = set()
    else:
        component_observations[uid] = current
        if current == previous:
            return
        affected = {(namespace, app_name)} if app_name else set()
    if previous and previous[1]:
        # The app it belonged to before (it was deleted or moved away).
        affected.add((previous[0], previous[1]))

    for app_namespace, affected_app in affected:
        logger.debug(f"Requesting reconciliation of KasprApp {affected_app} after a component change.")
        await request_reconciliation(affected_app, namespace=app_namespace)


@kopf.on.field(
    kind=APP_KIND,
    field="metadata.annotations",
    annotations={"kaspr.io/pause-reconciliation": kopf.PRESENT},
)
async def on_reconciliation_paused(
    name, diff, spec, namespace, logger: Logger, **kwargs
):
    """Handle reconciliation paused event."""
    await request_reconciliation(name, namespace, **kwargs)


@kopf.on.field(
    kind=APP_KIND,
    field="metadata.annotations",
    annotations={"kaspr.io/pause-reconciliation": kopf.ABSENT},
)
async def on_reconciliation_resumed(
    name, diff, spec, namespace, logger: Logger, **kwargs
):
    """Handle reconciliation resumed event."""
    await request_reconciliation(name, namespace, **kwargs)


@kopf.on.field(
    kind=APP_KIND,
    field="metadata.annotations",
    annotations={"kaspr.io/rebalance": kopf.PRESENT},
)
async def on_rebalance_requested(
    name, body, spec, namespace, annotations, patch, logger: Logger, status=None, **kwargs
):
    """Handle user-initiated rebalance request via annotation.
    
    This handler is for manual/user-triggered rebalances only. Automatic rebalances
    triggered by subscription changes use a separate direct-call path for better
    performance and simpler control flow (see _attempt_auto_rebalance).

    When kaspr.io/rebalance annotation is added, this handler:
    1. Attempts to rebalance the cluster
    2. Removes the annotation regardless of success/failure
    3. Posts an event indicating the result
    """
    spec_model: KasprAppSpec = KasprAppSpecSchema().load(spec)
    app = KasprApp.from_spec(
        name, APP_KIND, namespace, spec_model, annotations, logger=logger
    )

    try:
        logger.info(f"Rebalance requested for {name} via annotation")

        if not app.conf.client_status_check_enabled:
            raise kopf.PermanentError(
                "client status check is disabled in app config."
            )

        # Attempt rebalance
        requested, reason = await app.request_rebalance()
        if not requested:
            raise kopf.TemporaryError(reason, delay=30)

        # This rebalance also covers one pending from a subscription change.
        if (status or {}).get("rebalanceRequired"):
            patch.status["rebalanceRequired"] = False

    except Exception as e:
        # Post failure event
        kopf.event(
            body,
            type="Warning",
            reason="RebalanceRequestFailed",
            message=f"Rebalance request failed for '{name}' in '{namespace}' namespace: {e}",
        )

    finally:
        # Always remove the annotation to prevent repeated attempts
        if "kaspr.io/rebalance" in (annotations or {}):
            # Remove the annotation by setting it to None
            patch.metadata.annotations["kaspr.io/rebalance"] = None
            logger.info(f"Removed kaspr.io/rebalance annotation from {name}")
