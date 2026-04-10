from marshmallow import fields, post_dump
from kaspr.types.base import BaseSchema
from kaspr.types.models.kasprjoin_spec import KasprJoinSpec
from kaspr.types.schemas.code import CodeSpecSchema
from kaspr.utils.helpers import camel_to_snake


class KasprJoinSpecSchema(BaseSchema):
    __model__ = KasprJoinSpec

    name = fields.String(data_key="name", allow_none=True, load_default=None)
    description = fields.String(
        data_key="description", allow_none=True, load_default=None
    )
    left_table = fields.String(data_key="leftTable", required=True)
    right_table = fields.String(data_key="rightTable", required=True)
    extractor = fields.Nested(
        CodeSpecSchema(), data_key="extractor", required=True
    )
    join_type = fields.String(
        data_key="type", allow_none=True, load_default="inner"
    )
    output_channel = fields.String(
        data_key="outputChannel", allow_none=True, load_default=None
    )

    @post_dump
    def camel_to_snake_dump(self, data, **kwargs):
        """Convert data keys from camelCase to snake_case."""
        return camel_to_snake(data)
