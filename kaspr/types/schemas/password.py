from marshmallow import fields
from kaspr.types.base import BaseSchema
from kaspr.types.models.password import PasswordSecret


class PasswordSecretSchema(BaseSchema):
    __model__ = PasswordSecret
    secret_name = fields.Str(data_key="secretName")
    password_key = fields.Str(data_key="passwordKey")
