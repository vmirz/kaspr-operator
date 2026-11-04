from typing import Any, Dict, Set
from kaspr.types.models import KasprJoinSpec, KasprJoinResources
from kaspr.utils.objects import cached_property
from kaspr.resources.appcomponent import BaseAppComponent
from kaspr.resources.definitions import BUNDLE, DELIVERY_ANNOTATION
from kaspr.types.models import KasprAppComponents

NOT_DELIVERED = "NotDelivered"
LEFT_TABLE_FOUND = "LeftTableFound"
LEFT_TABLE_NOT_FOUND = "LeftTableNotFound"
RIGHT_TABLE_FOUND = "RightTableFound"
RIGHT_TABLE_NOT_FOUND = "RightTableNotFound"


class KasprJoin(BaseAppComponent):
    """Kaspr Key Join kubernetes resource."""

    KIND = "KasprJoin"
    COMPONENT_TYPE = "join"
    PLURAL_NAME = "kasprjoins"
    kaspr_resource = KasprJoinResources
    # A join reaches its app's pods only inside the app's definitions bundle.
    WRITES_CONFIG_MAP = False

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

    async def synchronize(self):
        """A join has no ConfigMap of its own."""

    def not_delivered_message(self) -> str:
        """Why the join does not reach the pods of an app that does not deliver bundles."""
        return (
            f"Not delivered to the pods of KasprApp `{self.app_name}`: KasprJoins need "
            f"definitions bundle delivery (annotate the KasprApp `{DELIVERY_ANNOTATION}: {BUNDLE}`)."
        )

    def tables_status(self, app_tables: Set[str]) -> Dict[str, Any]:
        """Whether the join's tables belong to its app, by KasprTable name."""
        return {
            "leftTable": {
                "name": self.spec.left_table,
                "status": LEFT_TABLE_FOUND if self.spec.left_table in app_tables else LEFT_TABLE_NOT_FOUND,
            },
            "rightTable": {
                "name": self.spec.right_table,
                "status": RIGHT_TABLE_FOUND if self.spec.right_table in app_tables else RIGHT_TABLE_NOT_FOUND,
            },
        }
