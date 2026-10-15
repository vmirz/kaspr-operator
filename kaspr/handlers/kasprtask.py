import kopf
import logging
from kaspr.types.schemas import KasprTaskSpecSchema
from kaspr.types.models import KasprTaskSpec
from kaspr.resources import KasprTask
from kaspr.sensors import SensorDelegate
from kaspr.handlers.appcomponent import reconcile_component
from kaspr.handlers.kasprapp import notify_component_event

KIND = "KasprTask"
APP_NOT_FOUND = "AppNotFound"
APP_FOUND = "AppFound"


def get_sensor() -> SensorDelegate:
    """Get sensor from KasprTask class.
    
    Returns:
        Sensor instance or None
    """
    return getattr(KasprTask, 'sensor', None)


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
    """Reconcile KasprTask resources."""
    spec_model: KasprTaskSpec = KasprTaskSpecSchema().load(spec)
    task = KasprTask.from_spec(name, KIND, namespace, spec_model, dict(labels))
    await reconcile_component(
        task,
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
    """Reconcile the task's KasprApp when the task is added, changed or deleted."""
    await notify_component_event(event.get("type"), body, logger)
