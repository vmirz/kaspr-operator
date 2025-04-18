from marshmallow import fields, post_dump
from kaspr.utils.helpers import camel_to_snake
from kaspr.types.base import BaseSchema
from kaspr.types.models import (
    ContainerTemplate,
    ContainerEnvVar,
    ContainerEnvVarSource,
    ConfigMapKeySelector,
    SecretKeySelector,
    VolumeMount,
)


class ConfigMapKeySelectorSchema(BaseSchema):
    """Schema for Secret Key Selector."""

    __model__ = ConfigMapKeySelector
    key = fields.Str(
        data_key="key",
        required=True,
        allow_none=False,
    )
    name = fields.Str(
        data_key="name",
        required=True,
        allow_none=False,
    )
    optional = fields.Bool(
        data_key="optional",
        required=False,
        allow_none=True,
        load_default=None,
    )


class SecretKeySelectorSchema(BaseSchema):
    """Schema for Secret Key Selector."""

    __model__ = SecretKeySelector
    key = fields.Str(
        data_key="key",
        required=True,
        allow_none=False,
    )
    name = fields.Str(
        data_key="name",
        required=True,
        allow_none=False,
    )
    optional = fields.Bool(
        data_key="optional",
        required=False,
        allow_none=True,
        load_default=None,
    )


class ContainerEnvVarSourceSchema(BaseSchema):
    """Schema for Container Environment Variable Source."""

    __model__ = ContainerEnvVarSource
    config_map_key_ref = fields.Nested(
        ConfigMapKeySelectorSchema(),
        data_key="configMapKeyRef",
        required=False,
        allow_none=True,
        load_default=None,
    )
    secret_key_ref = fields.Nested(
        SecretKeySelectorSchema(),
        data_key="secretKeyRef",
        required=False,
        allow_none=True,
        load_default=None,
    )


class ContainerEnvVarSchema(BaseSchema):
    """Schema for Container Environment Variables."""

    __model__ = ContainerEnvVar
    name = fields.Str(
        data_key="name",
        required=True,
        allow_none=False,
    )
    value = fields.Str(
        data_key="value",
        required=False,
        allow_none=True,
        load_default=None,
    )
    value_from = fields.Nested(
        ContainerEnvVarSourceSchema(),
        data_key="valueFrom",
        required=False,
        allow_none=True,
        load_default=None,
    )

    @post_dump
    def camel_to_snake_dump(self, data, **kwargs):
        """Convert data keys from camelCase to snake_case."""
        return camel_to_snake(data)


class VolumeMountSchema(BaseSchema):
    __model__ = VolumeMount

    name = fields.Str(
        data_key="name",
        required=True,
        allow_none=False,
    )
    mount_path = fields.Str(
        data_key="mountPath",
        required=True,
        allow_none=False,
    )
    sub_path = fields.Str(
        data_key="subPath",
        required=False,
        allow_none=True,
        load_default=None,
    )
    read_only = fields.Bool(
        data_key="readOnly",
        required=False,
        allow_none=True,
        load_default=None,
    )
    mount_propagation = fields.Str(
        data_key="mountPropagation",
        required=False,
        allow_none=True,
        load_default=None,
    )
    sub_path_expr = fields.Str(
        data_key="subPathExpr",
        required=False,
        allow_none=True,
        load_default=None,
    )

    @post_dump
    def camel_to_snake_dump(self, data, **kwargs):
        """Convert data keys from camelCase to snake_case."""
        return camel_to_snake(data)


class ContainerTemplateSchema(BaseSchema):
    __model__ = ContainerTemplate

    env = fields.List(
        fields.Nested(ContainerEnvVarSchema()),
        data_key="env",
        allow_none=True,
        load_default=list,
    )
    volume_mounts = fields.List(
        fields.Nested(VolumeMountSchema()),
        data_key="volumeMounts",
        allow_none=True,
        load_default=list,
    )
    security_context = fields.Dict(
        keys=fields.String(),
        values=fields.Raw(),
        allow_none=True,
        load_default=None,
        data_key="securityContext",
    )

    @post_dump
    def camel_to_snake_dump(self, data, **kwargs):
        """Convert data keys from camelCase to snake_case."""
        return camel_to_snake(data)
