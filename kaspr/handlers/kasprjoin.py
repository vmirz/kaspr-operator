import asyncio
import kopf
import logging
from collections import defaultdict
from typing import Dict
from benedict import benedict
from kaspr.types.schemas import KasprJoinSpecSchema
from kaspr.types.models import KasprJoinSpec
from kaspr.resources import KasprJoin, KasprApp, KasprTable
from kaspr.sensors import SensorDelegate

KIND = "KasprJoin"
APP_NOT_FOUND = "AppNotFound"
APP_FOUND = "AppFound"
LEFT_TABLE_NOT_FOUND = "LeftTableNotFound"
LEFT_TABLE_FOUND = "LeftTableFound"
RIGHT_TABLE_NOT_FOUND = "RightTableNotFound"
RIGHT_TABLE_FOUND = "RightTableFound"


def get_sensor() -> SensorDelegate:
    """Get sensor from KasprJoin class.

    Returns:
        Sensor instance or None
    """
    return getattr(KasprJoin, "sensor", None)


# Queue of requests to update KasprJoin status
patch_request_queues: Dict[str, asyncio.Queue] = defaultdict(asyncio.Queue)


class TimerLogFilter(logging.Filter):
    def filter(self, record):
        """Timer logs are noisy so we filter them out."""
        return "Timer " not in record.getMessage()


kopf_logger = logging.getLogger("kopf.objects")
kopf_logger.addFilter(TimerLogFilter())


@kopf.on.resume(kind=KIND)
@kopf.on.create(kind=KIND)
@kopf.on.update(kind=KIND)
async def reconciliation(
    body, spec, name, namespace, logger, labels, patch, annotations, **kwargs
):
    """Reconcile KasprJoin resources."""
    spec_model: KasprJoinSpec = KasprJoinSpecSchema().load(spec)
    join_resource = KasprJoin.from_spec(
        name, KIND, namespace, spec_model, dict(labels)
    )
    app = await KasprApp.default().fetch(join_resource.app_name, namespace)
    await join_resource.create()

    # Validate referenced tables exist
    left_table = await KasprTable.default().fetch(spec_model.left_table, namespace)
    right_table = await KasprTable.default().fetch(spec_model.right_table, namespace)

    patch.status.update(
        {
            "app": {
                "name": join_resource.app_name,
                "status": APP_FOUND if app else APP_NOT_FOUND,
            },
            "leftTable": {
                "name": spec_model.left_table,
                "status": LEFT_TABLE_FOUND if left_table else LEFT_TABLE_NOT_FOUND,
            },
            "rightTable": {
                "name": spec_model.right_table,
                "status": RIGHT_TABLE_FOUND if right_table else RIGHT_TABLE_NOT_FOUND,
            },
            "configMap": join_resource.config_map_name,
            "hash": join_resource.hash,
        }
    )

    if app is None:
        kopf.warn(
            body,
            reason=APP_NOT_FOUND,
            message=f"KasprApp `{join_resource.app_name}` does not exist in `{namespace or 'default'}` namespace.",
        )
    else:
        kopf.event(
            body,
            type="Normal",
            reason=APP_FOUND,
            message=f"KasprApp `{join_resource.app_name}` found in `{namespace or 'default'}` namespace.",
        )

    if left_table is None:
        kopf.warn(
            body,
            reason=LEFT_TABLE_NOT_FOUND,
            message=f"KasprTable `{spec_model.left_table}` not found in `{namespace or 'default'}` namespace.",
        )
    else:
        kopf.event(
            body,
            type="Normal",
            reason=LEFT_TABLE_FOUND,
            message=f"KasprTable `{spec_model.left_table}` found in `{namespace or 'default'}` namespace.",
        )

    if right_table is None:
        kopf.warn(
            body,
            reason=RIGHT_TABLE_NOT_FOUND,
            message=f"KasprTable `{spec_model.right_table}` not found in `{namespace or 'default'}` namespace.",
        )
    else:
        kopf.event(
            body,
            type="Normal",
            reason=RIGHT_TABLE_FOUND,
            message=f"KasprTable `{spec_model.right_table}` found in `{namespace or 'default'}` namespace.",
        )


@kopf.timer(KIND, interval=1)
async def patch_resource(name, patch, **kwargs):
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


@kopf.daemon(
    kind=KIND, cancellation_backoff=2.0, cancellation_timeout=5.0, initial_delay=5.0
)
async def monitor_join(
    stopped,
    name,
    body,
    spec,
    meta,
    labels,
    status,
    namespace,
    patch,
    logger: logging.Logger,
    **kwargs,
):
    """Monitor KasprJoin resources for app and table availability."""
    while not stopped:
        try:
            _status = benedict(status, keyattr_dynamic=True)
            _status_updates = benedict(keyattr_dynamic=True)
            spec_model: KasprJoinSpec = KasprJoinSpecSchema().load(spec)
            join_resource = KasprJoin.from_spec(
                name, KIND, namespace, spec_model, dict(labels)
            )

            # Check app existence
            app = await KasprApp.default().fetch(join_resource.app_name, namespace)
            if app is None and _status.app.status == APP_FOUND:
                kopf.warn(
                    body,
                    reason=APP_NOT_FOUND,
                    message=f"KasprApp `{join_resource.app_name}` does not exist in `{namespace or 'default'}` namespace.",
                )
                _status_updates.app.status = APP_NOT_FOUND
            elif app and _status.app.status == APP_NOT_FOUND:
                kopf.event(
                    body,
                    type="Normal",
                    reason=APP_FOUND,
                    message=f"KasprApp `{join_resource.app_name}` found in `{namespace or 'default'}` namespace.",
                )
                _status_updates.app.status = APP_FOUND

            # Check left table existence
            left_table = await KasprTable.default().fetch(
                spec_model.left_table, namespace
            )
            if (
                left_table is None
                and _status.get("leftTable", {}).get("status") == LEFT_TABLE_FOUND
            ):
                kopf.warn(
                    body,
                    reason=LEFT_TABLE_NOT_FOUND,
                    message=f"KasprTable `{spec_model.left_table}` not found in `{namespace or 'default'}` namespace.",
                )
                _status_updates.leftTable.status = LEFT_TABLE_NOT_FOUND
            elif (
                left_table
                and _status.get("leftTable", {}).get("status") == LEFT_TABLE_NOT_FOUND
            ):
                kopf.event(
                    body,
                    type="Normal",
                    reason=LEFT_TABLE_FOUND,
                    message=f"KasprTable `{spec_model.left_table}` found in `{namespace or 'default'}` namespace.",
                )
                _status_updates.leftTable.status = LEFT_TABLE_FOUND

            # Check right table existence
            right_table = await KasprTable.default().fetch(
                spec_model.right_table, namespace
            )
            if (
                right_table is None
                and _status.get("rightTable", {}).get("status") == RIGHT_TABLE_FOUND
            ):
                kopf.warn(
                    body,
                    reason=RIGHT_TABLE_NOT_FOUND,
                    message=f"KasprTable `{spec_model.right_table}` not found in `{namespace or 'default'}` namespace.",
                )
                _status_updates.rightTable.status = RIGHT_TABLE_NOT_FOUND
            elif (
                right_table
                and _status.get("rightTable", {}).get("status")
                == RIGHT_TABLE_NOT_FOUND
            ):
                kopf.event(
                    body,
                    type="Normal",
                    reason=RIGHT_TABLE_FOUND,
                    message=f"KasprTable `{spec_model.right_table}` found in `{namespace or 'default'}` namespace.",
                )
                _status_updates.rightTable.status = RIGHT_TABLE_FOUND

            if _status_updates:
                await patch_request_queues[name].put(
                    [
                        {"field": "status", "value": _status_updates},
                    ]
                )

            await asyncio.sleep(10)
        except asyncio.CancelledError:
            logger.info("Monitoring stopped.")
            break
        except Exception as e:
            logger.error(f"Unexpected error during monitoring: {e}")
            logger.exception(e)


@kopf.timer(KIND, initial_delay=5.0, interval=60.0, backoff=10.0)
async def reconcile(name, spec, namespace, labels, logger: logging.Logger, **kwargs):
    """Full sync."""
    sensor = get_sensor()
    success = True
    error = None

    try:
        spec_model: KasprJoinSpec = KasprJoinSpecSchema().load(spec)
        join_resource = KasprJoin.from_spec(
            name, KIND, namespace, spec_model, dict(labels)
        )

        sensor_state = sensor.on_reconcile_start(
            join_resource.app_name, name, namespace, 0, "timer"
        )

        logger.debug(f"Reconciling {KIND}/{name} in {namespace} namespace.")
        await join_resource.synchronize()
        logger.debug(f"Reconciled {KIND}/{name} in {namespace} namespace.")
    except Exception as e:
        success = False
        error = e
        logger.error(f"Unexpected error during reconciliation: {e}")
        logger.exception(e)
    finally:
        sensor.on_reconcile_complete(
            join_resource.app_name, name, namespace, sensor_state, success, error
        )
