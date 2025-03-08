import kopf
import logging
import kaspr.handlers.kasprscheduler as kasprscheduler

# Configure Kopf settings
@kopf.on.startup()
def configure_settings(settings: kopf.OperatorSettings, **kwargs):
    # Limit the number of concurrent workers to prevent flooding the API
    settings.batching.worker_limit = 1
    
    # Disable posting events to the Kubernetes API for logging > Warning
    settings.posting.enabled = True
    settings.posting.level = logging.WARNING

__all__ = [
    "kasprscheduler"
]