from marshmallow import fields
from kaspr.types.base import BaseSchema
from kaspr.types.models import KasprAppComponents
from kaspr.types.schemas.kaspragent_spec import KasprAgentSpecSchema
from kaspr.types.schemas.kasprwebview_spec import KasprWebViewSpecSchema


class KasprAppComponentsSchema(BaseSchema):
    __model__ = KasprAppComponents

    agents = fields.List(
        fields.Nested(KasprAgentSpecSchema()),
        data_key="agents",
        required=False,
        load_default=[],
    )
    webviews = fields.List(
        fields.Nested(KasprWebViewSpecSchema()),
        data_key="webviews",
        required=False,
        load_default=[],
    )
    
