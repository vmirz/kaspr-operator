from typing import Optional, Dict, List
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
    empty_dir: Optional[Dict[str, str]]
    persistent_volume_claim: Optional[Dict[str, str]]
    csi: Optional[Dict[str, str]]


class PodTemplate(ResourceTemplate):
    image_pull_secrets: Optional[List[Dict[str, str]]]
    security_context: Optional[Dict[str, str]]
    termination_grace_period_seconds: Optional[int]
    affinity: Optional[Dict[str, str]]
    tolerations: Optional[List[Dict[str, str]]]
    topology_spread_constraints: Optional[List[Dict[str, str]]]
    priority_class_name: Optional[str]
    scheduler_name: Optional[str]
    host_aliases: Optional[List[Dict[str, str]]]
    enable_service_links: Optional[bool]
    volumes: Optional[List[AdditionalVolume]]
