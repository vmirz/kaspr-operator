from marshmallow import fields
from kaspr.types.base import BaseSchema
from kaspr.types.models.resource_requirements import ResourceRequirements

class ResourceRequirementsSchema(BaseSchema):
    __model__ = ResourceRequirements
    claims = fields.Dict(data_key="claims", default=None)
    requests = fields.Dict(data_key="requests", default=None)
    limits = fields.Dict(data_key="limits", default=None)