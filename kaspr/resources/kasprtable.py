from typing import Dict
from kaspr.types.models import KasprTableSpec, KasprTableResources
from kaspr.resources.appcomponent import BaseAppComponent


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
