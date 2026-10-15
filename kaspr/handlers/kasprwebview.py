import kopf
import logging
from kaspr.types.schemas import KasprWebViewSpecSchema
from kaspr.types.models import KasprWebViewSpec
from kaspr.resources import KasprWebView
from kaspr.sensors import SensorDelegate
from kaspr.handlers.appcomponent import reconcile_component
from kaspr.handlers.kasprapp import notify_component_event

KIND = "KasprWebView"
APP_NOT_FOUND = "AppNotFound"
APP_FOUND = "AppFound"


def get_sensor() -> SensorDelegate:
    """Get sensor from KasprWebView class.
    
    Returns:
        Sensor instance or None
    """
    return getattr(KasprWebView, 'sensor', None)


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
    body, spec, name, namespace, logger, labels, patch, annotations, meta=None, status=None, reason=None, **kwargs
):
    """Reconcile KasprWebView resources."""
    spec_model: KasprWebViewSpec = KasprWebViewSpecSchema().load(spec)
    webview = KasprWebView.from_spec(name, KIND, namespace, spec_model, dict(labels))
    await reconcile_component(
        webview,
        body=body,
        status=status,
        patch=patch,
        namespace=namespace,
        generation=(meta or {}).get("generation", 0),
        reason=reason,
        logger=logger,
    )


@kopf.on.event(kind=KIND)
async def notify_app(event, body, logger, **kwargs):
    """Reconcile the webview's KasprApp when the webview is added, changed or deleted."""
    await notify_component_event(event.get("type"), body, logger)


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
