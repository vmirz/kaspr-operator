from marshmallow import fields, post_dump
from kaspr.utils.helpers import camel_to_snake
from kaspr.types.base import BaseSchema
from kaspr.types.models import (
    KasprWebViewSpec,
    KasprWebViewRequestSpec,
    KasprWebViewResponseSpec,
    KasprWebViewResponseSelector,
    KasprWebViewProcessorSpec,
    KasprWebViewProcessorOperation,
    KasprWebViewProcessorsInit,
    KasprWebViewProcessorMapOperator,
    KasprWebViewProcessorTopicSendOperator,
)
from kaspr.types.schemas.topicout import TopicOutSpecSchema
from kaspr.types.schemas.code import CodeSpecSchema
from kaspr.types.schemas.tableref import TableRefSpecSchema

class KasprWebViewProcessorTopicSendOperatorSchema(TopicOutSpecSchema):
    __model__ = KasprWebViewProcessorTopicSendOperator


class KasprWebViewProcessorMapOperatorSchema(CodeSpecSchema):
    __model__ = KasprWebViewProcessorMapOperator


class KasprWebViewProcessorOperationSchema(BaseSchema):
    __model__ = KasprWebViewProcessorOperation

    name = fields.String(data_key="name", allow_none=True, load_default=None)
    topic_send = fields.Nested(
        KasprWebViewProcessorTopicSendOperatorSchema(),
        data_key="topicSend",
        allow_none=True,
        load_default=None,
    )
    map = fields.Nested(
        KasprWebViewProcessorMapOperatorSchema(),
        data_key="map",
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

    @post_dump
    def camel_to_snake_dump(self, data, **kwargs):
        """Convert data keys from camelCase to snake_case."""
        return camel_to_snake(data)


class KasprWebViewProcessorInitSchema(BaseSchema):
    __model__ = KasprWebViewProcessorsInit


class KasprWebViewProcessorSpecSchema(BaseSchema):
    __model__ = KasprWebViewProcessorSpec

    pipeline = fields.List(
        fields.Str(data_key="pipeline", allow_none=False, required=True),
        allow_none=False,
        load_default=[],
    )
    init = fields.Nested(
        KasprWebViewProcessorInitSchema(),
        data_key="init",
        allow_none=True,
        load_default=None,
    )
    operations = fields.List(
        fields.Nested(
            KasprWebViewProcessorOperationSchema(), data_key="operations", required=True
        ),
        allow_none=False,
        load_default=[],
    )


class KasprWebViewResponseSelectorSchema(BaseSchema):
    __model__ = KasprWebViewResponseSelector

    on_success = fields.Nested(
        CodeSpecSchema(),
        data_key="onSuccess",
        allow_none=True,
        load_default=None,
    )
    on_error = fields.Nested(
        CodeSpecSchema(),
        data_key="onError",
        allow_none=True,
        load_default=None,
    )

    @post_dump
    def camel_to_snake_dump(self, data, **kwargs):
        """Convert data keys from camelCase to snake_case."""
        return camel_to_snake(data)


class KasprWebViewResponseSpecSchema(BaseSchema):
    __model__ = KasprWebViewResponseSpec

    content_type = fields.Str(
        data_key="contentType", allow_none=False, load_default=None
    )
    status_code = fields.Int(data_key="statusCode", allow_none=False, load_default=None)
    headers = fields.Mapping(
        keys=fields.Str(required=True),
        values=fields.Str(required=True),
        data_key="headers",
        allow_none=False,
        load_default={},
    )
    body_selector = fields.Nested(
        KasprWebViewResponseSelectorSchema(),
        data_key="bodySelector",
        allow_none=True,
        load_default=None,
    )
    status_code_selector = fields.Nested(
        KasprWebViewResponseSelectorSchema(),
        data_key="statusCodeSelector",
        allow_none=True,
        load_default=None,
    )
    headers_selector = fields.Nested(
        KasprWebViewResponseSelectorSchema(),
        data_key="headersSelector",
        allow_none=True,
        load_default=None,
    )

    @post_dump
    def camel_to_snake_dump(self, data, **kwargs):
        """Convert data keys from camelCase to snake_case."""
        return camel_to_snake(data)


class KasprWebViewRequestSpecSchema(BaseSchema):
    __model__ = KasprWebViewRequestSpec

    method = fields.Str(data_key="method", allow_none=True, load_default=None)
    path = fields.Str(data_key="path", required=True)


class KasprWebViewSpecSchema(BaseSchema):
    __model__ = KasprWebViewSpec

    name = fields.Str(data_key="name", allow_none=False, required=True)
    description = fields.Str(data_key="description", allow_none=True, load_default=None)
    request = fields.Nested(
        KasprWebViewRequestSpecSchema(), data_key="request", required=True
    )
    response = fields.Nested(
        KasprWebViewResponseSpecSchema(),
        data_key="response",
        allow_none=True,
        load_default=None,
    )
    processors = fields.Nested(
        KasprWebViewProcessorSpecSchema(),
        data_key="processors",
        allow_none=True,
        load_default=None,
    )
