from marshmallow import fields
from kaspr.types.base import BaseSchema
from kaspr.types.models import ResourceTemplate


class MetadataTemplateSchema(BaseSchema):
    labels = fields.Dict(
        keys=fields.String(), values=fields.String(), allow_none=True, load_default={}
    )
    annotations = fields.Dict(
        keys=fields.String(), values=fields.String(), allow_none=True, load_default={}
    )


class ResourceTemplateSchema(BaseSchema):
    __model__ = ResourceTemplate
    metadata = fields.Nested(
        MetadataTemplateSchema(), data_key="metadata", required=True
    )
