from typing import Mapping
from kaspr.types.base import BaseModel


class MetadataTemplate(BaseModel):
    #: Labels added to the Kubernetes resource.
    labels: Mapping[str, str]
    #: Annotations added to the Kubernetes resource.
    annotations: Mapping[str, str]

class ResourceTemplate(BaseModel):
    #: Metadata applied to the resource.
    metadata: MetadataTemplate
