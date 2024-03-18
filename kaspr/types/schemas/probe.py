from marshmallow import fields
from kaspr.types.base import BaseSchema
from kaspr.types.models.probe import Probe


class ProbeSchema(BaseSchema):
    __model__ = Probe

    failure_threshold = fields.Int(data_key="failureThreshold", load_default=3)
    initial_delay_seconds = fields.Int(data_key="initialDelaySeconds", load_default=15)
    period_seconds = fields.Int(data_key="periodSeconds", load_default=10)
    success_threshold = fields.Int(data_key="successThreshold", load_default=1)
    timeout_seconds = fields.Int(data_key="timeoutSeconds", load_default=5)