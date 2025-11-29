from typing import Optional
from kaspr.types.base import BaseModel
from kaspr.types.models.tls import ClientTls
from kaspr.types.models.authentication import KafkaClientAuthentication
from kaspr.types.models.config import KasprAppConfig
from kaspr.types.models.storage import KasprAppStorage
from kaspr.types.models.resource_requirements import ResourceRequirements
from kaspr.types.models.probe import Probe
from kaspr.types.models.resource_template import ResourceTemplate
from kaspr.types.models.pod_template import PodTemplate
from kaspr.types.models.service_template import ServiceTemplate
from kaspr.types.models.container_template import ContainerTemplate
from kaspr.types.models.python_packages import PythonPackagesSpec

class KasprAppTemplate(BaseModel):
    """KasprApp template"""
    service_account: Optional[ResourceTemplate]
    pod: Optional[PodTemplate]
    service: Optional[ServiceTemplate]
    kaspr_container: Optional[ContainerTemplate]

class KasprAppSpec(BaseModel):
    """KasprApp CRD spec"""

    version: Optional[str]
    replicas: Optional[str]
    image: Optional[str]
    bootstrap_servers: str
    tls: ClientTls
    authentication: KafkaClientAuthentication
    config: Optional[KasprAppConfig]
    resources: Optional[ResourceRequirements]
    liveness_probe: Probe
    readiness_probe: Probe
    storage: KasprAppStorage
    template: Optional[KasprAppTemplate]
    python_packages: Optional[PythonPackagesSpec]
