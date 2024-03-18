import kopf
import kaspr.handlers.kafkamessagescheduler as kafkamessagescheduler

@kopf.on.startup()
def config(settings: kopf.OperatorSettings, **_):
    settings.admission.server = kopf.WebhookServer()
    
__all__ = [
    "kafkamessagescheduler"
]