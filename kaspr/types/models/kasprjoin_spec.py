from typing import Optional
from kaspr.types.base import BaseModel
from kaspr.types.models.code import CodeSpec


class KasprJoinSpec(BaseModel):
    """KasprJoin CRD spec"""

    name: str
    description: Optional[str]
    left_table: str
    right_table: str
    extractor: CodeSpec
    join_type: Optional[str]        # "inner" (default) or "left"
    output_channel: Optional[str]   # Named channel for joined output
