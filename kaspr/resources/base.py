import kaspr
import json
import hashlib
from typing import Any, List
from kaspr.utils.objects import cached_property
from kaspr.common.models.labels import Labels
from kaspr.common.models.version import Version
from kaspr.utils.errors import already_exists_error
from kubernetes.client import (
    ApiException,
    V1ResourceRequirements,
    V1Probe,
    V1Container,
    V1ServiceAccount,
    CoreV1Api,
    CustomObjectsApi,
    V1Service,
    AppsV1Api,
    V1StatefulSet,
    V1ConfigMap,
    V1PersistentVolumeClaim,
    V1DeleteOptions,
)


class BaseResource:
    """Base resource model."""

    KASPR_OPERATOR_NAME = "kaspr-operator"

    _cluster: str
    _namespace: str
    _component_name: str
    _labels: Labels

    _image: str

    # Container configuration
    resources: V1ResourceRequirements
    readiness_probe_options: V1Probe
    liveness_probe_options: V1Probe

    # # PodSecurityProvider
    # protected PodSecurityProvider securityProvider = PodSecurityProviderFactory.getProvider();

    # # Template configurations shared between all AbstractModel subclasses.
    # protected ResourceTemplate templateServiceAccount;
    templateContainer: V1Container

    def __init__(
        self, cluster: str, namespace: str, component_name: str, labels: Labels
    ):
        self._cluster = cluster
        self._namespace = namespace
        self._component_name = component_name
        self._labels = labels

    @property
    def cluster(self) -> str:
        return self._cluster

    @property
    def namespace(self) -> str:
        return self._namespace

    @property
    def component_name(self) -> str:
        return self._component_name

    @property
    def labels(self) -> Labels:
        return self._labels

    @property
    def image(self) -> str:
        return self._image

    @cached_property
    def operator_version(self) -> Version:
        return Version.from_str(kaspr.__version__)

    def generate_service_account(self) -> V1ServiceAccount:
        raise NotImplementedError()

    def compute_hash(self, data: Any) -> str:
        """Compute a hash of the config map data."""
        if isinstance(data, dict):
            hash_input = json.dumps(data, sort_keys=True).encode()
        elif isinstance(data, str):
            hash_input = data.encode()
        else:
            raise ValueError(f"Hash of {type(data)} is not supporetd.")
        return hashlib.sha256(hash_input).hexdigest()

    def fetch_service(
        self, core_v1_api: CoreV1Api, name: str, namespace: str
    ) -> V1Service:
        """Retrieve the latest state of a service"""
        return core_v1_api.read_namespaced_service(name=name, namespace=namespace)

    def create_service(
        self, core_v1_api: CoreV1Api, namespace: str, service: V1Service
    ) -> None:
        try:
            core_v1_api.create_namespaced_service(namespace=namespace, body=service)
        except ApiException as ex:
            if already_exists_error(ex):
                self.replace_service(
                    core_v1_api,
                    name=service.metadata.name,
                    namespace=namespace,
                    service=service,
                )
            else:
                raise

    def replace_service(
        self, core_v1_api: CoreV1Api, name: str, namespace: str, service: V1Service
    ):
        core_v1_api.replace_namespaced_service(
            name=name,
            namespace=namespace,
            body=service,
        )

    def patch_service(
        self, core_v1_api: CoreV1Api, name: str, namespace: str, service: V1Service
    ):
        core_v1_api.patch_namespaced_service(
            name=name,
            namespace=namespace,
            body=service,
        )

    def fetch_stateful_set(
        self, apps_v1_api: AppsV1Api, name: str, namespace: str
    ) -> V1StatefulSet:
        return apps_v1_api.read_namespaced_stateful_set(name=name, namespace=namespace)

    def create_stateful_set(
        self,
        apps_v1_api: AppsV1Api,
        namespace: str,
        stateful_set: V1StatefulSet,
    ):
        try:
            # Create the Statefulset in default namespace
            apps_v1_api.create_namespaced_stateful_set(
                namespace=namespace, body=stateful_set
            )
        except ApiException as ex:
            if already_exists_error(ex):
                self.patch_stateful_set(
                    apps_v1_api,
                    name=stateful_set.metadata.name,
                    namespace=namespace,
                    stateful_set=stateful_set,
                )
            else:
                raise

    def replace_stateful_set(
        self,
        apps_v1_api: AppsV1Api,
        name: str,
        namespace: str,
        stateful_set: V1StatefulSet,
    ):
        apps_v1_api.replace_namespaced_stateful_set(
            name=name, namespace=namespace, body=stateful_set
        )

    def patch_stateful_set(
        self,
        apps_v1_api: AppsV1Api,
        name: str,
        namespace: str,
        stateful_set: V1StatefulSet,
    ):
        apps_v1_api.patch_namespaced_stateful_set(
            name=name, namespace=namespace, body=stateful_set
        )

    def delete_stateful_set(
        self,
        apps_v1_api: AppsV1Api,
        name: str,
        namespace: str,
        delete_options: V1DeleteOptions,
    ):
        apps_v1_api.delete_namespaced_stateful_set(name, namespace, body=delete_options)

    def create_config_map(
        self, core_v1_api: CoreV1Api, namespace: str, config_map: V1ConfigMap
    ):
        try:
            core_v1_api.create_namespaced_config_map(
                namespace=namespace, body=config_map
            )
        except ApiException as ex:
            if already_exists_error(ex):
                self.replace_config_map(
                    core_v1_api,
                    name=config_map.metadata.name,
                    namespace=namespace,
                    config_map=config_map,
                )
            else:
                raise

    def replace_config_map(
        self, core_v1_api: CoreV1Api, name: str, namespace: str, config_map: V1ConfigMap
    ):
        core_v1_api.replace_namespaced_config_map(
            name=name,
            namespace=namespace,
            body=config_map,
        )

    def patch_config_map(
        self, core_v1_api: CoreV1Api, name: str, namespace: str, config_map: V1ConfigMap
    ):
        core_v1_api.patch_namespaced_config_map(
            name=name,
            namespace=namespace,
            body=config_map,
        )

    def list_persistent_volume_claims(
        self, core_v1_api: CoreV1Api, namespace: str
    ) -> List[V1PersistentVolumeClaim]:
        return core_v1_api.list_namespaced_persistent_volume_claim(namespace=namespace)

    def patch_persistent_volume_claim(
        self,
        core_v1_api: CoreV1Api,
        name: str,
        namespace: str,
        pvc: V1PersistentVolumeClaim,
    ):
        core_v1_api.patch_namespaced_persistent_volume_claim(
            name=name,
            namespace=namespace,
            body=pvc,
        )

    def get_custom_object(
        self,
        custom_objects_api: CustomObjectsApi,
        namespace: str,
        group: str,
        version: str,
        plural: str,
        name: str,
    ):
        try:
            return custom_objects_api.get_namespaced_custom_object(
                group=group,
                version=version,
                namespace=namespace,
                plural=plural,
                name=name,
            )
        except ApiException as ex:
            if ex.status == 404:
                return None
            raise

    def list_custom_objects(
        self,
        custom_objects_api: CustomObjectsApi,
        namespace: str,
        group: str,
        version: str,
        plural: str,
        label_selector: str = None,
    ):
        return custom_objects_api.list_namespaced_custom_object(
            group=group,
            version=version,
            namespace=namespace,
            plural=plural,
            label_selector=label_selector,
        )
