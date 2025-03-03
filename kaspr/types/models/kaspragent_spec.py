from typing import Optional, List
from kaspr.types.base import BaseModel
from kaspr.types.models.code import CodeSpec
from kaspr.types.models.operation import MapOperation, FilterOperation
from kaspr.types.models.topicout import TopicOutSpec

class KasprAgentInputTopic(BaseModel):
    names: Optional[List[str]]
    pattern: Optional[str]
    key_serializer: Optional[str]
    value_serializer: Optional[str]

class KasprAgentInputChannel(BaseModel):
    name: str

class KasprAgentInput(BaseModel):
    topic: Optional[KasprAgentInputTopic]
    channel: Optional[KasprAgentInputChannel]

class KasprAgentOutput(BaseModel):
    topics: Optional[List[TopicOutSpec]]

class KasprAgentProcessorsOperation(BaseModel):
    name: str
    map: Optional[MapOperation]
    filter: Optional[FilterOperation]

class KasprAgentProcessorsInit(CodeSpec):
    ...

class KasprAgentProcessors(BaseModel):
    pipeline: List[str]
    init: KasprAgentProcessorsInit
    operations: List[KasprAgentProcessorsOperation]

class KasprAgentSpec(BaseModel):
    """KasprAgent CRD spec"""

    name: str
    description: Optional[str]
    input: KasprAgentInput
    output: KasprAgentOutput
    processors: KasprAgentProcessors