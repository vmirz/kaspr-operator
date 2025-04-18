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
    kaspr_resource = KasprTableResources

    spec: KasprTableSpec

    @classmethod
    def from_spec(
        cls,
        name: str,
        kind: str,
        namespace: str,
        spec: KasprTableSpec,
        labels: Dict[str, str] = None,
    ) -> "KasprTable":
        agent = KasprTable(name, kind, namespace, cls.KIND, labels)
        agent.spec = spec
        agent.spec.name = name
        agent.config_map_name = cls.kaspr_resource.config_name(name)
        agent.volume_mount_name = cls.kaspr_resource.volume_mount_name(name)
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
    def app_components(self) -> KasprAppComponents:
        """Return the app components."""
        return KasprAppComponents(tables=[self.spec])