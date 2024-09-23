from enum import Enum
from typing import Optional, Union
from kaspr.types.base import BaseModel
from kaspr.types.models.password import PasswordSecret
from kaspr.types.models.tls import ClientTls


class AuthType(Enum):
    PLAIN = "plain"
    SCRAM_SHA_256 = "scram-sha-256"
    SCRAM_SHA_512 = "scram-sha-512"
    TLS = "tls"


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
    certificate_and_key: KafkaClientAuthenticationTlsCertificateAndKey


class KafkaClientAuthenticationPlain(BaseModel):
    username: Optional[str]
    password_secret: Optional[PasswordSecret]


class KafkaClientAuthenticationScramSha256(KafkaClientAuthenticationPlain):
    pass

class KafkaClientAuthenticationScramSha512(KafkaClientAuthenticationPlain):
    pass


class KafkaClientAuthentication(BaseModel):
    # A protocol map is generated that uses the sasl and tls values to determine
    # which protocol to map to the listener.
    # Security Protocol Map:
    # SASL = True, TLS = True → SASL_SSL
    # SASL = False, TLS = True → SSL
    # SASL = True, TLS = False → SASL_PLAINTEXT
    # SASL = False, TLS = False → PLAINTEXT

    # Note: We say SASL is used when username and password are provided

    type: str  # plain, tls, scram_sha_256, scram_sha_512
    authentication_plain: Optional[KafkaClientAuthenticationPlain]
    authentication_scram_sha_256: Optional[KafkaClientAuthenticationScramSha256]
    authentication_scram_sha_512: Optional[KafkaClientAuthenticationScramSha512]
    authentication_tls: Optional[KafkaClientAuthenticationTls]

    _tls: ClientTls
    _security_protocol: AuthProtocol
    _sasl_credentials: SASLCredentials
    _sasl_enabled: bool

    def __init__(self, tls: ClientTls = None, **data) -> None:
        super().__init__(**data)
        self._tls = tls
        self._security_protocol = None
        self._sasl_credentials = None
        self._sasl_enabled = False

    def prepare_sasl_credentials(self) -> SASLCredentials:
        """Prepare SASL-based credentials details."""
        credentials: SASLCredentials = None
        mechanism = SASLMechanism(self.type.upper()) if self.type else None
        if mechanism == SASLMechanism.PLAIN:
            credentials = SASLCredentials(
                username=self.authentication_plain.username,
                password=self.authentication_plain.password_secret,
                tls=self.tls,
                mechanism=SASLMechanism.PLAIN,
            )
        elif mechanism == SASLMechanism.SCRAM_SHA_256:
            credentials = SASLCredentials(
                username=self.authentication_scram_sha_256.username,
                password=self.authentication_scram_sha_256.password_secret,
                tls=self.tls,
                mechanism=SASLMechanism.SCRAM_SHA_256,
            )
        elif mechanism == SASLMechanism.SCRAM_SHA_512:
            credentials = SASLCredentials(
                username=self.authentication_scram_sha_512.username,
                password=self.authentication_scram_sha_512.password_secret,
                tls=self.tls,
                mechanism=SASLMechanism.SCRAM_SHA_512,
            )
        return credentials

    def has_sasl_credentials(self) -> bool:
        """Return True if SASL credentials are provided."""
        if self.type == AuthType.PLAIN.value:
            return self.authentication_plain and self.authentication_plain.username
        elif self.type in [AuthType.SCRAM_SHA_256.value, AuthType.SCRAM_SHA_512.value]:
            return True
        return False

    def _prepare_security_protocol(self) -> AuthProtocol:
        """Return the security protocol based on the authentication mechanism."""
        if self.sasl_enabled:
            if self.tls is not None:
                return AuthProtocol.SASL_SSL
            return AuthProtocol.SASL_PLAINTEXT
        if self.tls is not None:
            return AuthProtocol.SSL
        return AuthProtocol.PLAINTEXT

    @property
    def tls(self) -> ClientTls:
        return self._tls

    @property
    def sasl_enabled(self) -> bool:
        """Return True if SASL is enabled."""
        if self._sasl_enabled:
            return self._sasl_enabled
        else:
            self._sasl_enabled = self.has_sasl_credentials()
            return self._sasl_enabled

    @property
    def sasl_credentials(self) -> SASLCredentials:
        """Return SASL-based credentials details.
        Returns None is authentication mechanism is not using SASL.
        """
        if self._sasl_credentials:
            return self._sasl_credentials
        else:
            self._sasl_credentials = self.prepare_sasl_credentials()
            return self._sasl_credentials

    @property
    def security_protocol(self) -> AuthProtocol:
        """Return the security protocol based on the authentication mechanism."""
        if self._security_protocol:
            return self._security_protocol
        else:
            self._security_protocol = self._prepare_security_protocol()
            return self._security_protocol
