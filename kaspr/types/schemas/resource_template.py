from marshmallow import fields, pre_load
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
        MetadataTemplateSchema(), data_key="metadata", allow_none=True, load_default={}
    )

    @pre_load
    def make(self, data, **kwargs):
        if "metadata" not in data:
            data["metadata"] = {}
        return data
