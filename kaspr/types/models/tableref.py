from kaspr.types.base import BaseModel


class TableRefSpec(BaseModel):
    name: str
    param_name: str