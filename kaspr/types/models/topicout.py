from typing import Optional, Mapping
from kaspr.types.base import BaseModel
from kaspr.types.models.code import CodeSpec

class TopicOutSpec(BaseModel):
    name: str
    name_selector: Optional[CodeSpec]
    declare: Optional[bool]
    pass_through: Optional[bool]
    ack: Optional[bool]
    key_serializer: Optional[str]
    value_serializer: Optional[str]
    partitions: Optional[int]
    retention: Optional[int]
    compacting: Optional[bool]
    deleting: Optional[bool]
    replicas: Optional[int]
    config: Optional[Mapping[str, str]]
    key_selector: Optional[CodeSpec]
    value_selector: Optional[CodeSpec]
    partition_selector: Optional[CodeSpec]
    headers_selector: Optional[CodeSpec]
    predicate: Optional[CodeSpec]