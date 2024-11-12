from typing import Optional, List
from kaspr.types.base import BaseModel
from kaspr.types.models.code import CodeSpec
from kaspr.types.models.operation import MapOperation, FilterOperation

class KasprAgentTopic(BaseModel):
    names: Optional[List[str]]
    pattern: Optional[str]
    key_serializer: Optional[str]
    value_serializer: Optional[str]

class KasprAgentChannel(BaseModel):
    name: str

class KasprAgentInput(BaseModel):
    topic: Optional[KasprAgentTopic]
    channel: Optional[KasprAgentChannel]

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
    inputs: KasprAgentInput
    processors: KasprAgentProcessors