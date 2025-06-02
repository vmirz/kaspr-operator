from typing import Optional, Dict, List, Any
from kaspr.types.base import BaseModel
from kaspr.types.models.resource_template import ResourceTemplate


class KeyToPath(BaseModel):
    key: str
    path: str
    mode: Optional[int]


class SecretVolumeSource(BaseModel):
    default_mode: Optional[int]
    optional: Optional[bool]
    secret_name: str
    items: Optional[List[KeyToPath]]


class ConfigMapVolumeSource(BaseModel):
    default_mode: Optional[int]
    optional: Optional[bool]
    name: str
    items: Optional[List[KeyToPath]]


class AdditionalVolume(BaseModel):
    name: str
    secret: Optional[SecretVolumeSource]
    config_map: Optional[ConfigMapVolumeSource]
    empty_dir: Optional[Dict[str, Any]]
    persistent_volume_claim: Optional[Dict[str, Any]]
    csi: Optional[Dict[str, Any]]


class PodTemplate(ResourceTemplate):
    image_pull_secrets: Optional[List[Dict[str, Any]]]
    security_context: Optional[Dict[str, Any]]
    termination_grace_period_seconds: Optional[int]
    node_selector: Optional[Dict[str, str]]
    affinity: Optional[Dict[str, Any]]
    tolerations: Optional[List[Dict[str, Any]]]
    topology_spread_constraints: Optional[List[Dict[str, Any]]]
    priority_class_name: Optional[str]
    scheduler_name: Optional[str]
    host_aliases: Optional[List[Dict[str, Any]]]
    enable_service_links: Optional[bool]
    volumes: Optional[List[AdditionalVolume]]
