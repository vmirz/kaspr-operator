from typing import Dict
from kaspr.types.models import KasprTaskSpec, KasprTaskResources
from kaspr.utils.objects import cached_property
from kaspr.resources.appcomponent import BaseAppComponent
from kaspr.types.models import KasprAppComponents


class KasprTask(BaseAppComponent):
    """Kaspr Task kubernetes resource."""

    KIND = "KasprTask"
    COMPONENT_TYPE = "task"
    PLURAL_NAME = "kasprtasks"
    kaspr_resource = KasprTaskResources

    spec: KasprTaskSpec
    
    @classmethod
    def from_spec(
        cls,
        name: str,
        kind: str,
        namespace: str,
        spec: KasprTaskSpec,
        labels: Dict[str, str] = None,
    ) -> "KasprTask":
        agent = KasprTask(name, kind, namespace, cls.KIND, labels)
        agent.spec = spec
        agent.spec.name = name
        agent.config_map_name = cls.kaspr_resource.config_name(name)
        agent.volume_mount_name = cls.kaspr_resource.volume_mount_name(name)
        return agent

    @classmethod
    def default(self) -> "KasprTask":
        """Create a default KasprTask resource."""
        return KasprTask(
            name="default",
            kind=self.KIND,
            namespace=None,
            component_type=self.COMPONENT_TYPE,
        )

    @cached_property
    def app_components(self) -> KasprAppComponents:
        """Return the app components."""
        return KasprAppComponents(tasks=[self.spec])