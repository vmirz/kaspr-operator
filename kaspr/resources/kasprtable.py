from typing import Dict
from kaspr.types.models import KasprTableSpec, KasprTableResources
from kaspr.utils.objects import cached_property
from kaspr.resources.appcomponent import BaseAppComponent
from kaspr.types.models import KasprAppComponents


class KasprTable(BaseAppComponent):
    """KasprTable resource."""

    KIND = "KasprTable"
    COMPONENT_TYPE = "webview"
    PLURAL_NAME = "kasprtables"
    spec: KasprTableSpec

    @classmethod
    def from_spec(
        self,
        name: str,
        kind: str,
        namespace: str,
        spec: KasprTableSpec,
        labels: Dict[str, str] = None,
    ) -> "KasprTable":
        agent = KasprTable(name, kind, namespace, self.KIND, labels)
        agent.spec = spec
        agent.spec.name = name
        agent.config_map_name = KasprTableResources.config_name(name)
        agent.volume_mount_name = KasprTableResources.volume_mount_name(name)
        return agent

    @classmethod
    def default(self) -> "KasprTable":
        return KasprTable(
            name="default",
            kind=self.KIND,
            namespace=None,
            component_type=self.COMPONENT_TYPE,
        )

    @cached_property
    def component_name(self) -> str:
        """Return the component name."""
        return KasprTableResources.component_name(self.spec.name)

    @cached_property
    def app_components(self) -> KasprAppComponents:
        """Return the app components."""
        return KasprAppComponents(tables=[self.spec])