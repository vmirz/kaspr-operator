from typing import Optional, List
from kaspr.types.base import BaseModel

class KasprAgentTopic(BaseModel):
    name: str
    partitions: Optional[int]

class KasprAgentChannel(BaseModel):
    name: str

class KasprAgentInput(BaseModel):
    topic: Optional[KasprAgentTopic]
    channel: Optional[KasprAgentChannel]

class KasprAgentOutput(BaseModel):
    topic: Optional[KasprAgentTopic]
    channel: Optional[KasprAgentChannel]

class KasprAgentSpec(BaseModel):
    """KasprAgent CRD spec"""

    description: Optional[str]
    inputs: List[KasprAgentInput]
    outputs: List[KasprAgentOutput]