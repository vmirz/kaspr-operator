from kaspr.types.base import BaseModel


class PasswordSecret(BaseModel):
    secret_name: str
    password_key: str
