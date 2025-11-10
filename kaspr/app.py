import kopf
import logging
import kaspr.handlers.kasprapp as kasprapp
import kaspr.handlers.kaspragent as kaspragent
import kaspr.handlers.kasprwebview as kasprwebview
from kaspr.types.settings import Settings
from kaspr.resources.kasprapp import KasprApp
from kaspr.resources.appcomponent import BaseAppComponent
from kaspr.web import KasprWebClient
from kubernetes_asyncio import config
from kubernetes_asyncio.client.api_client import ApiClient


# Configure Kopf settings
@kopf.on.startup()
async def setup(
    settings: kopf.OperatorSettings, memo: kopf.Memo, logger: logging.Logger, **kwargs
):
    await config.load_kube_config()

    memo.conf = Settings()
    KasprApp.conf = memo.conf
    KasprApp.web_client = KasprWebClient()

    # Create a shared ApiClient for all resources to prevent connection leaks
    shared_client = ApiClient()
    KasprApp.shared_api_client = shared_client
    BaseAppComponent.shared_api_client = shared_client
    logger.info("Shared Kubernetes API client initialized")

    if not KasprApp.conf.client_status_check_enabled:
        logger.warning(
            "Member status checks are disabled as per configuration. "
            "Some functionality will be limited."
        )

    # Limit the number of concurrent workers to prevent flooding the API
    settings.batching.worker_limit = 2

    # Disable posting events to the Kubernetes API for logging > Warning
    settings.posting.enabled = True
    settings.posting.level = logging.WARNING


@kopf.on.cleanup()
async def cleanup(logger: logging.Logger, **kwargs):
    """Cleanup handler for operator shutdown."""
    logger.info("Shutting down operator...")

    # Close the shared API client
    if hasattr(KasprApp, "shared_api_client") and KasprApp.shared_api_client:
        await KasprApp.shared_api_client.close()
        logger.info("Shared API client closed")

    # Close the web client
    if hasattr(KasprApp, "web_client") and KasprApp.web_client:
        await KasprApp.web_client.close()
        logger.info("Web client closed")

    logger.info("Operator shutdown complete")


__all__ = [
    "kasprapp",
    "kaspragent",
    "kasprwebview",
]
