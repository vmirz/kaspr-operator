import asyncio
import kopf
import time
from logging import Logger
from collections import defaultdict
from typing import List, Dict
from kubernetes_asyncio.client import ApiException
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
from kaspr.utils.helpers import upsert_condition, deep_compare_dict
from kaspr.utils.errors import convert_api_exception

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


async def fetch_app_related_resources(name: str, namespace: str) -> Dict[str, List]:
    """Fetch all resources related to a KasprApp in parallel.
    
    Args:
        name: The name of the KasprApp
        namespace: The namespace of the KasprApp
        
    Returns:
        Dictionary with keys: 'agents', 'webviews', 'tables', 'tasks'
        Each containing a list of resource items
    """
    agent_task, webview_task, table_task, task_task = await asyncio.gather(
        KasprAgent.default().search(namespace, apps=[name]),
        KasprWebView.default().search(namespace, apps=[name]),
        KasprTable.default().search(namespace, apps=[name]),
        KasprTask.default().search(namespace, apps=[name]),
        return_exceptions=True
    )
    
    # Handle potential errors and extract items
    def extract_items(result, resource_type: str):
        if isinstance(result, Exception):
            # Log error but return empty list to allow partial results
            return []
        return result.get("items", []) if result else []
    
    return {
        "agents": extract_items(agent_task, "agents"),
        "webviews": extract_items(webview_task, "webviews"),
        "tables": extract_items(table_task, "tables"),
        "tasks": extract_items(task_task, "tasks"),
    }


async def request_reconciliation(name, **kwargs):
    """Request reconciliation for the KasprApp.
    
    Enqueues the request only if it's not already in the queue.
    This prevents duplicate processing while preserving order.
    """
    if name not in names_in_queue:
        names_in_queue.add(name)
        await reconciliation_queue[name].put(name)

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


async def update_status(
    name, spec, meta, status, patch, namespace, annotations, logger: Logger, **kwargs
):
    """Update KasprApp status based on the actual state of the app."""
    spec_model: KasprAppSpec = KasprAppSpecSchema().load(spec)
    app = KasprApp.from_spec(name, APP_KIND, namespace, spec_model, annotations, logger=logger)
    _status = status or {}    
    try:        
        gen = meta.get("generation", 0)
        cur_gen = _status.get("observedGeneration")

        # Always update observedGeneration to match the current generation
        patch.status["observedGeneration"] = gen

        # Fetch app status and related resources in parallel
        app_status_task = app.fetch_app_status()
        related_resources_task = fetch_app_related_resources(name, namespace)
        
        _actual_status, related_resources = await asyncio.gather(
            app_status_task, 
            related_resources_task,
            return_exceptions=True
        )
        
        # Handle potential errors from fetch_app_status
        if isinstance(_actual_status, Exception):
            logger.error(f"Failed to fetch app status: {_actual_status}")
            _actual_status = None
        
        # Handle potential errors from fetch_app_related_resources
        if isinstance(related_resources, Exception):
            logger.error(f"Failed to fetch related resources: {related_resources}")
            related_resources = {"agents": [], "webviews": [], "tables": [], "tasks": []}
        
        if not _actual_status:
            return

        # Always update kasprVersion if changed
        if _actual_status.get("kasprVersion") and _actual_status["kasprVersion"] != _status.get("kasprVersion"):
            patch.status["kasprVersion"] = _actual_status["kasprVersion"]

        if _actual_status.get("availableMembers") is not None and _actual_status.get("desiredMembers") is not None:
            availableMembers = f"{_actual_status['availableMembers']}/{_actual_status['desiredMembers']}"
            if availableMembers != _status.get("availableMembers"):
                patch.status["availableMembers"] = availableMembers

        # Update members status if changed (using deep comparison for nested data)
        if _actual_status.get("members") is not None and not deep_compare_dict(_actual_status["members"], _status.get("members")):
            patch.status["members"] = _actual_status["members"]

        if _actual_status.get("rolloutInProgress") is not None and _actual_status.get("rolloutInProgress") != _status.get("rolloutInProgress"):
            patch.status["rolloutInProgress"] = _actual_status["rolloutInProgress"]

        # Update related resources status in a specific order under "linkedResources" field
        # Extract resource name and hash from each resource
        def extract_resource_info(resources):
            """Extract name and hash from resource list."""
            return [
                {
                    "name": resource["metadata"]["name"],
                    "hash": resource.get("status", {}).get("hash", "")
                }
                for resource in resources
            ]
        
        agents_info = extract_resource_info(related_resources["agents"])
        webviews_info = extract_resource_info(related_resources["webviews"])
        tables_info = extract_resource_info(related_resources["tables"])
        tasks_info = extract_resource_info(related_resources["tasks"])
        
        # Get current resources from status
        current_resources = _status.get("linkedResources", {})
        
        # Check if any resources changed (using deep comparison for nested structures)
        resources_changed = (
            not deep_compare_dict({"agents": agents_info}, {"agents": current_resources.get("agents", [])}) or
            not deep_compare_dict({"webviews": webviews_info}, {"webviews": current_resources.get("webviews", [])}) or
            not deep_compare_dict({"tables": tables_info}, {"tables": current_resources.get("tables", [])}) or
            not deep_compare_dict({"tasks": tasks_info}, {"tasks": current_resources.get("tasks", [])})
        )
        
        # Update all resources together to maintain order
        if resources_changed:
            patch.status["linkedResources"] = {
                "agents": agents_info,
                "webviews": webviews_info,
                "tables": tables_info,
                "tasks": tasks_info,
            }

        conds = _status.get("conditions", [])

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

        patch.status["conditions"] = conds

    except Exception as e:
        logger.exception(e)


async def reconcile(name, namespace, spec, meta, status, patch, annotations, logger: Logger, **kwargs):
    """Reconcile the KasprApp."""
    spec_model: KasprAppSpec = KasprAppSpecSchema().load(spec)
    app = KasprApp.from_spec(name, APP_KIND, namespace, spec_model, annotations, logger=logger)
    if app.reconciliation_paused:
        logger.info("Reconciliation is paused.")
        return
    try:
        logger.debug(f"Reconciling {APP_KIND}/{name} in {namespace} namespace.")
        await app.synchronize()
        logger.debug(f"Reconciled {APP_KIND}/{name} in {namespace} namespace.")
        await update_status(name, spec, meta, status, patch, namespace, annotations, logger)
    except Exception as e:
        logger.error(f"Unexpected error during reconcilation: {e}")
        logger.exception(e)
        on_error(e, spec, meta, status, patch, **kwargs)

@kopf.on.resume(kind=APP_KIND)
@kopf.on.create(kind=APP_KIND)
async def on_create(
    spec, name, meta, status, patch, namespace, annotations, logger: Logger, **kwargs
):
    """Creates KasprApp resources."""
    spec_model: KasprAppSpec = KasprAppSpecSchema().load(spec)
    app = KasprApp.from_spec(name, APP_KIND, namespace, spec_model, annotations, logger=logger)
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
    app = KasprApp.from_spec(name, APP_KIND, namespace, spec_model, annotations, logger=logger)
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
    app = KasprApp.from_spec(name, APP_KIND, namespace, spec_model, annotations, logger=logger)
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
    app = KasprApp.from_spec(name, APP_KIND, namespace, spec_model, annotations, logger=logger)
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
    app = KasprApp.from_spec(name, APP_KIND, namespace, spec_model, annotations, logger=logger)
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
    app = KasprApp.from_spec(name, APP_KIND, namespace, spec_model, annotations, logger=logger)
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
    app = KasprApp.from_spec(name, APP_KIND, namespace, spec_model, annotations, logger=logger)
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
    app = KasprApp.from_spec(name, APP_KIND, namespace, spec_model, annotations, logger=logger)
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
    app = KasprApp.from_spec(name, APP_KIND, namespace, spec_model, annotations, logger=logger)
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
    app = KasprApp.from_spec(name, APP_KIND, namespace, spec_model, annotations, logger=logger)
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
    app = KasprApp.from_spec(name, APP_KIND, namespace, spec_model, annotations, logger=logger)
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
    app = KasprApp.from_spec(name, APP_KIND, namespace, spec_model, annotations, logger=logger)
    if app.reconciliation_paused:
        logger.info("Reconciliation is paused.")
        return
    try:
        await app.patch_settings()
    except Exception as e:
        logger.error(f"Failed to patch settings for KasprApp: {e}")
        on_error(e, spec, meta, status, patch, **kwargs)
        raise


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
    # remove app name from reconciliation queue
    if name in reconciliation_queue:
        del reconciliation_queue[name]

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
async def process_reconciliation_requests(name, namespace, spec, meta, status, patch, annotations, logger: Logger, stopped, **kwargs):
    """Process reconciliation requests from the queue.
    
    Processes each request exactly once, even if it was 
    requested multiple times while processing another request.
    """
    if stopped:
        return
    try:
        queue_is_empty = reconciliation_queue[name].empty()
        if not queue_is_empty:
            reconciliation_queue[name].get_nowait()
            start_time = time.time()
            await reconcile(name, namespace, spec, meta, status, patch, annotations, logger, **kwargs)
            execution_time = time.time() - start_time
            logger.debug(f"Reconcile for {name} completed in {execution_time:.2f} seconds")
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
            app = KasprApp.from_spec(name, APP_KIND, namespace, spec_model, annotations, logger=logger)
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
            # current_agents_hash, desired_agents_hash = (
            #     annotations.get("kaspr.io/last-applied-agents-hash"),
            #     app.agents_hash,
            # )
            # current_webviews_hash, desired_webviews_hash = (
            #     annotations.get("kaspr.io/last-applied-webviews-hash"),
            #     app.webviews_hash,
            # )
            # current_tables_hash, desired_tables_hash = (
            #     annotations.get("kaspr.io/last-applied-tables-hash"),
            #     app.tables_hash,
            # )
            await app.patch_volume_mounted_resources()
            # TODO: Update latest applied generation # in status
            # patch_requests = [
            #     {
            #         "field": "metadata.labels",
            #         "value": {app.KASPR_APP_NAME_LABEL: name},
            #     }
            # ]
            # if current_agents_hash != desired_agents_hash:
            #     patch_requests.extend(
            #         [
            #             {
            #                 "field": "metadata.annotations",
            #                 "value": {
            #                     "kaspr.io/last-applied-agents-hash": desired_agents_hash
            #                 },
            #             },
            #             {
            #                 "field": "status",
            #                 "value": {
            #                     "version": str(app.version),
            #                     "agents": {
            #                         "registered": app.agents_status(),
            #                         "lastTransitionTime": utc_now().isoformat(),
            #                         "hash": app.agents_hash,
            #                     },
            #                 },
            #             },
            #         ]
            #     )
            #     kopf.event(
            #         body,
            #         type="Normal",
            #         reason=AGENTS_UPDATED,
            #         message=f"Agents were updated for `{name}` in `{namespace or 'default'}` namespace.",
            #     )

            # if current_webviews_hash != desired_webviews_hash:
            #     patch_requests.extend(
            #         [
            #             {
            #                 "field": "metadata.annotations",
            #                 "value": {
            #                     "kaspr.io/last-applied-webviews-hash": desired_webviews_hash
            #                 },
            #             },
            #             {
            #                 "field": "status",
            #                 "value": {
            #                     "version": str(app.version),
            #                     "webviews": {
            #                         "registered": app.webviews_status(),
            #                         "lastTransitionTime": utc_now().isoformat(),
            #                         "hash": app.webviews_hash,
            #                     },
            #                 },
            #             },
            #         ]
            #     )
            #     kopf.event(
            #         body,
            #         type="Normal",
            #         reason=WEBVIEWS_UPDATED,
            #         message=f"Webviews were updated for `{name}` in `{namespace or 'default'}` namespace.",
            #     )

            # if current_tables_hash != desired_tables_hash:
            #     patch_requests.extend(
            #         [
            #             {
            #                 "field": "metadata.annotations",
            #                 "value": {
            #                     "kaspr.io/last-applied-tables-hash": desired_tables_hash
            #                 },
            #             },
            #             {
            #                 "field": "status",
            #                 "value": {
            #                     "version": str(app.version),
            #                     "tables": {
            #                         "registered": app.tables_status(),
            #                         "lastTransitionTime": utc_now().isoformat(),
            #                         "hash": app.tables_hash,
            #                     },
            #                 },
            #             },
            #         ]
            #     )
            #     kopf.event(
            #         body,
            #         type="Normal",
            #         reason=TABLES_UPDATED,
            #         message=f"Tables were updated for `{name}` in `{namespace or 'default'}` namespace.",
            #     )

            # await patch_request_queues[name].put(patch_requests)
            await asyncio.sleep(10)  # Avoid tight loop

        except asyncio.CancelledError:
            logger.info("Stopping monitoring...")
            break
        except Exception as e:
            logger.error(f"Unexpected error during monitoring: {e}")
            logger.exception(e)
            await asyncio.sleep(10)  # Avoid tight loop on error


@kopf.timer(APP_KIND, initial_delay=5.0, interval=30.0, backoff=10.0)
async def periodic_reconciliation(name, **kwargs):
    """Reconcile KasprApp resources."""
    await request_reconciliation(name, **kwargs)

@kopf.on.field(kind=APP_KIND, field='metadata.annotations', annotations={'kaspr.io/pause-reconciliation': kopf.PRESENT})
async def on_reconciliation_paused(name, diff, spec, namespace, logger: Logger, **kwargs):
    """Handle reconciliation paused event."""
    await request_reconciliation(name, **kwargs)

@kopf.on.field(kind=APP_KIND, field='metadata.annotations', annotations={'kaspr.io/pause-reconciliation': kopf.ABSENT})
async def on_reconciliation_resumed(name, diff, spec, namespace, logger: Logger, **kwargs):
    """Handle reconciliation resumed event."""
    await request_reconciliation(name, **kwargs)

@kopf.on.field(kind=APP_KIND, field='metadata.annotations', annotations={'kaspr.io/rebalance': kopf.PRESENT})
async def on_rebalance_requested(
    name, body, spec, namespace, annotations, patch, logger: Logger, **kwargs
):
    """Handle ad-hoc rebalance request via annotation.
    
    When kaspr.io/rebalance annotation is added, this handler:
    1. Attempts to rebalance the cluster
    2. Removes the annotation regardless of success/failure
    3. Posts an event indicating the result
    """
    spec_model: KasprAppSpec = KasprAppSpecSchema().load(spec)
    app = KasprApp.from_spec(name, APP_KIND, namespace, spec_model, annotations, logger=logger)
    
    try:
        logger.info(f"Rebalance requested for {name} via annotation")
        
        # Attempt rebalance
        await app.request_rebalance()
        
        # Post success event
        kopf.event(
            body,
            type="Normal",
            reason="RebalanceRequested",
            message=f"Rebalance successfully requested for '{name}' in '{namespace}' namespace.",
        )
        
    except Exception as e:
        logger.error(f"Rebalance request failed for {name}: {e}")
        
        # Post failure event
        kopf.event(
            body,
            type="Warning",
            reason="RebalanceFailed",
            message=f"Rebalance request failed for '{name}' in '{namespace}' namespace: {e}",
        )
    
    finally:
        # Always remove the annotation to prevent repeated attempts
        if "kaspr.io/rebalance" in (annotations or {}):
            # Remove the annotation by setting it to None
            patch.metadata.annotations["kaspr.io/rebalance"] = None
            logger.info(f"Removed kaspr.io/rebalance annotation from {name}")