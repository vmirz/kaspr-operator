from kaspr.types.base import BaseSchema
from kaspr.types.models.tls import ClientTls


class ClientTlsSchema(BaseSchema):
    __model__ = ClientTls
