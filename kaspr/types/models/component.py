from typing import Optional, List
from kaspr.types.base import BaseModel
from kaspr.types.models.kaspragent_spec import KasprAgentSpec

class KasprAppComponents(BaseModel):
    agents: Optional[List[KasprAgentSpec]]