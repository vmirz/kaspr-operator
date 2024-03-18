from kaspr.types.base import BaseModel


class KasprAppStorage(BaseModel):
    """kaspr app storage configurations."""

    type: str
    storage_class: str
    size: str
    delete_claim: bool