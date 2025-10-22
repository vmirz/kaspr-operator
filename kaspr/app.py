import kopf
import logging
import kaspr.handlers.kasprapp as kasprapp
import kaspr.handlers.kaspragent as kaspragent
import kaspr.handlers.kasprwebview as kasprwebview
from kaspr.types.settings import Settings
from kaspr.resources.kasprapp import KasprApp
from kaspr.web import KasprWebClient

# Configure Kopf settings
@kopf.on.startup()
async def setup(settings: kopf.OperatorSettings, memo: kopf.Memo, logger: logging.Logger, **kwargs):

    memo.conf = Settings()  
    KasprApp.conf = memo.conf
    KasprApp.web_client = KasprWebClient()

    if not KasprApp.conf.client_status_check_enabled:
        logger.warning("Member status checks are disabled as per configuration. Some functionality may be limited.")


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