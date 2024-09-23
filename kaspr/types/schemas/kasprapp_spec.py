from marshmallow import fields
from kaspr.types.base import BaseSchema, EXCLUDE
from kaspr.types.schemas.tls import ClientTlsSchema
from kaspr.types.schemas.authentication import KafkaClientAuthenticationSchema
from kaspr.types.models.kasprapp_spec import KasprAppSpec
from kaspr.types.schemas.config import (
    KasprAppConfigSchema,
)
from kaspr.types.schemas.resource_requirements import ResourceRequirementsSchema
from kaspr.types.schemas.probe import ProbeSchema
from kaspr.types.schemas.storage import KasprAppStorageSchema


class KasprAppSpecSchema(BaseSchema):
    __model__ = KasprAppSpec

    version = fields.Str(data_key="version", allow_none=True, load_default=None)
    replicas = fields.Int(data_key="replicas", allow_none=True)
    image = fields.Str(data_key="image", allow_none=True, load_default=None)
    bootstrap_servers = fields.Str(data_key="bootstrapServers", required=True)
    tls = fields.Nested(ClientTlsSchema(), data_key="tls", allow_none=True, load_default=None)
    authentication = fields.Nested(
        KafkaClientAuthenticationSchema(), data_key="authentication", required=True
    )
    config = fields.Nested(
        KasprAppConfigSchema(),
        data_key="config",
        load_default=lambda: KasprAppConfigSchema().load({}),
    )
    resources = fields.Nested(
        ResourceRequirementsSchema(unknown=EXCLUDE),
        data_key="resources",
        load_default=None,
    )
    liveness_probe = fields.Nested(
        ProbeSchema(unknown=EXCLUDE),
        data_key="livenessProbe",
        load_default=lambda: ProbeSchema().load({}),
    )
    readiness_probe = fields.Nested(
        ProbeSchema(unknown=EXCLUDE),
        data_key="readinessProbe",
        load_default=lambda: ProbeSchema().load({}),
    )
    storage = fields.Nested(KasprAppStorageSchema(), data_key="storage", default=None)
