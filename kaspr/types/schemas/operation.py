from kaspr.types.models import MapOperation, FilterOperation
from kaspr.types.schemas.code import CodeSpecSchema

class MapOperationSchema(CodeSpecSchema):
    __model__ = MapOperation

class FilterOperationSchema(CodeSpecSchema):
    __model__ = FilterOperation