from marshmallow import fields
from kaspr.types.base import BaseSchema
from kaspr.types.models.vertical_pod_autoscaler import VerticalPodAutoscalerSpec


class VerticalPodAutoscalerSpecSchema(BaseSchema):
    """Vertical autoscaling settings of a KasprApp.

    Values are validated by the CRD. They are not validated again here: a value the
    installed Vertical Pod Autoscaler rejects is reported in the app's status, and
    must not keep the rest of the app from being reconciled.
    """

    __model__ = VerticalPodAutoscalerSpec

    DEFAULT_UPDATE_MODE = "InPlaceOrRecreate"
    DEFAULT_CONTROLLED_RESOURCES = ("cpu",)
    DEFAULT_CONTROLLED_VALUES = "RequestsOnly"

    enabled = fields.Boolean(data_key="enabled", allow_none=True, load_default=False)
    update_mode = fields.String(
        data_key="updateMode", allow_none=True, load_default=DEFAULT_UPDATE_MODE
    )
    min_replicas = fields.Integer(data_key="minReplicas", allow_none=True, load_default=None)
    controlled_resources = fields.List(
        fields.String(),
        data_key="controlledResources",
        allow_none=True,
        load_default=lambda: list(VerticalPodAutoscalerSpecSchema.DEFAULT_CONTROLLED_RESOURCES),
    )
    controlled_values = fields.String(
        data_key="controlledValues", allow_none=True, load_default=DEFAULT_CONTROLLED_VALUES
    )
    min_allowed = fields.Dict(data_key="minAllowed", allow_none=True, load_default=None)
    max_allowed = fields.Dict(data_key="maxAllowed", allow_none=True, load_default=None)
