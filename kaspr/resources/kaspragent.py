import kopf
import time
from typing import List, Dict, Optional
from kaspr.utils.objects import cached_property
from kaspr.types.models import KasprAgentSpec
from kaspr.types.schemas import KasprAgentSpecSchema
from kaspr.types.models import KasprAgentResources

from kubernetes.client import (
    AppsV1Api,
    CoreV1Api,
    V1ObjectMeta,
    V1ConfigMap,
    V1EnvVar,
    V1EnvVarSource,
    V1ConfigMapKeySelector,
)

from kaspr.resources.base import BaseResource
from kaspr.common.models.labels import Labels


class KasprAgent(BaseResource):
    """Kaspr App kubernetes resource."""

    KIND = "KasprAgent"
    COMPONENT_TYPE = "agent"
    KASPR_APP_NAME_LABEL = "kaspr.io/app"

    config_map_name: str
    spec: KasprAgentSpec

    # derived from spec
    _config_hash: str = None
    _json_str: str = None

    # k8s resources
    _apps_v1_api: AppsV1Api = None
    _core_v1_api: CoreV1Api = None
    _config_map: V1ConfigMap = None

    def __init__(
        self,
        name: str,
        kind: str,
        namespace: str,
        component_type: str,
        labels: Optional[Dict[str, str]] = None,
    ):
        component_name = KasprAgentResources.component_name(name)
        _labels = Labels.generate_default_labels(
            name,
            kind,
            component_name,
            component_type,
            self.KASPR_OPERATOR_NAME,
        )
        _labels.update(labels)
        _labels.exclude(Labels.KASPR_CLUSTER_LABEL)
        super().__init__(
            cluster=name,
            namespace=namespace,
            component_name=component_name,
            labels=_labels,
        )

    @classmethod
    def from_spec(
        self,
        name: str,
        kind: str,
        namespace: str,
        spec: KasprAgentSpec,
        labels: Dict[str, str],
    ) -> "KasprAgent":
        agent = KasprAgent(name, kind, namespace, self.KIND, labels)
        agent.spec = spec
        agent.config_map_name = KasprAgentResources.agent_config_name(name)
        return agent

    def patch_config_map(self):
        """Update resources as a result of app settings change."""
        self.patch_config_map(
            self.core_v1_api,
            self.config_map_name,
            self.namespace,
            self.config_map,
        )

    def prepare_json_str(self) -> str:
        """Prepare json string for agent config map data."""
        return KasprAgentSpecSchema().dumps(self.spec)

    def prepare_config_map(self) -> V1ConfigMap:
        """Prepare config map for agent."""
        return V1ConfigMap(
            api_version="v1",
            kind="ConfigMap",
            metadata=V1ObjectMeta(
                name=self.config_map_name,
                namespace=self.namespace,
                labels=self.labels.as_dict(),
            ),
            data={
                f"{self.component_name}.json": self.json_str,
            },
        )

    def create(self):
        """Create agent resources."""
        # we can remove this once validation admission is implemented
        if not self.app_name:
            raise kopf.PermanentError(
                f"Missing required label: {self.KASPR_APP_NAME_LABEL}"
            )
        self.unite()
        self.create_config_map(self.core_v1_api, self.namespace, self.config_map)

    def unite(self):
        """Ensure all child resources are owned by the root resource"""
        children = [self.config_map]
        kopf.adopt(children)

    @cached_property
    def core_v1_api(self) -> CoreV1Api:
        if self._core_v1_api is None:
            self._core_v1_api = CoreV1Api()
        return self._core_v1_api

    @cached_property
    def app_name(self):
        return self.labels.get(self.KASPR_APP_NAME_LABEL)

    @cached_property
    def config_map(self) -> V1ConfigMap:
        if self._config_map is None:
            self._config_map = self.prepare_config_map()
        return self._config_map

    @cached_property
    def config_hash(self) -> str:
        if self._config_hash is None:
            self._config_hash = self.compute_hash(self.config_map.data)
        return self._config_hash

    @cached_property
    def json_str(self) -> str:
        if self._json_str is None:
            self._json_str = self.prepare_json_str()
        return self._json_str
