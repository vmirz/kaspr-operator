from typing import Mapping, Optional
from kaspr.types.base import BaseModel


class MetadataTemplate(BaseModel):
    #: Labels added to the Kubernetes resource.
    labels: Optional[Mapping[str, str]]
    #: Annotations added to the Kubernetes resource.
    annotations: Optional[Mapping[str, str]]

class ResourceTemplate(BaseModel):
    #: Metadata applied to the resource.
    metadata: Optional[MetadataTemplate]
