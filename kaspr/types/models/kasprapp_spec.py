from typing import Optional
from kaspr.types.base import BaseModel
from kaspr.types.models.tls import ClientTls
from kaspr.types.models.authentication import KafkaClientAuthentication
from kaspr.types.models.config import KasprAppConfig
from kaspr.types.models.storage import KasprAppStorage
from kaspr.types.models.resource_requirements import ResourceRequirements
from kaspr.types.models.probe import Probe

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
