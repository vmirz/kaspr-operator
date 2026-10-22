from typing import Dict, List, Optional, Union
from kaspr.types.base import BaseModel


class VerticalPodAutoscalerSpec(BaseModel):
    """VerticalPodAutoscaler the operator manages for a KasprApp (opt-in)."""

    enabled: bool
    update_mode: str
    min_replicas: Optional[int]
    controlled_resources: List[str]
    controlled_values: str
    min_allowed: Optional[Dict[str, Union[str, int]]]
    max_allowed: Optional[Dict[str, Union[str, int]]]
