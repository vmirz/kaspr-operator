from marshmallow import fields, post_dump, validates_schema
from kaspr.utils.helpers import camel_to_snake
from kaspr.types.base import BaseSchema
from kaspr.types.models import (
    KasprAgentSpec,
    KasprAgentInput,
    KasprAgentInputChannel,
    KasprAgentInputTopic,
    KasprAgentOutput,
    KasprAgentProcessors,
    KasprAgentProcessorsInit,
)
from kaspr.types.schemas.topicout import TopicOutSpecSchema
from kaspr.types.schemas.code import CodeSpecSchema
from kaspr.types.schemas.operation import MapOperationSchema, FilterOperationSchema
from kaspr.types.schemas.tableref import TableRefSpecSchema

class KasprAgentInputTopicSchema(BaseSchema):
    __model__ = KasprAgentInputTopic

    name = fields.Str(data_key="name", required=False, load_default=None)
    pattern = fields.Str(data_key="pattern", required=False, load_default=None)
    key_serializer = fields.Str(
        data_key="keySerializer", required=False, load_default=None
    )
    value_serializer = fields.Str(
        data_key="valueSerializer", required=False, load_default=None
    )

    @post_dump
    def camel_to_snake_dump(self, data, **kwargs):
        """Convert data keys from camelCase to snake_case."""
        return camel_to_snake(data)
    
    @validates_schema
    def validate_topic(self, data, **kwargs):
        """Validate that either name or pattern is provided."""
        if not data.get("name") and not data.get("pattern"):
            raise ValueError("Either 'name' or 'pattern' must be provided.")
        if data.get("name") and data.get("pattern"):
            raise ValueError("Only one of 'name' or 'pattern' can be provided.")
        


class KasprAgentChannelSchema(BaseSchema):
    __model__ = KasprAgentInputChannel

    name = fields.Str(data_key="name", required=True)


class KasprAgentInputSchema(BaseSchema):
    __model__ = KasprAgentInput

    topic = fields.Nested(
        KasprAgentInputTopicSchema(),
        data_key="topic",
        allow_none=True,
        load_default=None,
    )
    channel = fields.Nested(
        KasprAgentChannelSchema(),
        data_key="channel",
        allow_none=True,
        load_default=None,
    )


class KasprAgentOutputSchema(BaseSchema):
    __model__ = KasprAgentOutput

    topics = fields.List(
        fields.Nested(TopicOutSpecSchema()),
        data_key="topics",
        allow_none=True,
        load_default=None,
    )


class KasprAgentProcessorsOperationSchema(BaseSchema):
    name = fields.Str(data_key="name", required=True)
    map = fields.Nested(
        MapOperationSchema,
        data_key="map",
        required=False,
        allow_none=True,
        load_default=None,
    )
    filter = fields.Nested(
        FilterOperationSchema,
        data_key="filter",
        required=False,
        allow_none=True,
        load_default=None,
    )
    table_refs = fields.List(
        fields.Nested(
            TableRefSpecSchema(), required=True
        ),
        data_key="tables",
        allow_none=False,
        load_default=list,
    )     


class KasprAgentProcessorsInitSchema(CodeSpecSchema):
    __model__ = KasprAgentProcessorsInit


class KasprAgentProcessorsSchema(BaseSchema):
    __model__ = KasprAgentProcessors

    pipeline = fields.List(fields.Str(), data_key="pipeline", required=True)
    init = fields.Nested(
        KasprAgentProcessorsInitSchema(),
        data_key="init",
        required=False,
        allow_none=True,
        load_default=None,
    )
    operations = fields.List(
        fields.Nested(
            KasprAgentProcessorsOperationSchema(), data_key="operations", required=True
        ),
        required=True,
    )


class KasprAgentSpecSchema(BaseSchema):
    __model__ = KasprAgentSpec

    name = fields.Str(data_key="name", required=False)
    description = fields.Str(data_key="description", allow_none=True, load_default=None)
    input = fields.Nested(KasprAgentInputSchema(), data_key="input", allow_none=True)
    output = fields.Nested(KasprAgentOutputSchema(), data_key="output", allow_none=True)
    processors = fields.Nested(
        KasprAgentProcessorsSchema(),
        data_key="processors",
        allow_none=True,
        load_default=None,
    )
