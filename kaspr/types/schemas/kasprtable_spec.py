from marshmallow import fields
from kaspr.types.base import BaseSchema
from kaspr.types.models import (
    KasprTableWindowTumblingSpec,
    KasprTableWindowHoppingSpec,
    KasprTableWindowSpec,
    KasprTableSpec,
)
from kaspr.types.schemas.code import CodeSpecSchema


class KasprTableWindowTumblingSpecSchema(BaseSchema):
    __model__ = KasprTableWindowTumblingSpec
    size = fields.Int(data_key="size", allow_none=False, required=True)
    expires = fields.Str(data_key="expires", allow_none=True, load_default=None)


class KasprTableWindowHoppingSpecSchema(BaseSchema):
    __model__ = KasprTableWindowHoppingSpec

    size = fields.Int(data_key="size", allow_none=False, required=True)
    step = fields.Int(data_key="step", allow_none=False, required=True)
    expires = fields.Str(data_key="expires", allow_none=True, load_default=None)


class KasprTableWindowSpecSchema(BaseSchema):
    __model__ = KasprTableWindowSpec

    tumbling = fields.Nested(
        KasprTableWindowTumblingSpecSchema(),
        data_key="tumbling",
        allow_none=True,
        load_default=None,
    )
    hopping = fields.Nested(
        KasprTableWindowHoppingSpecSchema(),
        data_key="hopping",
        allow_none=True,
        load_default=None,
    )
    relative_to = fields.Str(data_key="relativeTo", allow_none=True, load_default=None)
    relative_to_field_selector = fields.Nested(
        CodeSpecSchema(),
        data_key="relativeToFieldSelector",
        allow_none=True,
        load_default=None,
    )


class KasprTableSpecSchema(BaseSchema):
    __model__ = KasprTableSpec

    name = fields.Str(data_key="name", allow_none=False, required=True)
    description = fields.Str(data_key="description", allow_none=True, load_default=None)
    is_global = fields.Bool(data_key="global", allow_none=True, load_default=False)
    default_selector = fields.Nested(
        CodeSpecSchema(), data_key="defaultSelector", allow_none=True, load_default=None
    )
    key_serializer = fields.Str(
        data_key="keySerializer", required=False, load_default=None
    )
    value_serializer = fields.Str(
        data_key="valueSerializer", required=False, load_default=None
    )
    partitions = fields.Int(data_key="partitions", required=False, load_default=None)
    extra_topic_configs = fields.Mapping(
        keys=fields.Str(required=True),
        data_key="extraTopicConfigs",
        allow_none=True,
        load_default=dict,
    )
    window = fields.Nested(
        KasprTableWindowSpecSchema(), data_key="window", allow_none=True, load_default=None
    )
