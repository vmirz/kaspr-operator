import asyncio
import kopf
import logging
from collections import defaultdict
from typing import Dict
from benedict import benedict
from kaspr.types.schemas import KasprTableSpecSchema
from kaspr.types.models import KasprTableSpec
from kaspr.resources import KasprTable, KasprApp
from kaspr.utils.helpers import utc_now

KIND = "KasprTable"
APP_NOT_FOUND = "AppNotFound"
APP_FOUND = "AppFound"

# Queue of requests to update KasprTable status
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
def reconciliation(
    body, spec, name, namespace, logger, labels, patch, annotations, **kwargs
):
    """Reconcile KasprTable resources."""
    spec_model: KasprTableSpec = KasprTableSpecSchema().load(spec)
    table = KasprTable.from_spec(name, KIND, namespace, spec_model, dict(labels))
    app = KasprApp.default().fetch(table.app_name, namespace)
    table.create()
    # fetch the table's app and update it's status.
    patch.status.update(
        {
            "app": {
                "name": table.app_name,
                "status": APP_FOUND if app else APP_NOT_FOUND,
            },
            "configMap": table.config_map_name,
            "hash": table.hash,
            "lastUpdateTime": utc_now().isoformat(),
        }
    )
    if app is None:
        kopf.warn(
            body,
            reason=APP_NOT_FOUND,
            message=f"KasprApp `{table.app_name}` does not exist in `{namespace or 'default'}` namespace.",
        )
    else:
        kopf.event(
            body,
            type="Normal",
            reason=APP_FOUND,
            message=f"KasprApp `{table.app_name}` found in `{namespace or 'default'}` namespace.",
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
async def monitor_table(
    stopped, name, body, spec, meta, labels, status, namespace, patch, logger, **kwargs
):
    """Monitor table resources for status updates."""
    try:
        while not stopped:
            _status = benedict(status, keyattr_dynamic=True)
            _status_updates = benedict(keyattr_dynamic=True)
            spec_model: KasprTableSpec = KasprTableSpecSchema().load(spec)
            table = KasprTable.from_spec(
                name, KIND, namespace, spec_model, dict(labels)
            )
            # Warn if the table's app does not exists.
            app = KasprApp.default().fetch(table.app_name, namespace)
            if app is None and _status.app.status == APP_FOUND:
                kopf.warn(
                    body,
                    reason=APP_NOT_FOUND,
                    message=f"KasprApp `{table.app_name}` does not exist in `{namespace or 'default'}` namespace.",
                )
                _status_updates.app.status = APP_NOT_FOUND
            elif app and _status.app.status == APP_NOT_FOUND:
                kopf.event(
                    body,
                    type="Normal",
                    reason=APP_FOUND,
                    message=f"KasprApp `{table.app_name}` found in `{namespace or 'default'}` namespace.",
                )
                _status_updates.app.status = APP_FOUND

            if _status_updates:
                await patch_request_queues[name].put(
                    [
                        {"field": "status", "value": _status_updates},
                        {
                            "field": "status",
                            "value": {"lastUpdateTime": utc_now().isoformat()},
                        },
                    ]
                )

            await asyncio.sleep(10)
    except asyncio.CancelledError:
        print("We are done. Bye.")


@kopf.timer(KIND, initial_delay=5.0, idle=30.0)
async def reconcile(name, spec, namespace, labels, **kwargs):
    """Full sync."""
    spec_model: KasprTableSpec = KasprTableSpecSchema().load(spec)
    table = KasprTable.from_spec(name, KIND, namespace, spec_model, dict(labels))
    table.synchronize()


# @kopf.on.validate(kind=KIND)
# def includes_valid_app(spec, **_):
#     raise kopf.AdmissionError("Missing required label `kaspr.io/app`", code=429)

# @kopf.on.delete(kind=KIND)
# def on_delete(name, namespace, logger, **kwargs):
#     """Delete KasprAgent resources."""
#     agent = KasprAgent(name, KIND, namespace)
#     agent.delete()

# @kopf.daemon(KIND, cancellation_timeout=5.0)
# async def monitor_kex(**kwargs):
#     try:
#         while True:
#             print("Monitoring KEX")
#             await asyncio.sleep(10)
#     except asyncio.CancelledError:
#         print("We are done. Bye.")
