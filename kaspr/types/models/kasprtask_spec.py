from typing import Optional, List
from kaspr.types.base import BaseModel
from kaspr.types.models.code import CodeSpec
from kaspr.types.models.topicout import TopicOutSpec
from kaspr.types.models.tableref import TableRefSpec

class KasprTaskProcessorTopicSendOperator(TopicOutSpec): ...

class KasprTaskProcessorMapOperator(CodeSpec): ...

class KasprTaskProcessorFilterOperator(CodeSpec): ...

class KasprTaskScheduleSpec(BaseModel):
    interval: Optional[str]
    cron: Optional[str]

class KasprTaskProcessorsOperation(BaseModel):
    name: str
    tables: Optional[List[TableRefSpec]]    
    map: Optional[KasprTaskProcessorMapOperator]
    filter: Optional[KasprTaskProcessorFilterOperator]
    topic_send: Optional[KasprTaskProcessorTopicSendOperator]

class KasprTaskProcessorsInit(CodeSpec): ...

class KasprTaskProcessorsSpec(BaseModel):
    pipeline: List[str]
    init: KasprTaskProcessorsInit
    operations: List[KasprTaskProcessorsOperation]

class KasprTaskSpec(BaseModel):
    """KasprTask CRD spec"""

    name: str
    description: Optional[str]
    on_leader: Optional[bool]
    schedule: Optional[KasprTaskScheduleSpec]
    processors: KasprTaskProcessorsSpec