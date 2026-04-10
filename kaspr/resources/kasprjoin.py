from typing import Dict
from kaspr.types.models import KasprJoinSpec, KasprJoinResources
from kaspr.utils.objects import cached_property
from kaspr.resources.appcomponent import BaseAppComponent
from kaspr.types.models import KasprAppComponents


class KasprJoin(BaseAppComponent):
    """Kaspr Key Join kubernetes resource."""

    KIND = "KasprJoin"
    COMPONENT_TYPE = "join"
    PLURAL_NAME = "kasprjoins"
    kaspr_resource = KasprJoinResources

    spec: KasprJoinSpec

    @classmethod
    def from_spec(
        cls,
        name: str,
        kind: str,
        namespace: str,
        spec: KasprJoinSpec,
        labels: Dict[str, str] = None,
    ) -> "KasprJoin":
        join_resource = KasprJoin(name, kind, namespace, cls.KIND, labels)
        join_resource.spec = spec
        join_resource.spec.name = name
        join_resource.config_map_name = cls.kaspr_resource.config_name(name)
        join_resource.volume_mount_name = cls.kaspr_resource.volume_mount_name(name)
        return join_resource

    @classmethod
    def default(cls) -> "KasprJoin":
        """Create a default KasprJoin resource."""
        return KasprJoin(
            name="default",
            kind=cls.KIND,
            namespace=None,
            component_type=cls.COMPONENT_TYPE,
        )

    @cached_property
    def app_components(self) -> KasprAppComponents:
        """Return the app components."""
        return KasprAppComponents(joins=[self.spec])
