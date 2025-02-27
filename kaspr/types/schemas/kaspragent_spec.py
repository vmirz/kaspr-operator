from marshmallow import fields, post_dump
from kaspr.types.base import BaseSchema
from kaspr.types.models import (
    KasprAgentSpec,
    KasprAgentInput,
    KasprAgentInputChannel,
    KasprAgentInputTopic,
    KasprAgentOutput,
    KasprAgentOutputTopic,
    KasprAgentProcessors,
    KasprAgentProcessorsInit,
)
from kaspr.types.schemas.code import CodeSpecSchema
from kaspr.types.schemas.operation import MapOperationSchema, FilterOperationSchema


class KasprAgentInputTopicSchema(BaseSchema):
    __model__ = KasprAgentInputTopic

    name = fields.Str(data_key="name", required=True)
    pattern = fields.Str(data_key="pattern", required=False, load_default=None)
    key_serializer = fields.Str(
        data_key="keySerializer", required=False, load_default=None
    )
    value_serializer = fields.Str(
        data_key="valueSerializer", required=False, load_default=None
    )

    @post_dump
    def map_fields(self, data, **kwargs):
        data["key_serializer"] = data.pop("keySerializer")
        data["value_serializer"] = data.pop("valueSerializer")
        return data


class KasprAgentOutputTopicSchema(BaseSchema):
    __model__ = KasprAgentOutputTopic

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
    def map_fields(self, data, **kwargs):
        data["key_serializer"] = data.pop("keySerializer")
        data["value_serializer"] = data.pop("valueSerializer")
        data["key_selector"] = data.pop("keySelector")
        data["value_selector"] = data.pop("valueSelector")
        data["partition_selector"] = data.pop("partitionSelector")
        data["headers_selector"] = data.pop("headersSelector")
        data["predicate"] = data.pop("predicate")
        return data


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
        fields.Nested(KasprAgentOutputTopicSchema()),
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
