from marshmallow import fields, pre_load
from kaspr.types.base import BaseSchema
from kaspr.types.schemas.password import PasswordSecretSchema
from kaspr.types.models.authentication import (
    KafkaClientAuthenticationTlsCertificateAndKey,
    KafkaClientAuthenticationTls,
    KafkaClientAuthenticationPlain,
    KafkaClientAuthenticationScramSha256,
    KafkaClientAuthenticationScramSha512,
    KafkaClientAuthentication,
)


class KafkaClientAuthenticationTlsCertificateAndKeySchema(BaseSchema):
    __model__ = KafkaClientAuthenticationTlsCertificateAndKey
    secret_name = fields.Str(data_key="secretName", required=True)
    certificate = fields.Str(data_key="certificate", required=True)
    key = fields.Str(data_key="key", required=True)


class KafkaClientAuthenticationTlsSchema(BaseSchema):
    __model__ = KafkaClientAuthenticationTls
    type = fields.Str(data_key="type")
    certificate_and_key = fields.Nested(
        KafkaClientAuthenticationTlsCertificateAndKeySchema(),
        data_key="certificateAndKey",
        required=True,
    )


class KafkaClientAuthenticationPlainSchema(BaseSchema):
    __model__ = KafkaClientAuthenticationPlain
    type = fields.Str(data_key="type")
    username = fields.Str(data_key="username", required=True)
    password_secret = fields.Nested(
        PasswordSecretSchema(), data_key="passwordSecret", required=True
    )


class KafkaClientAuthenticationScramSha256Schema(KafkaClientAuthenticationPlainSchema):
    __model__ = KafkaClientAuthenticationScramSha256
    pass


class KafkaClientAuthenticationScramSha512Schema(KafkaClientAuthenticationPlainSchema):
    __model__ = KafkaClientAuthenticationScramSha512
    pass


class KafkaClientAuthenticationSchema(BaseSchema):
    __model__ = KafkaClientAuthentication

    type = fields.Str(required=True)
    authentication_plain = fields.Nested(
        KafkaClientAuthenticationPlainSchema(), default=None
    )
    authentication_scram_sha_256 = fields.Nested(
        KafkaClientAuthenticationScramSha256Schema(), default=None
    )
    authentication_scram_sha_512 = fields.Nested(
        KafkaClientAuthenticationScramSha512Schema(), default=None
    )
    authentication_tls = fields.Nested(
        KafkaClientAuthenticationTlsSchema(), default=None
    )

    @pre_load
    def make(self, data, **kwargs):
        authentication = {"type": data["type"]}
        if data["type"] == "plain":
            authentication["authentication_plain"] = data
        elif data["type"] == "scram-sha-256":
            authentication["authentication_scram_sha_256"] = data
        elif data["type"] == "scram-sha-512":
            authentication["authentication_scram_sha_512"] = data
        elif data["type"] == "tls":
            authentication["authentication_tls"] = data
        return authentication
