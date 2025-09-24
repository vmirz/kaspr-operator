import kopf
import logging
import kaspr.handlers.kasprapp as kasprapp
import kaspr.handlers.kaspragent as kaspragent
import kaspr.handlers.kasprwebview as kasprwebview
from kaspr.types.settings import Settings
from kaspr.resources.kasprapp import KasprApp

# Configure Kopf settings
@kopf.on.startup()
def configure_settings(settings: kopf.OperatorSettings, memo: kopf.Memo, **kwargs):

    memo.conf = Settings()
    KasprApp.conf = memo.conf

    # Limit the number of concurrent workers to prevent flooding the API
    settings.batching.worker_limit = 2
    
    # Disable posting events to the Kubernetes API for logging > Warning
    settings.posting.enabled = True
    settings.posting.level = logging.WARNING

__all__ = [
    "kasprapp",
    "kaspragent",
    "kasprwebview",
]