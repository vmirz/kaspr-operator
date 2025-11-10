"""
Override for kopf._cogs.helpers.thirdparty module to support kubernetes_asyncio.

This override can be removed once https://github.com/nolar/kopf/pull/809 is merged
and released in a new version of Kopf. Once that happens, we can go back to launching
the application via kopf module directly (e.g. `kopf run kaspr/app.py`).

This module MUST be imported before any Kopf imports to patch Kopf's internal
thirdparty detection to recognize kubernetes_asyncio models alongside the standard
kubernetes client models.

The patch works by replacing the kopf._cogs.helpers.thirdparty module in sys.modules
before Kopf's internal imports load it.
"""
import abc
import sys
from typing import Any, Optional


def patch_kopf_thirdparty():
    """Patch Kopf's thirdparty detection before it loads."""
    
    # Check if already patched
    if 'kopf._cogs.helpers.thirdparty' in sys.modules:
        existing = sys.modules['kopf._cogs.helpers.thirdparty']
        if hasattr(existing, '_kaspr_patched'):
            return  # Already patched by us
        
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
    thirdparty_module._kaspr_patched = True  # Mark as patched
    
    # Force replace in sys.modules
    sys.modules['kopf._cogs.helpers.thirdparty'] = thirdparty_module
    
    print("[kaspr] Applied Kopf thirdparty patch for kubernetes_asyncio support")


# Apply immediately when imported
patch_kopf_thirdparty()
