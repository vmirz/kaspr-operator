from typing import Optional, List, Mapping
from kaspr.types.base import BaseModel
from kaspr.types.models.code import CodeSpec
from kaspr.types.models.operation import MapOperation, FilterOperation
from kaspr.types.models.topicout import TopicOutSpec
from kaspr.types.models.tableref import TableRefSpec

class KasprAgentInputTopic(BaseModel):
    names: Optional[List[str]]
    pattern: Optional[str]
    key_serializer: Optional[str]
    value_serializer: Optional[str]
    partitions: Optional[int]
    retention: Optional[int]
    compacting: Optional[bool]
    deleting: Optional[bool]
    replicas: Optional[int]
    config: Optional[Mapping[str, str]]    

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
    tables: Optional[List[TableRefSpec]]

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