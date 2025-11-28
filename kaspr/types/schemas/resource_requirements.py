from marshmallow import fields
from kaspr.types.base import BaseSchema
from kaspr.types.models.resource_requirements import ResourceRequirements

class ResourceRequirementsSchema(BaseSchema):
    __model__ = ResourceRequirements
    claims = fields.Dict(data_key="claims", dump_default=None)
    requests = fields.Dict(data_key="requests", dump_default=None)
    limits = fields.Dict(data_key="limits", dump_default=None)