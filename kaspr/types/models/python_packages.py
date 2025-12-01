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


class PythonPackagesSpec(BaseModel):
    """Python packages specification."""
    
    packages: List[str]
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
