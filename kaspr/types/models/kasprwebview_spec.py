from typing import Optional, List, Mapping
from kaspr.types.base import BaseModel
from kaspr.types.models.code import CodeSpec
from kaspr.types.models.topicout import TopicOutSpec


class KasprWebViewProcessorTopicSendOperator(TopicOutSpec): ...


class KasprWebViewProcessorMapOperator(CodeSpec): ...


class KasprWebViewProcessorOperation(BaseModel):
    name: str
    topic_send: Optional[KasprWebViewProcessorTopicSendOperator]
    map: Optional[KasprWebViewProcessorMapOperator]


class KasprWebViewProcessorsInit(CodeSpec): ...


class KasprWebViewProcessorSpec(BaseModel):
    pipeline: Optional[List[str]]
    init: Optional[KasprWebViewProcessorsInit]
    operations: List[KasprWebViewProcessorOperation]


class KasprWebViewRequestSpec(BaseModel):
    method: str
    path: str


class KasprWebViewResponseSelector(BaseModel):
    on_success: Optional[CodeSpec]
    on_error: Optional[CodeSpec]


class KasprWebViewResponseSpec(BaseModel):
    content_type: Optional[str]
    status_code: Optional[int]
    headers: Optional[Mapping[str, str]]
    body_selector: Optional[KasprWebViewResponseSelector]
    status_code_selector: Optional[KasprWebViewResponseSelector]
    headers_selector: Optional[KasprWebViewResponseSelector]


class KasprWebViewSpec(BaseModel):
    """Kaspr WebView CRD spec"""

    name: str
    description: Optional[str]
    request: KasprWebViewRequestSpec
    response: KasprWebViewResponseSpec
    processors: KasprWebViewProcessorSpec
