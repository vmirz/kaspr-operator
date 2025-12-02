"""Python packages schemas for validation."""

from marshmallow import fields, validates, ValidationError
from kaspr.types.base import BaseSchema
from kaspr.types.models.python_packages import (
    PythonPackagesCache,
    PythonPackagesInstallPolicy,
    PythonPackagesResources,
    PythonPackagesSpec,
    PythonPackagesStatus,
)


class PythonPackagesCacheSchema(BaseSchema):
    """Schema for Python packages cache configuration."""
    
    __model__ = PythonPackagesCache
    
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
    
    @validates("access_mode")
    def validate_access_mode(self, value):
        """Validate access mode is ReadWriteMany (only supported mode)."""
        if value is not None and value != "ReadWriteMany":
            raise ValidationError(
                f"Invalid access mode: {value}. Only 'ReadWriteMany' is currently supported for shared package cache."
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


class PythonPackagesSpecSchema(BaseSchema):
    """Schema for Python packages specification."""
    
    __model__ = PythonPackagesSpec
    
    packages = fields.List(
        fields.String(),
        data_key="packages",
        required=True,
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
