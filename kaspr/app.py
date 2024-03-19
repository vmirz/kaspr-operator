import kopf
import kaspr.handlers.kafkamessagescheduler as kafkamessagescheduler

# Disabling Webhook server for now.
# @kopf.on.startup()
# def config(settings: kopf.OperatorSettings, **_):
#     settings.admission.server = kopf.WebhookServer()

__all__ = [
    "kafkamessagescheduler"
]