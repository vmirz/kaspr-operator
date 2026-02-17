"""Python packages schemas for validation."""

import re
import warnings
from marshmallow import fields, validates, validates_schema, ValidationError
from kaspr.types.base import BaseSchema
from kaspr.types.models.python_packages import (
    GCSCacheConfig,
    GCSSecretReference,
    PythonPackagesCache,
    PythonPackagesCredentials,
    PythonPackagesInstallPolicy,
    PythonPackagesResources,
    PythonPackagesSpec,
    PythonPackagesStatus,
    SecretReference,
)


class GCSSecretReferenceSchema(BaseSchema):
    """Schema for GCS service account key Secret reference."""

    __model__ = GCSSecretReference

    name = fields.String(
        data_key="name",
        required=True,
    )
    key = fields.String(
        data_key="key",
        allow_none=True,
        load_default=None,
    )


class GCSCacheConfigSchema(BaseSchema):
    """Schema for GCS cache configuration."""

    __model__ = GCSCacheConfig

    bucket = fields.String(
        data_key="bucket",
        required=True,
    )
    prefix = fields.String(
        data_key="prefix",
        allow_none=True,
        load_default=None,
    )
    max_archive_size = fields.String(
        data_key="maxArchiveSize",
        allow_none=True,
        load_default=None,
    )
    secret_ref = fields.Nested(
        GCSSecretReferenceSchema(),
        data_key="secretRef",
        required=True,
    )


class PythonPackagesCacheSchema(BaseSchema):
    """Schema for Python packages cache configuration."""
    
    __model__ = PythonPackagesCache
    
    type = fields.String(
        data_key="type",
        allow_none=True,
        load_default=None,
    )
    enabled = fields.Boolean(
        data_key="enabled",
        allow_none=True,
        load_default=None,
    )
    storage_class = fields.String(
        data_key="storageClass",
        allow_none=True,
        load_default=None,
    )
    size = fields.String(
        data_key="size",
        allow_none=True,
        load_default=None,
    )
    access_mode = fields.String(
        data_key="accessMode",
        allow_none=True,
        load_default=None,
    )
    delete_claim = fields.Boolean(
        data_key="deleteClaim",
        allow_none=True,
        load_default=None,
    )
    gcs = fields.Nested(
        GCSCacheConfigSchema(),
        data_key="gcs",
        allow_none=True,
        load_default=None,
    )
    
    @validates("type")
    def validate_type(self, value):
        """Validate cache type."""
        if value is not None:
            valid_types = ["pvc", "gcs"]
            if value not in valid_types:
                raise ValidationError(
                    f"Invalid cache type: {value}. Must be one of {valid_types}"
                )
    
    @validates("access_mode")
    def validate_access_mode(self, value):
        """Validate access mode is ReadWriteMany (only supported mode)."""
        if value is not None and value != "ReadWriteMany":
            raise ValidationError(
                f"Invalid access mode: {value}. Only 'ReadWriteMany' is currently supported for shared package cache."
            )
    
    @validates_schema
    def validate_gcs_config(self, data, **kwargs):
        """Validate GCS configuration is provided when type is gcs."""
        cache_type = data.get("type")
        if cache_type == "gcs":
            if not data.get("gcs"):
                raise ValidationError(
                    "GCS configuration (gcs) is required when cache type is 'gcs'.",
                    field_name="gcs",
                )
            if data.get("enabled") is not None:
                warnings.warn(
                    "cache.enabled is ignored when cache.type is 'gcs'. "
                    "GCS caching is always active when type is 'gcs'. "
                    "Remove the 'enabled' field to silence this warning.",
                    UserWarning,
                    stacklevel=2,
                )


class PythonPackagesInstallPolicySchema(BaseSchema):
    """Schema for installation policy configuration."""
    
    __model__ = PythonPackagesInstallPolicy
    
    retries = fields.Integer(
        data_key="retries",
        allow_none=True,
        load_default=None,
    )
    timeout = fields.Integer(
        data_key="timeout",
        allow_none=True,
        load_default=None,
    )
    on_failure = fields.String(
        data_key="onFailure",
        allow_none=True,
        load_default=None,
    )
    
    @validates("retries")
    def validate_retries(self, value):
        """Validate retries is positive."""
        if value is not None and value < 0:
            raise ValidationError("Retries must be non-negative")
    
    @validates("timeout")
    def validate_timeout(self, value):
        """Validate timeout is positive."""
        if value is not None and value < 60:
            raise ValidationError("Timeout must be at least 60 seconds")
    
    @validates("on_failure")
    def validate_on_failure(self, value):
        """Validate onFailure is a valid option."""
        if value is not None:
            valid_options = ["block", "allow"]
            if value not in valid_options:
                raise ValidationError(
                    f"Invalid onFailure value: {value}. Must be one of {valid_options}"
                )


class PythonPackagesResourcesSchema(BaseSchema):
    """Schema for init container resources."""
    
    __model__ = PythonPackagesResources
    
    requests = fields.Dict(
        data_key="requests",
        allow_none=True,
        load_default=None,
    )
    limits = fields.Dict(
        data_key="limits",
        allow_none=True,
        load_default=None,
    )


class SecretReferenceSchema(BaseSchema):
    """Schema for Kubernetes Secret reference."""

    __model__ = SecretReference

    name = fields.String(
        data_key="name",
        required=True,
    )
    username_key = fields.String(
        data_key="usernameKey",
        allow_none=True,
        load_default=None,
    )
    password_key = fields.String(
        data_key="passwordKey",
        allow_none=True,
        load_default=None,
    )


class PythonPackagesCredentialsSchema(BaseSchema):
    """Schema for PyPI authentication credentials."""

    __model__ = PythonPackagesCredentials

    secret_ref = fields.Nested(
        SecretReferenceSchema(),
        data_key="secretRef",
        required=True,
    )


# URL validation pattern for index URLs
_URL_PATTERN = re.compile(r'^https?://.+')


class PythonPackagesSpecSchema(BaseSchema):
    """Schema for Python packages specification."""
    
    __model__ = PythonPackagesSpec
    
    packages = fields.List(
        fields.String(),
        data_key="packages",
        required=True,
    )
    index_url = fields.String(
        data_key="indexUrl",
        allow_none=True,
        load_default=None,
    )
    extra_index_urls = fields.List(
        fields.String(),
        data_key="extraIndexUrls",
        allow_none=True,
        load_default=None,
    )
    trusted_hosts = fields.List(
        fields.String(),
        data_key="trustedHosts",
        allow_none=True,
        load_default=None,
    )
    credentials = fields.Nested(
        PythonPackagesCredentialsSchema(),
        data_key="credentials",
        allow_none=True,
        load_default=None,
    )
    cache = fields.Nested(
        PythonPackagesCacheSchema(),
        data_key="cache",
        allow_none=True,
        load_default=None,
    )
    install_policy = fields.Nested(
        PythonPackagesInstallPolicySchema(),
        data_key="installPolicy",
        allow_none=True,
        load_default=None,
    )
    resources = fields.Nested(
        PythonPackagesResourcesSchema(),
        data_key="resources",
        allow_none=True,
        load_default=None,
    )
    
    @validates("packages")
    def validate_packages(self, value):
        """Validate packages list is not empty and contains valid package specs."""
        if not value:
            raise ValidationError("Packages list cannot be empty")
        
        for package in value:
            if not isinstance(package, str) or not package.strip():
                raise ValidationError(f"Invalid package specification: {package}")
            
            # Basic validation for package format
            # Valid formats: package, package==1.0.0, package>=1.0.0, etc.
            if any(char in package for char in [' ', '\t', '\n']):
                raise ValidationError(
                    f"Package specification contains invalid whitespace: {package}"
                )

    @validates("index_url")
    def validate_index_url(self, value):
        """Validate index URL is well-formed."""
        if value is not None and not _URL_PATTERN.match(value):
            raise ValidationError(
                f"Invalid index URL: {value}. Must start with http:// or https://"
            )

    @validates("extra_index_urls")
    def validate_extra_index_urls(self, value):
        """Validate extra index URLs are well-formed."""
        if value is not None:
            for url in value:
                if not _URL_PATTERN.match(url):
                    raise ValidationError(
                        f"Invalid extra index URL: {url}. Must start with http:// or https://"
                    )


class PythonPackagesStatusSchema(BaseSchema):
    """Schema for Python packages status.
    """
    
    __model__ = PythonPackagesStatus
    
    hash = fields.String(
        data_key="hash",
        allow_none=True,
        load_default=None,
    )
    installed = fields.List(
        fields.String(),
        data_key="installed",
        allow_none=True,
        load_default=None,
    )
    cache_mode = fields.String(
        data_key="cacheMode",
        allow_none=True,
        load_default=None,
    )
    last_install_time = fields.String(
        data_key="lastInstallTime",
        allow_none=True,
        load_default=None,
    )
    install_duration = fields.String(
        data_key="installDuration",
        allow_none=True,
        load_default=None,
    )
    installed_by = fields.String(
        data_key="installedBy",
        allow_none=True,
        load_default=None,
    )
    warnings = fields.List(
        fields.String(),
        data_key="warnings",
        allow_none=True,
        load_default=None,
    )
