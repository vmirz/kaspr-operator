from typing import Optional, Mapping
from kaspr.types.base import BaseModel
from kaspr.types.models.code import CodeSpec


class KasprTableWindowTumblingSpec(BaseModel):
    size: int
    expires_at: Optional[str]


class KasprTableWindowHoppingSpec(BaseModel):
    size: int
    step: int
    expires: str


class KasprTableWindowSpec(BaseModel):
    tumbling: Optional[KasprTableWindowTumblingSpec]
    hopping: Optional[KasprTableWindowHoppingSpec]
    relative_to: Optional[str]
    relative_to_field_selector: Optional[CodeSpec]


class KasprTableSpec(BaseModel):
    name: str
    description: Optional[str]
    is_global: Optional[bool]
    default_selector: Optional[CodeSpec]
    key_serializer: Optional[str]
    value_serializer: Optional[str]
    partitions: Optional[int]
    extra_topic_configs: Optional[Mapping[str, str]]
    window: Optional[KasprTableWindowSpec]
