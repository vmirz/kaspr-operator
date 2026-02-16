"""Python packages models for KasprApp."""

from typing import Optional, List
from kaspr.types.base import BaseModel


class PythonPackagesCache(BaseModel):
    """Python packages cache configuration."""
    
    enabled: Optional[bool]
    storage_class: Optional[str]
    size: Optional[str]
    access_mode: Optional[str]
    delete_claim: Optional[bool]


class PythonPackagesInstallPolicy(BaseModel):
    """Installation behavior policy."""
    
    retries: Optional[int]
    timeout: Optional[int]
    on_failure: Optional[str]


class PythonPackagesResources(BaseModel):
    """Resource requirements for init container."""
    
    requests: Optional[dict]
    limits: Optional[dict]


class SecretReference(BaseModel):
    """Reference to a Kubernetes Secret."""

    name: str
    username_key: Optional[str]
    password_key: Optional[str]


class PythonPackagesCredentials(BaseModel):
    """PyPI authentication credentials."""

    secret_ref: SecretReference


class PythonPackagesSpec(BaseModel):
    """Python packages specification."""
    
    packages: List[str]
    index_url: Optional[str]
    extra_index_urls: Optional[List[str]]
    trusted_hosts: Optional[List[str]]
    credentials: Optional[PythonPackagesCredentials]
    cache: Optional[PythonPackagesCache]
    install_policy: Optional[PythonPackagesInstallPolicy]
    resources: Optional[PythonPackagesResources]


class PythonPackagesStatus(BaseModel):
    """Python packages status.
    """
    
    hash: Optional[str]
    installed: Optional[List[str]]
    cache_mode: Optional[str]
    last_install_time: Optional[str]
    install_duration: Optional[str]
    installed_by: Optional[str]
    warnings: Optional[List[str]]
