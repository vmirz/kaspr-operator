from typing import Optional, Dict, List, Any
from kaspr.types.base import BaseModel

class ConfigMapKeySelector(BaseModel):
    key: str
    name: str
    optional: Optional[bool] 

class SecretKeySelector(BaseModel):
    key: str
    name: str
    optional: Optional[bool] 

class FieldRefSelector(BaseModel):
    field_path: str
    api_version: Optional[str]
    
class ContainerEnvVarSource(BaseModel):
    config_map_key_ref: Optional[ConfigMapKeySelector]
    secret_key_ref: Optional[SecretKeySelector]
    field_ref: Optional[FieldRefSelector]

class ContainerEnvVar(BaseModel):
    name: str
    value: Optional[str] 
    value_from: Optional[ContainerEnvVarSource]
    
class VolumeMount(BaseModel):
    name: str
    mount_path: str
    sub_path: Optional[str]
    read_only: Optional[bool]
    mount_propagation: Optional[str]
    sub_path_expr: Optional[str]

class ContainerTemplate(BaseModel):
    env: Optional[List[ContainerEnvVar]]
    volume_mounts: Optional[List[VolumeMount]]
    security_context: Optional[Dict[str, Any]]
