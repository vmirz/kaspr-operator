from marshmallow import fields, post_dump
from kaspr.utils.helpers import camel_to_snake
from kaspr.types.base import BaseSchema
from kaspr.types.models import TopicOutSpec
from kaspr.types.schemas.code import CodeSpecSchema


class TopicOutSpecSchema(BaseSchema):
    __model__ = TopicOutSpec

    name = fields.Str(data_key="name", required=True)
    ack = fields.Bool(data_key="ack", required=False, load_default=None)
    key_serializer = fields.Str(
        data_key="keySerializer", required=False, load_default=None
    )
    value_serializer = fields.Str(
        data_key="valueSerializer", required=False, load_default=None
    )
    key_selector = fields.Nested(
        CodeSpecSchema(), data_key="keySelector", required=False, load_default=None
    )
    value_selector = fields.Nested(
        CodeSpecSchema(), data_key="valueSelector", required=False, load_default=None
    )
    partition_selector = fields.Nested(
        CodeSpecSchema(),
        data_key="partitionSelector",
        required=False,
        load_default=None,
    )
    headers_selector = fields.Nested(
        CodeSpecSchema(), data_key="headersSelector", required=False, load_default=None
    )
    predicate = fields.Nested(
        CodeSpecSchema(), data_key="predicate", required=False, load_default=None
    )

    @post_dump
    def camelto_to_snake_dump(self, data, **kwargs):
        """Convert data keys from camelCase to snake_case."""
        return camel_to_snake(data)