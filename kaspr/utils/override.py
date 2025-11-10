"""
Override for kopf._cogs.helpers.thirdparty module to support kubernetes_asyncio.
"""
import abc
import sys
from typing import Any, Optional

# Force early module replacement before Kopf can import it
def patch_kopf_thirdparty():
    """Patch Kopf's thirdparty detection before it loads."""
    
    # Create our custom implementation
    class _dummy:
        pass

    try:
        from pykube.objects import APIObject as APIObject
        PykubeObject = APIObject
    except ImportError:
        PykubeObject = _dummy

    try:
        from kubernetes_asyncio.client import (
            V1ObjectMeta as V1ObjectMeta,
            V1OwnerReference as V1OwnerReference,
        )
    except ImportError:
        V1ObjectMeta = V1OwnerReference = None

    class KubernetesModel(abc.ABC):
        @classmethod
        def __subclasshook__(cls, subcls: Any) -> Any:
            if cls is KubernetesModel:
                if any(
                    C.__module__.startswith("kubernetes.client.models.")
                    or C.__module__.startswith("kubernetes_asyncio.client.models.")
                    for C in subcls.__mro__
                ):
                    return True
            return NotImplemented

        @property
        def metadata(self) -> Optional[V1ObjectMeta]:
            raise NotImplementedError

        @metadata.setter
        def metadata(self, _: Optional[V1ObjectMeta]) -> None:
            raise NotImplementedError

    # Create the replacement module
    import types
    thirdparty_module = types.ModuleType('thirdparty')
    thirdparty_module.PykubeObject = PykubeObject
    thirdparty_module.KubernetesModel = KubernetesModel
    thirdparty_module.V1ObjectMeta = V1ObjectMeta
    thirdparty_module.V1OwnerReference = V1OwnerReference
    
    # Force replace in sys.modules
    sys.modules['kopf._cogs.helpers.thirdparty'] = thirdparty_module

# Apply immediately when imported
patch_kopf_thirdparty()