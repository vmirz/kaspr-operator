import kopf
import yaml
import time
from typing import List, Dict, Optional
from kaspr.utils.objects import cached_property
from kaspr.utils.helpers import ordered_dict_to_dict
from kaspr.types.models import KasprAgentSpec, KasprAgentResources, KasprAppComponents
from kaspr.types.schemas import KasprAppComponentsSchema

from kubernetes.client import (
    AppsV1Api,
    CoreV1Api,
    CustomObjectsApi,
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
    GROUP_VERSION = "v1alpha1"
    COMPONENT_TYPE = "agent"
    KASPR_APP_NAME_LABEL = "kaspr.io/app"
    OUTPUT_TYPE = "yaml"

    config_map_name: str
    volume_mount_name: str
    spec: KasprAgentSpec

    # derived from spec
    _hash: str = None
    _json_str: str = None
    _yaml_str: str = None

    # k8s resources
    _apps_v1_api: AppsV1Api = None
    _core_v1_api: CoreV1Api = None
    _custom_objects_api: CustomObjectsApi = None
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
        _labels.update(labels or {})
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
        labels: Dict[str, str] = None,
    ) -> "KasprAgent":
        agent = KasprAgent(name, kind, namespace, self.KIND, labels)
        agent.spec = spec
        agent.spec.name = name
        agent.config_map_name = KasprAgentResources.agent_config_name(name)
        agent.volume_mount_name = KasprAgentResources.volume_mount_name(name)
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

    def fetch(self, name: str, namespace: str):
        """Fetch KasprAgent from kubernetes."""
        return self.get_custom_object(
            self.custom_objects_api,
            namespace=namespace,
            group="kaspr.io",
            version=self.GROUP_VERSION,
            plural="kaspragents",
            name=name,
        )

    def search(self, namespace: str, apps: List[str] = None):
        """Search for KasprAgents in kubernetes."""

        label_selector = (
            ",".join(f"kaspr.io/app={app}" for app in apps) if apps else None
        )
        return self.list_custom_objects(
            self.custom_objects_api,
            namespace=namespace,
            group="kaspr.io",
            version=self.GROUP_VERSION,
            plural="kaspragents",
            label_selector=label_selector,
        )

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
        return KasprAppComponentsSchema().dumps(self.wrap_components())

    def prepare_yaml_str(self) -> str:
        """Prepare yaml string for agent config map data."""
        components = KasprAppComponentsSchema().dump(self.wrap_components())
        components = ordered_dict_to_dict(components)
        return yaml.dump(
            components, default_flow_style=False
        )
    
    def wrap_components(self) -> KasprAppComponents:
        """Wrap agent spec in KasprAppComponents."""
        return KasprAppComponents(agents=[self.spec])

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
                self.file_name: self.file_data,
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

    def info(self) -> Dict:
        """Return agent info."""
        return {
            "name": self.cluster,
            "configMap": self.config_map_name,
            "hash": self.hash,
        }

    @cached_property
    def core_v1_api(self) -> CoreV1Api:
        if self._core_v1_api is None:
            self._core_v1_api = CoreV1Api()
        return self._core_v1_api

    @cached_property
    def custom_objects_api(self) -> CustomObjectsApi:
        if self._custom_objects_api is None:
            self._custom_objects_api = CustomObjectsApi()
        return self._custom_objects_api

    @cached_property
    def app_name(self):
        return self.labels.get(self.KASPR_APP_NAME_LABEL)

    @cached_property
    def config_map(self) -> V1ConfigMap:
        if self._config_map is None:
            self._config_map = self.prepare_config_map()
        return self._config_map

    @cached_property
    def hash(self) -> str:
        if self._hash is None:
            self._hash = self.compute_hash(self.config_map.data)
        return self._hash

    @cached_property
    def json_str(self) -> str:
        if self._json_str is None:
            self._json_str = self.prepare_json_str()
        return self._json_str

    @cached_property
    def yaml_str(self) -> str:
        if self._yaml_str is None:
            self._yaml_str = self.prepare_yaml_str()
        return self._yaml_str

    @cached_property
    def file_name(self) -> str:
        if self.OUTPUT_TYPE == "yaml":
            return f"{self.component_name}.yaml"
        else:
            return f"{self.component_name}.json"

    @cached_property
    def file_data(self) -> str:
        if self.OUTPUT_TYPE == "yaml":
            return self.yaml_str
        else:
            return self.json_str
