from enum import Enum
from typing import Optional, Union
from kaspr.types.base import BaseModel
from kaspr.types.models.password import PasswordSecret
from kaspr.types.models.tls import ClientTls


class AuthProtocol(Enum):
    SSL = "SSL"
    PLAINTEXT = "PLAINTEXT"
    SASL_PLAINTEXT = "SASL_PLAINTEXT"
    SASL_SSL = "SASL_SSL"


class SASLMechanism(Enum):
    PLAIN = "PLAIN"
    GSSAPI = "GSSAPI"
    SCRAM_SHA_256 = "SCRAM-SHA-256"
    SCRAM_SHA_512 = "SCRAM-SHA-512"


class Credentials:
    """Base class for authentication credentials."""

    protocol: AuthProtocol


class SASLCredentials(Credentials):
    """Describe SASL credentials."""

    protocol = AuthProtocol.SASL_PLAINTEXT
    mechanism: SASLMechanism = SASLMechanism.PLAIN

    username: Optional[str]
    password: Optional[PasswordSecret]

    def __init__(
        self,
        *,
        username: str = None,
        password: PasswordSecret = None,
        tls: ClientTls = None,
        mechanism: Union[str, SASLMechanism] = None,
    ) -> None:
        self.username = username
        self.password = password

        if tls is not None:
            self.protocol = AuthProtocol.SASL_SSL

        if mechanism is not None:
            self.mechanism = SASLMechanism(mechanism)

    def __repr__(self) -> str:
        return f"<{type(self).__name__}: username={self.username}>"


class KafkaClientAuthenticationTlsCertificateAndKey(BaseModel):
    secret_name: str
    certificate: str
    key: str


class KafkaClientAuthenticationTls(BaseModel):
    type: str
    certificate_and_key: KafkaClientAuthenticationTlsCertificateAndKey


class KafkaClientAuthenticationPlain(BaseModel):
    type: str
    username: str
    password_secret: PasswordSecret


class KafkaClientAuthenticationScramSha256(KafkaClientAuthenticationPlain):
    pass


class KafkaClientAuthenticationScramSha512(KafkaClientAuthenticationPlain):
    pass


class KafkaClientAuthentication(BaseModel):
    type: str
    authentication_plain: Optional[KafkaClientAuthenticationPlain]
    authentication_scram_sha_256: Optional[KafkaClientAuthenticationScramSha256]
    authentication_scram_sha_512: Optional[KafkaClientAuthenticationScramSha512]
    authentication_tls: Optional[KafkaClientAuthenticationTls]

    def sasl_credentials(self, tls: ClientTls = None) -> SASLCredentials:
        """Return SASL-based credentials details. 
        Returns None is authentication mechanism is not using SASL.
        """
        credentials: SASLCredentials = None
        mechanism = SASLMechanism(self.type.upper()) if self.type else None
        if mechanism == SASLMechanism.PLAIN:
            credentials = SASLCredentials(
                username=self.authentication_plain.username,
                password=self.authentication_plain.password_secret,
                tls=tls,
                mechanism=SASLMechanism.PLAIN,
            )
        elif mechanism == SASLMechanism.SCRAM_SHA_256:
            credentials = SASLCredentials(
                username=self.authentication_scram_sha_256.username,
                password=self.authentication_scram_sha_256.password_secret,
                tls=tls,
                mechanism=SASLMechanism.SCRAM_SHA_256,
            )
        elif mechanism == SASLMechanism.SCRAM_SHA_512:
            credentials = SASLCredentials(
                username=self.authentication_scram_sha_512.username,
                password=self.authentication_scram_sha_512.password_secret,
                tls=tls,
                mechanism=SASLMechanism.SCRAM_SHA_512,
            )
        return credentials
