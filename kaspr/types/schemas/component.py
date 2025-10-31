from marshmallow import fields
from kaspr.types.base import BaseSchema
from kaspr.types.models import KasprAppComponents
from kaspr.types.schemas.kaspragent_spec import KasprAgentSpecSchema
from kaspr.types.schemas.kasprwebview_spec import KasprWebViewSpecSchema
from kaspr.types.schemas.kasprtable_spec import KasprTableSpecSchema
from kaspr.types.schemas.kasprtask_spec import KasprTaskSpecSchema


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
    tables = fields.List(
        fields.Nested(KasprTableSpecSchema()),
        data_key="tables",
        required=False,
        load_default=[],
    )
    tasks = fields.List(
        fields.Nested(KasprTaskSpecSchema()),
        data_key="tasks",
        required=False,
        load_default=[],
    )
