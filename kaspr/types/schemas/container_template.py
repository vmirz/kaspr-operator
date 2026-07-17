from marshmallow import ValidationError, fields, post_dump, validates_schema
from kaspr.utils.helpers import camel_to_snake
from kaspr.types.base import BaseSchema
from kaspr.types.models import (
    ContainerTemplate,
    ContainerEnvVar,
    ContainerEnvVarSource,
    ConfigMapKeySelector,
    FieldRefSelector,
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


class FieldRefSelectorSchema(BaseSchema):
    """Schema for Kubernetes downward API field references."""

    __model__ = FieldRefSelector
    field_path = fields.Str(
        data_key="fieldPath",
        required=True,
        allow_none=False,
    )
    api_version = fields.Str(
        data_key="apiVersion",
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
    field_ref = fields.Nested(
        FieldRefSelectorSchema(),
        data_key="fieldRef",
        required=False,
        allow_none=True,
        load_default=None,
    )

    @validates_schema(pass_original=True)
    def validate_supported_source(self, data, original_data, **kwargs):
        """Require exactly one supported Kubernetes env source."""
        source_fields = {
            "configMapKeyRef": data.get("config_map_key_ref"),
            "secretKeyRef": data.get("secret_key_ref"),
            "fieldRef": data.get("field_ref"),
        }
        provided_sources = [name for name, value in source_fields.items() if value is not None]
        if len(provided_sources) != 1:
            raise ValidationError(
                "Exactly one of configMapKeyRef, secretKeyRef, or fieldRef must be set.",
            )

        if isinstance(original_data, dict):
            extra_keys = set(original_data.keys()) - set(source_fields.keys())
            if extra_keys:
                raise ValidationError(
                    f"Unsupported valueFrom source(s): {', '.join(sorted(extra_keys))}"
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

    @validates_schema
    def validate_value_or_value_from(self, data, **kwargs):
        """Require exactly one Kubernetes EnvVar value mode."""
        has_value = data.get("value") is not None
        has_value_from = data.get("value_from") is not None
        if has_value == has_value_from:
            raise ValidationError(
                "Exactly one of value or valueFrom must be set.",
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
