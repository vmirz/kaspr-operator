from marshmallow import fields
from kaspr.types.base import BaseSchema
from kaspr.types.models import (
    KasprAgentSpec,
    KasprAgentOutput,
    KasprAgentInput,
    KasprAgentChannel,
    KasprAgentTopic,
)


class KasprAgentTopicSchema(BaseSchema):
    __model__ = KasprAgentTopic

    name = fields.Str(data_key="name", required=True)
    partitions = fields.Int(data_key="partitions", load_default=None)


class KasprAgentChannelSchema(BaseSchema):
    __model__ = KasprAgentChannel

    name = fields.Str(data_key="name", required=True)


class KasprAgentInputSchema(BaseSchema):
    __model__ = KasprAgentInput

    topic = fields.Nested(
        KasprAgentTopicSchema(), data_key="topic", allow_none=True, load_default=None
    )
    channel = fields.Nested(
        KasprAgentChannelSchema(),
        data_key="channel",
        allow_none=True,
        load_default=None,
    )


class KasprAgentOutputSchema(BaseSchema):
    __model__ = KasprAgentOutput

    topic = fields.Nested(
        KasprAgentTopicSchema(), data_key="topic", allow_none=True, load_default=None
    )
    channel = fields.Nested(
        KasprAgentChannelSchema(),
        data_key="channel",
        allow_none=True,
        load_default=None,
    )


class KasprAgentSpecSchema(BaseSchema):
    __model__ = KasprAgentSpec

    description = fields.Str(data_key="description", allow_none=True, load_default=None)
    inputs = fields.List(
        fields.Nested(KasprAgentInputSchema(), data_key="inputs", allow_none=True),
        required=True,
    )
    outputs = fields.List(
        fields.Nested(KasprAgentOutputSchema(), data_key="outputs", allow_none=True),
        required=True,
    )
