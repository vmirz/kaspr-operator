from typing import Any
from marshmallow import fields
from kaspr.types.base import BaseSchema, EXCLUDE, post_load
from kaspr.types.schemas.tls import ClientTlsSchema
from kaspr.types.schemas.authentication import KafkaClientAuthenticationSchema
from kaspr.types.models.kasprapp_spec import KasprAppSpec, KasprAppTemplate
from kaspr.types.schemas.config import (
    KasprAppConfigSchema,
)
from kaspr.types.schemas.resource_requirements import ResourceRequirementsSchema
from kaspr.types.schemas.probe import ProbeSchema
from kaspr.types.schemas.storage import KasprAppStorageSchema
from kaspr.types.schemas.resource_template import ResourceTemplateSchema
from kaspr.types.schemas.pod_template import PodTemplateSchema
from kaspr.types.schemas.service_template import ServiceTemplateSchema
from kaspr.types.schemas.container_template import ContainerTemplateSchema
from kaspr.types.schemas.python_packages import PythonPackagesSpecSchema


class KasprAppTemplateSchema(BaseSchema):
    __model__ = KasprAppTemplate

    service_account = fields.Nested(
        ResourceTemplateSchema(),
        data_key="serviceAccount",
        allow_none=True,
        load_default=None,
    )
    pod = fields.Nested(
        PodTemplateSchema(),
        data_key="pod",
        allow_none=True,
        load_default=lambda: PodTemplateSchema().load({}),
    )
    service = fields.Nested(
        ServiceTemplateSchema(),
        data_key="service",
        allow_none=True,
        load_default=lambda: ServiceTemplateSchema().load({}),
    )
    kaspr_container = fields.Nested(
        ContainerTemplateSchema(),
        data_key="kasprContainer",
        allow_none=True,
        load_default=lambda: ContainerTemplateSchema().load({}),
    )


class KasprAppSpecSchema(BaseSchema):
    __model__ = KasprAppSpec

    version = fields.Str(data_key="version", allow_none=True, load_default=None)
    replicas = fields.Int(data_key="replicas", allow_none=True)
    image = fields.Str(data_key="image", allow_none=True, load_default=None)
    bootstrap_servers = fields.Str(data_key="bootstrapServers", required=True)
    tls = fields.Nested(
        ClientTlsSchema(), data_key="tls", allow_none=True, load_default=None
    )
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
    storage = fields.Nested(KasprAppStorageSchema(), data_key="storage", dump_default=None)
    template = fields.Nested(
        KasprAppTemplateSchema(),
        data_key="template",
        allow_none=True,
        load_default=lambda: KasprAppTemplateSchema().load({}),
    )
    python_packages = fields.Nested(
        PythonPackagesSpecSchema(),
        data_key="pythonPackages",
        allow_none=True,
        load_default=None,
    )

    @post_load
    def include_tls(self, app: KasprAppSpec, **kwargs: Any) -> KasprAppSpec:
        """Include TLS spec in the child authentication object."""
        if "authentication" in app:
            app["authentication"].tls = app["tls"]
        return app
