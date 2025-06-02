from marshmallow import fields, pre_load, post_dump
from kaspr.utils.helpers import camel_to_snake
from kaspr.types.base import BaseSchema
from kaspr.types.models import (
    PodTemplate,
    AdditionalVolume,
    SecretVolumeSource,
    ConfigMapVolumeSource,
    KeyToPath,
)
from kaspr.types.schemas.resource_template import ResourceTemplateSchema


class KeyToPathSchema(BaseSchema):
    """Schema for KeyToPath."""

    __model__ = KeyToPath
    key = fields.String(required=True, allow_none=False)
    path = fields.String(required=True, allow_none=False)
    mode = fields.Integer(allow_none=True, load_default=None)


class SecretVolumeSourceSchema(BaseSchema):
    """Schema for Secret Volume Source."""

    __model__ = SecretVolumeSource
    default_mode = fields.Integer(
        data_key="defaultMode",
        allow_none=True,
        load_default=None,
    )
    optional = fields.Boolean(
        allow_none=True,
        load_default=None,
        data_key="optional",
    )
    secret_name = fields.String(
        required=True,
        allow_none=False,
        data_key="secretName",
    )
    items = fields.List(
        fields.Nested(KeyToPathSchema()),
        allow_none=True,
        load_default=list,
        data_key="items",
    )

    @post_dump
    def camel_to_snake_dump(self, data, **kwargs):
        """Convert data keys from camelCase to snake_case."""
        return camel_to_snake(data)


class ConfigMapVolumeSourceSchema(BaseSchema):
    """Schema for ConfigMap Volume Source."""

    __model__ = ConfigMapVolumeSource
    default_mode = fields.Integer(
        data_key="defaultMode",
        allow_none=True,
        load_default=None,
    )
    optional = fields.Boolean(
        allow_none=True,
        load_default=None,
        data_key="optional",
    )
    name = fields.String(
        required=True,
        allow_none=False,
        data_key="name",
    )
    items = fields.List(
        fields.Nested(KeyToPathSchema()),
        allow_none=True,
        load_default=list,
        data_key="items",
    )

    @post_dump
    def camel_to_snake_dump(self, data, **kwargs):
        """Convert data keys from camelCase to snake_case."""
        return camel_to_snake(data)


class AdditionalVolumeSchema(BaseSchema):
    __model__ = AdditionalVolume
    name = fields.Str(required=True)
    secret = fields.Nested(
        SecretVolumeSourceSchema(),
        data_key="secret",
        allow_none=True,
        load_default=None,
    )
    config_map = fields.Nested(
        ConfigMapVolumeSourceSchema(),
        allow_none=True,
        load_default=None,
        data_key="configMap",
    )
    empty_dir = fields.Dict(
        keys=fields.String(),
        values=fields.Raw(),
        allow_none=True,
        load_default=None,
        data_key="emptyDir",
    )
    persistent_volume_claim = fields.Dict(
        keys=fields.String(),
        values=fields.Raw(),
        allow_none=True,
        load_default=None,
        data_key="persistentVolumeClaim",
    )
    csi = fields.Dict(
        keys=fields.String(),
        values=fields.Raw(),
        allow_none=True,
        load_default=None,
        data_key="csi",
    )

    @post_dump
    def camel_to_snake_dump(self, data, **kwargs):
        """Convert data keys from camelCase to snake_case."""
        return camel_to_snake(data)


class PodTemplateSchema(ResourceTemplateSchema):
    __model__ = PodTemplate

    image_pull_secrets = fields.List(
        fields.Dict(keys=fields.String(), values=fields.Raw(), allow_none=False),
        data_key="imagePullSecrets",
        allow_none=True,
        load_default=list,
    )
    security_context = fields.Dict(
        keys=fields.String(),
        values=fields.Raw(),
        data_key="securityContext",
        allow_none=True,
        load_default=None,
    )
    termination_grace_period_seconds = fields.Int(
        data_key="terminationGracePeriodSeconds", allow_none=True, load_default=None
    )
    node_selector = fields.Dict(
        keys=fields.String(),
        values=fields.String(),
        data_key="nodeSelector",
        allow_none=True,
        load_default=None,
    )
    affinity = fields.Dict(
        keys=fields.String(),
        values=fields.Raw(),
        data_key="affinity",
        allow_none=True,
        load_default=None,
    )
    tolerations = fields.List(
        fields.Dict(keys=fields.String(), values=fields.Raw(), allow_none=False),
        data_key="tolerations",
        allow_none=True,
        load_default=list,
    )
    topology_spread_constraints = fields.List(
        fields.Dict(keys=fields.String(), values=fields.Raw(), allow_none=False),
        data_key="topologySpreadConstraints",
        allow_none=True,
        load_default=list,
    )
    priority_class_name = fields.Str(
        data_key="priorityClassName",
        allow_none=True,
        load_default=None,
    )
    scheduler_name = fields.Str(
        data_key="schedulerName",
        allow_none=True,
        load_default=None,
    )
    host_aliases = fields.List(
        fields.Dict(keys=fields.String(), values=fields.Raw(), allow_none=False),
        data_key="hostAliases",
        allow_none=True,
        load_default=list,
    )
    enable_service_links = fields.Boolean(
        data_key="enableServiceLinks",
        allow_none=True,
        load_default=None,
    )
    volumes = fields.List(
        fields.Nested(AdditionalVolumeSchema()),
        data_key="volumes",
        allow_none=True,
        load_default=list,
    )

    @pre_load
    def make(self, data, **kwargs):
        if "metadata" not in data:
            data["metadata"] = {}
        return data

    @post_dump
    def camel_to_snake_dump(self, data, **kwargs):
        """Convert data keys from camelCase to snake_case."""
        return camel_to_snake(data)
