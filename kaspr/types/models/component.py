from typing import Optional, List
from kaspr.types.base import BaseModel
from kaspr.types.models.kaspragent_spec import KasprAgentSpec
from kaspr.types.models.kasprwebview_spec import KasprWebViewSpec
from kaspr.types.models.kasprtable_spec import KasprTableSpec
from kaspr.types.models.kasprtask_spec import KasprTaskSpec
from kaspr.types.models.kasprjoin_spec import KasprJoinSpec

class KasprAppComponents(BaseModel):
    agents: Optional[List[KasprAgentSpec]]
    webviews: Optional[List[KasprWebViewSpec]]
    tables: Optional[List[KasprTableSpec]]
    tasks: Optional[List[KasprTaskSpec]]
    joins: Optional[List[KasprJoinSpec]]
    