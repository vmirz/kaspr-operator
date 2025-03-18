from marshmallow import fields
from kaspr.types.base import BaseSchema
from kaspr.types.models import CodeSpec


class CodeSpecSchema(BaseSchema):
    __model__ = CodeSpec

    python = fields.Str(data_key="python", required=False, load_default=None)