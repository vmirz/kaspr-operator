from typing import Optional
from kaspr.types.base import BaseModel
from kaspr.types.models.code import CodeSpec

class TopicOutSpec(BaseModel):
    name: str
    ack: Optional[bool]
    key_serializer: Optional[str]
    value_serializer: Optional[str]
    key_selector: Optional[CodeSpec]
    value_selector: Optional[CodeSpec]
    partition_selector: Optional[CodeSpec]
    headers_selector: Optional[CodeSpec]
    predicate: Optional[CodeSpec]