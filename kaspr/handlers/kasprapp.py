import asyncio
import kopf
import time
import json
import base64
from logging import Logger
from collections import defaultdict
from typing import List, Dict, Optional
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
    KasprWebViewSpecSchema,
    KasprTableSpecSchema,
)
from kaspr.resources import KasprApp, KasprAgent, KasprWebView, KasprTable, KasprTask
from kaspr.utils.helpers import upsert_condition, deep_compare_dict, now
from kaspr.utils.errors import convert_api_exception
from kaspr.utils.python_packages import compute_packages_hash

APP_KIND = "KasprApp"

AGENTS_UPDATED = "AgentsUpdated"
WEBVIEWS_UPDATED = "WebviewsUpdated"
TABLES_UPDATED = "TablesUpdated"

# Queue of requests to patch KasprApps
patch_request_queues: Dict[str, asyncio.Queue] = defaultdict(asyncio.Queue)

# Use a set to track which names are already queued
names_in_queue = set()
# The actual queue for ordered processing
reconciliation_queue: Dict[str, asyncio.Queue] = defaultdict(asyncio.Queue)
# Locks to prevent race conditions when enqueueing reconciliation requests
reconciliation_locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
# Track consecutive hung member detections: (app_name, member_id) -> consecutive_count
hung_member_tracking: Dict[tuple[str, int], int] = {}

TRUTHY = ("true", "1", "yes", "True", "Yes", "YES")


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


async def request_reconciliation(name, namespace: str = None, **kwargs):
    """Request reconciliation for the KasprApp.

    Enqueues the request only if it's not already in the queue.
    This prevents duplicate processing while preserving order.
    Uses a lock to ensure atomicity of the check-and-add operation.
    """
    async with reconciliation_locks[name]:
        if name not in names_in_queue:
            names_in_queue.add(name)
            await reconciliation_queue[name].put(name)
            
            # Instrument queue operation
            sensor = get_sensor()
            if sensor and namespace:
                queue_depth = reconciliation_queue[name].qsize()
                sensor.on_reconcile_queued(name, name, namespace, queue_depth)


def on_error(error, spec, meta, status, patch, **_):
    """Handle errors during reconciliation."""
    gen = meta.get("generation", 0)
    conds = (status or {}).get("conditions", [])
    conds = upsert_condition(
        conds,
        {
            "type": "Progressing",
            "status": "False",
            "reason": "Error",
            "message": error if error else "Reconcile failed; see events/logs",
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


def _extract_agent_info(resources: List) -> List[Dict]:
    """Extract agent info including subscription-relevant fields.
    
    Args:
        resources: List of agent resource dictionaries
        
    Returns:
        List of agent info dicts with name, hash, topicName, and topicPattern
    """
    result = []
    for resource in resources:
        info = {
            "name": resource["metadata"]["name"],
            "hash": resource.get("status", {}).get("hash", ""),
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


def _extract_table_info(resources: List) -> List[Dict]:
    """Extract table info including subscription-relevant fields.
    
    Args:
        resources: List of table resource dictionaries
        
    Returns:
        List of table info dicts with name, hash, and tableName
    """
    result = []
    for resource in resources:
        info = {
            "name": resource["metadata"]["name"],
            "hash": resource.get("status", {}).get("hash", ""),
        }
        # Extract table name which determines the changelog topic
        table_name = resource.get("spec", {}).get("name")
        if table_name:
            info["tableName"] = table_name
        result.append(info)
    return result


def _extract_basic_info(resources: List) -> List[Dict]:
    """Extract name and hash for resources without subscription impact.
    
    Args:
        resources: List of resource dictionaries
        
    Returns:
        List of basic info dicts with name and hash
    """
    return [
        {
            "name": resource["metadata"]["name"],
            "hash": resource.get("status", {}).get("hash", ""),
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
            
            # Build filtered member object with only desired properties
            filtered_member = {
                "id": member_id,
                "leader": new_member.get("leader"),
                "rebalancing": new_member.get("rebalancing"),
                "recovering": new_member.get("recovering"),
            }
            
            # Preserve or update lastTransitionTime
            if state_changed or "lastTransitionTime" not in current_member:
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

    status_update["rebalanceRequired"] = False

    if not app.static_group_membership_enabled:
        return False

    # Only evaluate subscription changes if fetch was fully successful
    # to avoid false positives from empty lists due to fetch failures
    fetch_succeeded = related_resources.get("success", False)
    if not fetch_succeeded:
        logger.warning(f"Skipping subscription change detection for {name} - resource fetch failed")
        return False

    agents_info = _extract_agent_info(related_resources["agents"])
    webviews_info = _extract_basic_info(related_resources["webviews"])
    tables_info = _extract_table_info(related_resources["tables"])
    tasks_info = _extract_basic_info(related_resources["tasks"])

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
    logger: Logger
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
        
        try:
            logger.info(f"Attempting automatic rebalance for {name} due to subscription changes")
            requested, reason = await app.request_rebalance()

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

        logger.info(f"Automatic rebalance deferred for {name}: {', '.join(reasons)}")


async def fetch_python_packages_status(app: KasprApp, logger: Logger) -> tuple[Optional[Dict], Optional[Dict]]:
    """Fetch Python packages installation status from pods.
    
    Since all pods share the same PVC, we only need to check one available pod.
    
    Args:
        app: KasprApp instance
        logger: Logger instance
        
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
    enabled = cache.enabled if cache and hasattr(cache, 'enabled') else app.DEFAULT_PACKAGES_CACHE_ENABLED
    
    if not enabled:
        return None, None
    
    # Compute packages hash once and reuse throughout
    packages_hash = compute_packages_hash(app.python_packages)
    
    try:
        # List pods for this app
        pods = await app.list_pods(app.core_v1_api, app.namespace, app.labels.kasper_label_selectors().as_dict())
        
        if not pods or not pods.items:
            # No pods yet
            metadata = {
                "hash": packages_hash,
                "cacheMode": "ReadWriteMany" if app.DEFAULT_PACKAGES_ACCESS_MODE == "ReadWriteMany" else "ReadWriteOnce",
            }
            state_info = {
                "state": "Installing",
                "reason": "Installing",
                "message": f"Installing packages (hash: {packages_hash[:8]}...)",
            }
            return metadata, state_info
        
        # Find pod with init container matching the current packages hash
        # This ensures we check the status of the LATEST package installation attempt,
        # not a stale pod with old packages during rolling updates
        target_pod = None
        
        for pod in pods.items:
            # Check if pod has the install-packages init container
            if pod.status and pod.status.init_container_statuses:
                for init_status in pod.status.init_container_statuses:
                    if init_status.name == "install-packages":
                        # Check if this pod's init container has the current packages hash
                        # by examining the PACKAGES_HASH env var
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
        
        # If no pod with current hash found, fall back to any pod with install-packages init container
        # (This can happen briefly during rollout before any pod with new hash exists)
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
                "hash": packages_hash,
                "cacheMode": "ReadWriteMany" if app.DEFAULT_PACKAGES_ACCESS_MODE == "ReadWriteMany" else "ReadWriteOnce",
            }
            state_info = {
                "state": "Installing",
                "reason": "Installing",
                "message": f"Installing packages (hash: {packages_hash[:8]}...)",
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
                "hash": packages_hash,
                "cacheMode": "ReadWriteMany" if app.DEFAULT_PACKAGES_ACCESS_MODE == "ReadWriteMany" else "ReadWriteOnce",
            }
            state_info = {
                "state": "Installing",
                "reason": "Installing",
                "message": f"Installing packages (hash: {packages_hash[:8]}...)",
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
                    "hash": packages_hash,
                    "cacheMode": "ReadWriteMany" if app.DEFAULT_PACKAGES_ACCESS_MODE == "ReadWriteMany" else "ReadWriteOnce",
                }
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
                    "hash": packages_hash,
                    "cacheMode": "ReadWriteMany" if app.DEFAULT_PACKAGES_ACCESS_MODE == "ReadWriteMany" else "ReadWriteOnce",
                }
                state_info = {
                    "state": "Installing",
                    "reason": "Installing",
                    "message": f"Installing packages (hash: {packages_hash[:8]}..., status: {waiting_reason})",
                }
                return metadata, state_info
        
        # Check if init container failed (terminated with non-zero exit code)
        if init_container_status.state and init_container_status.state.terminated:
            if init_container_status.state.terminated.exit_code != 0:
                error_msg = init_container_status.state.terminated.message or "Package installation failed"
                metadata = {
                    "hash": packages_hash,
                    "cacheMode": "ReadWriteMany" if app.DEFAULT_PACKAGES_ACCESS_MODE == "ReadWriteMany" else "ReadWriteOnce",
                }
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
                "hash": packages_hash,
                "cacheMode": "ReadWriteMany" if app.DEFAULT_PACKAGES_ACCESS_MODE == "ReadWriteMany" else "ReadWriteOnce",
            }
            state_info = {
                "state": "Installing",
                "reason": "Installing",
                "message": f"Installing packages (hash: {packages_hash[:8]}...)",
            }
            return metadata, state_info
        
        # Init container completed successfully - try to read marker file
        if init_container_status.state and init_container_status.state.terminated and init_container_status.state.terminated.exit_code == 0:
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
                            "cacheMode": "ReadWriteMany" if app.DEFAULT_PACKAGES_ACCESS_MODE == "ReadWriteMany" else "ReadWriteOnce",
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
                            "cacheMode": "ReadWriteMany" if app.DEFAULT_PACKAGES_ACCESS_MODE == "ReadWriteMany" else "ReadWriteOnce",
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
                        "cacheMode": "ReadWriteMany" if app.DEFAULT_PACKAGES_ACCESS_MODE == "ReadWriteMany" else "ReadWriteOnce",
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
                        "cacheMode": "ReadWriteMany" if app.DEFAULT_PACKAGES_ACCESS_MODE == "ReadWriteMany" else "ReadWriteOnce",
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
                    "cacheMode": "ReadWriteMany" if app.DEFAULT_PACKAGES_ACCESS_MODE == "ReadWriteMany" else "ReadWriteOnce",
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
                    "cacheMode": "ReadWriteMany" if app.DEFAULT_PACKAGES_ACCESS_MODE == "ReadWriteMany" else "ReadWriteOnce",
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
                    "hash": packages_hash,
                    "cacheMode": "ReadWriteMany" if app.DEFAULT_PACKAGES_ACCESS_MODE == "ReadWriteMany" else "ReadWriteOnce",
                    "warnings": [warning_msg],
                }
                state_info = {
                    "state": "Ready",
                    "reason": "PackagesInstalled",
                    "message": "Packages installed (details unavailable)",
                }
                return metadata, state_info
        
        # Fallback
        metadata = {
            "hash": packages_hash,
            "cacheMode": "ReadWriteMany" if app.DEFAULT_PACKAGES_ACCESS_MODE == "ReadWriteMany" else "ReadWriteOnce",
        }
        state_info = {
            "state": "Installing",
            "reason": "Installing",
            "message": f"Installing packages (hash: {packages_hash[:8]}...)",
        }
        return metadata, state_info
        
    except Exception as e:
        logger.error(f"Error fetching Python packages status: {e}")
        metadata = {
            "hash": packages_hash,
        }
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


async def update_status(
    name, spec, meta, status, patch, namespace, annotations, logger: Logger, **kwargs
):
    """Update KasprApp status based on the actual state of the app.
    
    Batches all status updates into a single atomic patch operation to prevent
    conflicts and improve consistency.
    """
    spec_model: KasprAppSpec = KasprAppSpecSchema().load(spec)
    app = KasprApp.from_spec(
        name, APP_KIND, namespace, spec_model, annotations, logger=logger
    )
    _status = status or {}
    try:
        gen = meta.get("generation", 0)
        cur_gen = _status.get("observedGeneration")

        # Build status update dictionary atomically
        status_update = {}
        
        # Always update observedGeneration to match the current generation
        status_update["observedGeneration"] = gen

        # Fetch app status and related resources in parallel
        app_status_task = app.fetch_app_status()
        related_resources_task = fetch_app_related_resources(name, namespace)

        _actual_status, related_resources = await asyncio.gather(
            app_status_task, related_resources_task, return_exceptions=True
        )

        # Handle potential errors from fetch_app_status
        if isinstance(_actual_status, Exception):
            logger.error(f"Failed to fetch app status: {_actual_status}")
            _actual_status = None

        # Handle potential errors from fetch_app_related_resources
        if isinstance(related_resources, Exception):
            logger.error(f"Failed to fetch related resources: {related_resources}")
            related_resources = {
                "agents": [],
                "webviews": [],
                "tables": [],
                "tasks": [],
                "success": False,
            }

        if not _actual_status:
            return

        # Build all status updates atomically before patching
        _update_basic_status_fields(status_update, _status, _actual_status, app, logger)
        _update_linked_resources_status(status_update, _status, app, related_resources, name, logger)
        
        # Update Python packages status if configured
        if app.python_packages:
            packages_metadata, packages_state_info = await fetch_python_packages_status(app, logger)
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
                    logger.info(f"Python packages metadata updated: hash={packages_metadata.get('hash', 'N/A')[:8]}...")
                
                # Create/update PythonPackagesReady condition
                pkg_condition = create_python_packages_condition(packages_state_info, gen)
                if pkg_condition:
                    # Get or initialize conditions
                    conds = status_update.get("conditions", _status.get("conditions", []))
                    conds = upsert_condition(conds, pkg_condition)
                    status_update["conditions"] = conds
                    logger.info(f"PythonPackagesReady condition: status={pkg_condition['status']}, reason={pkg_condition['reason']}")
        else:
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

        # Detect hung rebalancing members
        hung_member_ids = await _detect_hung_members(_status, app, name, namespace, logger)
        
        _update_conditions(status_update, _status, _actual_status, gen, cur_gen, app, hung_member_ids)
        await _attempt_auto_rebalance(status_update, _status, _actual_status, annotations, app, name, namespace, logger)

        # Apply all status updates in a single atomic operation
        patch.status.update(status_update)
        
        # Instrument status update
        sensor = get_sensor()
        if sensor:
            update_fields = list(status_update.keys())
            sensor.on_status_update(name, namespace, update_fields)

        # Terminate hung members after status update
        await _terminate_hung_members(app, hung_member_ids, name, namespace, logger)

    except Exception as e:
        logger.exception(e)


async def reconcile(
    name, namespace, spec, meta, status, patch, annotations, logger: Logger, trigger_source: str = "manual", **kwargs
):
    """Reconcile the KasprApp."""
    # Instrument reconciliation start
    sensor = get_sensor()
    generation = meta.get('generation', 0)
    sensor_state = None
    if sensor:
        sensor_state = sensor.on_reconcile_start(name, name, namespace, generation, trigger_source)
    
    success = True
    error = None
    
    spec_model: KasprAppSpec = KasprAppSpecSchema().load(spec)
    app = KasprApp.from_spec(
        name, APP_KIND, namespace, spec_model, annotations, logger=logger
    )
    if app.reconciliation_paused:
        logger.info("Reconciliation is paused.")
        if sensor:
            sensor.on_reconcile_complete(name, name, namespace, sensor_state, True)
        return
    try:
        logger.debug(f"Reconciling {APP_KIND}/{name} in {namespace} namespace.")
        await app.synchronize()
        logger.debug(f"Reconciled {APP_KIND}/{name} in {namespace} namespace.")
        await update_status(
            name, spec, meta, status, patch, namespace, annotations, logger
        )
    except Exception as e:
        success = False
        error = e
        logger.error(f"Unexpected error during reconcilation: {e}")
        logger.exception(e)
        on_error(e, spec, meta, status, patch, **kwargs)
    finally:
        # Instrument reconciliation complete
        if sensor:
            sensor.on_reconcile_complete(name, name, namespace, sensor_state, success, error)


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
    try:
        await app.create()
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


@kopf.on.delete(kind=APP_KIND)
async def on_delete(name, **kwargs):
    """Handle deletion of KasprApp resources."""
    # Clean up all global state for this resource
    if name in reconciliation_queue:
        del reconciliation_queue[name]
    if name in patch_request_queues:
        del patch_request_queues[name]
    if name in reconciliation_locks:
        del reconciliation_locks[name]
    names_in_queue.discard(name)
    
    # Clean up hung member tracking
    keys_to_remove = [key for key in hung_member_tracking.keys() if key[0] == name]
    for key in keys_to_remove:
        del hung_member_tracking[key]
    names_in_queue.discard(name)


@kopf.timer(APP_KIND, interval=1)
async def patch_resource(name, patch, **kwargs):
    """Update KasprApp status.

    Example usage:
    ```
        # Request to patch annotations
        await patch_request_queues[resource_name].put(
            {
                "field": "metadata.annotations",
                "value": {"kaspr.io/last-applied-agents-hash": "xyz"},
            }
        )
    ```

    Update multiple fields in one pass:
    ```
        # Request to patch annotations
        await patch_request_queues[resource_name].put(
            [
                {
                    "field": "metadata.annotations",
                    "value": {
                        "kaspr.io/last-applied-agents-hash": "xyz"
                    },
                },
                {
                    "field": "status",
                    "value": {
                        "agents": [{"name": "agent-1", "status": "running"}],
                    },
                },
            ]
        )
    ```
    """
    queue = patch_request_queues[name]

    def set_patch(request):
        fields = request["field"].split(".")
        _patch = patch
        for field in fields:
            _patch = getattr(_patch, field)
        _patch.update(request["value"])

    while not queue.empty():
        request = queue.get_nowait()
        if isinstance(request, list):
            for req in request:
                set_patch(req)
        else:
            set_patch(request)


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
    """Process reconciliation requests from the queue.

    Processes each request exactly once, even if it was
    requested multiple times while processing another request.
    """
    if stopped:
        return
    try:
        queue_is_empty = reconciliation_queue[name].empty()
        if not queue_is_empty:
            queue_start_time = time.time()
            reconciliation_queue[name].get_nowait()
            
            # Instrument dequeue with wait time
            sensor = get_sensor()
            if sensor:
                wait_time = time.time() - queue_start_time
                sensor.on_reconcile_dequeued(name, name, namespace, wait_time)
            
            start_time = time.time()
            await reconcile(
                name,
                namespace,
                spec,
                meta,
                status,
                patch,
                annotations,
                logger,
                trigger_source="queue",
                **kwargs,
            )
            execution_time = time.time() - start_time
            logger.info(
                f"Reconciliation for {name} completed in {execution_time:.2f} seconds"
            )
            # Allow this name to be requeued after processing
            names_in_queue.remove(name)
            reconciliation_queue[name].task_done()
    except asyncio.QueueEmpty:
        pass
    except Exception as e:
        logger.error(f"Error processing reconciliation request: {e}")
        # Ensure we don't get stuck on failed requests
        names_in_queue.remove(name)


@kopf.daemon(kind=APP_KIND, initial_delay=5.0)
async def monitor_related_resources(
    stopped,
    name,
    body,
    spec,
    meta,
    labels,
    annotations,
    status,
    namespace,
    patch,
    logger: Logger,
    **kwargs,
):
    """Monitor app's agents, webviews, and tables.

    On every iteration, the handler:
    1. Finds all agents, webviews, etc. related to the app.
    2. Determines if the app needs to be patched with updates to any resource.
    3. (Maybe) Patches the app with updated resources.
    4. Update app annotations & status with changes.
    """

    while not stopped:
        try:
            spec_model: KasprAppSpec = KasprAppSpecSchema().load(spec)
            app = KasprApp.from_spec(
                name, APP_KIND, namespace, spec_model, annotations, logger=logger
            )
            agents: List[KasprAgent] = []
            webviews: List[KasprWebView] = []
            tables: List[KasprTable] = []
            tasks: List[KasprTask] = []

            # Fetch all related resources in parallel
            related_resources = await fetch_app_related_resources(name, namespace)

            for agent in related_resources["agents"]:
                agents.append(
                    KasprAgent.from_spec(
                        agent["metadata"]["name"],
                        KasprAgent.KIND,
                        namespace,
                        KasprAgentSpecSchema().load(agent["spec"]),
                        dict(agent["metadata"]["labels"]),
                    )
                )

            for webview in related_resources["webviews"]:
                webviews.append(
                    KasprWebView.from_spec(
                        webview["metadata"]["name"],
                        KasprWebView.KIND,
                        namespace,
                        KasprWebViewSpecSchema().load(webview["spec"]),
                        dict(webview["metadata"]["labels"]),
                    )
                )

            for table in related_resources["tables"]:
                tables.append(
                    KasprTable.from_spec(
                        table["metadata"]["name"],
                        KasprTable.KIND,
                        namespace,
                        KasprTableSpecSchema().load(table["spec"]),
                        dict(table["metadata"]["labels"]),
                    )
                )

            for task in related_resources["tasks"]:
                tasks.append(
                    KasprTask.from_spec(
                        task["metadata"]["name"],
                        KasprTask.KIND,
                        namespace,
                        KasprTableSpecSchema().load(task["spec"]),
                        dict(task["metadata"]["labels"]),
                    )
                )
            app.with_agents(agents)
            app.with_webviews(webviews)
            app.with_tables(tables)
            app.with_tasks(tasks)
            await app.patch_volume_mounted_resources()
            await asyncio.sleep(10)  # Avoid tight loop

        except asyncio.CancelledError:
            logger.info("Stopping monitoring...")
            break
        except Exception as e:
            logger.error(f"Unexpected error during monitoring: {e}")
            logger.exception(e)
            await asyncio.sleep(10)  # Avoid tight loop on error


@kopf.timer(APP_KIND, initial_delay=5.0, interval=30.0, backoff=10.0)
async def periodic_reconciliation(name, namespace, **kwargs):
    """Reconcile KasprApp resources."""
    await request_reconciliation(name, namespace, **kwargs)


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
    name, body, spec, namespace, annotations, patch, logger: Logger, **kwargs
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
