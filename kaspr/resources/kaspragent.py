from typing import Dict
from kaspr.types.models import KasprAgentSpec, KasprAgentResources
from kaspr.utils.objects import cached_property
from kaspr.resources.appcomponent import BaseAppComponent
from kaspr.types.models import KasprAppComponents

class KasprAgent(BaseAppComponent):
    """Kaspr App kubernetes resource."""

    KIND = "KasprAgent"
    COMPONENT_TYPE = "agent"
    PLURAL_NAME = "kaspragents"
    kaspr_resource = KasprAgentResources

    spec: KasprAgentSpec

    @classmethod
    def from_spec(
        cls,
        name: str,
        kind: str,
        namespace: str,
        spec: KasprAgentSpec,
        labels: Dict[str, str] = None,
    ) -> "KasprAgent":
        agent = KasprAgent(name, kind, namespace, cls.KIND, labels)
        agent.spec = spec
        agent.spec.name = name
        agent.config_map_name = cls.kaspr_resource.config_name(name)
        agent.volume_mount_name = cls.kaspr_resource.volume_mount_name(name)
        return agent

    @classmethod
    def default(self) -> "KasprAgent":
        """Create a default KasprAgent resource."""
        return KasprAgent(
            name="default",
            kind=self.KIND,
            namespace=None,
            component_type=self.COMPONENT_TYPE,
        )
    
    @cached_property
    def app_components(self) -> KasprAppComponents:
        """Return the app components."""
        return KasprAppComponents(agents=[self.spec])
