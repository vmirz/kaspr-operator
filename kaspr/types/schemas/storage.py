from marshmallow import fields
from kaspr.types.base import BaseSchema
from kaspr.types.models.storage import KasprAppStorage


class KasprAppStorageSchema(BaseSchema):
    """kaspr app storage configurations."""

    __model__ = KasprAppStorage

    type = fields.Str(data_key="type", required=True)
    storage_class = fields.Str(data_key="class", required=True)
    size = fields.Str(data_key="size", required=True)
    delete_claim = fields.Bool(data_key="deleteClaim", load_default=None)
