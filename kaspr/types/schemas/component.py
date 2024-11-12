from marshmallow import fields
from kaspr.types.base import BaseSchema
from kaspr.types.models import KasprAppComponents
from kaspr.types.schemas.kaspragent_spec import KasprAgentSpecSchema


class KasprAppComponentsSchema(BaseSchema):
    __model__ = KasprAppComponents

    agents = fields.List(
        fields.Nested(KasprAgentSpecSchema()),
        data_key="agents",
        required=False,
        load_default=[],
    )
