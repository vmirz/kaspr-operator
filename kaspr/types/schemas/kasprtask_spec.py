from marshmallow import fields, post_dump
from kaspr.types.models.kasprtask_spec import KasprTaskSpec
from kaspr.utils.helpers import camel_to_snake
from kaspr.types.base import BaseSchema
from kaspr.types.models import (
    KasprTaskSpec,
    KasprTaskScheduleSpec,
    KasprTaskProcessorsSpec,
    KasprTaskProcessorTopicSendOperator,
    KasprTaskProcessorMapOperator,
    KasprTaskProcessorFilterOperator,
    KasprTaskProcessorsOperation,
    KasprTaskProcessorsInit,
)
from kaspr.types.schemas.topicout import TopicOutSpecSchema
from kaspr.types.schemas.code import CodeSpecSchema
from kaspr.types.schemas.tableref import TableRefSpecSchema

class KasprTaskProcessorTopicSendOperatorSchema(TopicOutSpecSchema):
    __model__ = KasprTaskProcessorTopicSendOperator

class KasprTaskProcessorMapOperatorSchema(CodeSpecSchema):
    __model__ = KasprTaskProcessorMapOperator

class KasprTaskProcessorFilterOperatorSchema(CodeSpecSchema):
    __model__ = KasprTaskProcessorFilterOperator

class KasprTaskProcessorOperationSchema(BaseSchema):
    __model__ = KasprTaskProcessorsOperation

    name = fields.String(data_key="name", allow_none=True, load_default=None)
    table_refs = fields.List(
        fields.Nested(
            TableRefSpecSchema(), required=True
        ),
        data_key="tables",
        allow_none=False,
        load_default=list,
    )     
    topic_send = fields.Nested(
        KasprTaskProcessorTopicSendOperatorSchema(),
        data_key="topicSend",
        allow_none=True,
        load_default=None,
    )
    map = fields.Nested(
        KasprTaskProcessorMapOperatorSchema(),
        data_key="map",
        allow_none=True,
        load_default=None,
    )
    filter = fields.Nested(
        KasprTaskProcessorFilterOperatorSchema(),
        data_key="filter",
        allow_none=True,
        load_default=None,
    )      

    @post_dump
    def camel_to_snake_dump(self, data, **kwargs):
        """Convert data keys from camelCase to snake_case."""
        return camel_to_snake(data)


class KasprTaskProcessorInitSchema(CodeSpecSchema):
    __model__ = KasprTaskProcessorsInit


class KasprTaskProcessorSpecSchema(BaseSchema):
    __model__ = KasprTaskProcessorsSpec

    pipeline = fields.List(
        fields.Str(data_key="pipeline", allow_none=False, required=True),
        allow_none=False,
        load_default=[],
    )
    init = fields.Nested(
        KasprTaskProcessorInitSchema(),
        data_key="init",
        allow_none=True,
        load_default=None,
    )
    operations = fields.List(
        fields.Nested(
            KasprTaskProcessorOperationSchema(), data_key="operations", required=True
        ),
        allow_none=False,
        load_default=[],
    )

class KasprTaskScheduleSpecSchema(BaseSchema):
    __model__ = KasprTaskScheduleSpec

    interval = fields.String(
        data_key="interval", allow_none=True, load_default=None
    )
    cron = fields.String(data_key="cron", allow_none=True, load_default=None)

class KasprTaskSpecSchema(BaseSchema):
    __model__ = KasprTaskSpec

    name = fields.Str(data_key="name", allow_none=False, required=True)
    description = fields.Str(data_key="description", allow_none=True, load_default=None)
    on_leader = fields.Bool(
        data_key="onLeader", allow_none=True, load_default=None
    )
    schedule = fields.Nested(
        KasprTaskScheduleSpecSchema(),
        data_key="schedule",
        allow_none=True,
        load_default=None,
    )
    processors = fields.Nested(
        KasprTaskProcessorSpecSchema(),
        data_key="processors",
        allow_none=True,
        load_default=None,
    )

    @post_dump
    def camel_to_snake_dump(self, data, **kwargs):
        """Convert data keys from camelCase to snake_case."""
        return camel_to_snake(data)