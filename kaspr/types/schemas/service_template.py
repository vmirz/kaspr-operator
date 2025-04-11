from marshmallow import post_dump
from kaspr.utils.helpers import camel_to_snake
from kaspr.types.models import ServiceTemplate
from kaspr.types.schemas.resource_template import ResourceTemplateSchema


class ServiceTemplateSchema(ResourceTemplateSchema):
    __model__ = ServiceTemplate

    @post_dump
    def camel_to_snake_dump(self, data, **kwargs):
        """Convert data keys from camelCase to snake_case."""
        return camel_to_snake(data)    
