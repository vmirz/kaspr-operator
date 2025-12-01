import kaspr
import mmh3
import hashlib
from typing import Any, List, Dict, Union
from kaspr.utils.objects import cached_property
from kaspr.utils.helpers import canonicalize_dict
from kaspr.common.models.labels import Labels
from kaspr.common.models.version import Version
from kaspr.utils.errors import already_exists_error
from kubernetes_asyncio.client import (
    ApiException,
    V1ResourceRequirements,
    V1Probe,
    V1Container,
    V1ServiceAccount,
    CoreV1Api,
    CustomObjectsApi,
    V1Service,
    AppsV1Api,
    AutoscalingV2Api,
    V1StatefulSet,
    V1ConfigMap,
    V1PersistentVolumeClaim,
    V1DeleteOptions,
    V2HorizontalPodAutoscaler,
    V1PodList
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
        """Compute a murmur3 hash."""
        if isinstance(data, dict):
            _data = canonicalize_dict(data)
        elif isinstance(data, str):
            _data = data.encode()
        else:
            raise ValueError(f"Hash of {type(data)} is not supporetd.")        
        # Compute the hash by encoding the string to bytes.
        mumur_str = str(mmh3.hash128(_data))

        # Compute SHA-256 hash
        hash_obj = hashlib.sha256(mumur_str.encode('utf-8'))
        full_hash = hash_obj.hexdigest()
        
        # Return first 16 characters for readability in labels/annotations
        return full_hash[:16]        
    
    def prepare_hash_annotation(self, hash: Union[str, int]) -> Dict[str, str]:
        """Prepare hash annotation for k8s resources."""
        return {"kaspr.io/resource-hash": str(hash)}

    async def fetch_service(
        self, core_v1_api: CoreV1Api, name: str, namespace: str
    ) -> V1Service:
        """Retrieve the latest state of a service"""
        try:
            return await core_v1_api.read_namespaced_service(name=name, namespace=namespace)
        except ApiException as ex:
            if ex.status == 404:
                return None
            raise

    async def create_service(
        self, core_v1_api: CoreV1Api, namespace: str, service: V1Service
    ) -> None:
        try:
            await core_v1_api.create_namespaced_service(namespace=namespace, body=service)
        except ApiException as ex:
            if already_exists_error(ex):
                await self.replace_service(
                    core_v1_api,
                    name=service.metadata.name,
                    namespace=namespace,
                    service=service,
                )
            else:
                raise

    async def replace_service(
        self, core_v1_api: CoreV1Api, name: str, namespace: str, service: V1Service
    ):
        await core_v1_api.replace_namespaced_service(
            name=name,
            namespace=namespace,
            body=service,
        )

    async def patch_service(
        self, core_v1_api: CoreV1Api, name: str, namespace: str, service: V1Service
    ):
        await core_v1_api.patch_namespaced_service(
            name=name,
            namespace=namespace,
            body=service,
        )

    async def fetch_service_account(
        self, core_v1_api: CoreV1Api, name: str, namespace: str
    ) -> V1ServiceAccount:
        try:
            return await core_v1_api.read_namespaced_service_account(
                name=name, namespace=namespace
            )
        except ApiException as ex:
            if ex.status == 404:
                return None
            raise

    async def create_service_account(
        self, core_v1_api: CoreV1Api, namespace: str, service_account: V1ServiceAccount
    ) -> None:
        try:
            await core_v1_api.create_namespaced_service_account(
                namespace=namespace, body=service_account
            )
        except ApiException as ex:
            if already_exists_error(ex):
                await self.replace_service_account(
                    core_v1_api,
                    name=service_account.metadata.name,
                    namespace=namespace,
                    service_account=service_account,
                )
            else:
                raise

    async def replace_service_account(
        self,
        core_v1_api: CoreV1Api,
        name: str,
        namespace: str,
        service_account: V1ServiceAccount,
    ) -> None:
        await core_v1_api.replace_namespaced_service_account(
            name=name,
            namespace=namespace,
            body=service_account,
        )

    async def patch_service_account(
        self,
        core_v1_api: CoreV1Api,
        name: str,
        namespace: str,
        service_account: V1ServiceAccount,
    ) -> None:
        await core_v1_api.patch_namespaced_service_account(
            name=name,
            namespace=namespace,
            body=service_account,
        )

    async def fetch_stateful_set(
        self, apps_v1_api: AppsV1Api, name: str, namespace: str
    ) -> V1StatefulSet:
        try:
            return await apps_v1_api.read_namespaced_stateful_set(name=name, namespace=namespace)
        except ApiException as ex:
            if ex.status == 404:
                return None
            raise

    async def create_stateful_set(
        self,
        apps_v1_api: AppsV1Api,
        namespace: str,
        stateful_set: V1StatefulSet,
    ):
        try:
            # Create the Statefulset in default namespace
            await apps_v1_api.create_namespaced_stateful_set(
                namespace=namespace, body=stateful_set
            )
        except ApiException as ex:
            if already_exists_error(ex):
                await self.replace_stateful_set(
                    apps_v1_api,
                    name=stateful_set.metadata.name,
                    namespace=namespace,
                    stateful_set=stateful_set,
                )
            else:
                raise

    async def replace_stateful_set(
        self,
        apps_v1_api: AppsV1Api,
        name: str,
        namespace: str,
        stateful_set: V1StatefulSet,
    ):
        await apps_v1_api.replace_namespaced_stateful_set(
            name=name, namespace=namespace, body=stateful_set
        )

    async def patch_stateful_set(
        self,
        apps_v1_api: AppsV1Api,
        name: str,
        namespace: str,
        stateful_set: V1StatefulSet,
    ):
        await apps_v1_api.patch_namespaced_stateful_set(
            name=name, namespace=namespace, body=stateful_set
        )

    async def delete_stateful_set(
        self,
        apps_v1_api: AppsV1Api,
        name: str,
        namespace: str,
        delete_options: V1DeleteOptions,
    ):
        try:
            await apps_v1_api.delete_namespaced_stateful_set(name, namespace, body=delete_options)
        except ApiException as ex:
            if ex.status == 404:
                return
            raise

    async def fetch_secret(
        self, core_v1_api: CoreV1Api, name: str, namespace: str
    ) -> V1Service:
        return await core_v1_api.read_namespaced_secret(name=name, namespace=namespace)
    
    async def fetch_config_map(
        self, core_v1_api: CoreV1Api, name: str, namespace: str
    ) -> V1ConfigMap:
        try:
            return await core_v1_api.read_namespaced_config_map(name=name, namespace=namespace)
        except ApiException as ex:
            if ex.status == 404:
                return None
            raise

    async def create_config_map(
        self, core_v1_api: CoreV1Api, namespace: str, config_map: V1ConfigMap
    ):
        try:
            await core_v1_api.create_namespaced_config_map(
                namespace=namespace, body=config_map
            )
        except ApiException as ex:
            if already_exists_error(ex):
                await self.replace_config_map(
                    core_v1_api,
                    name=config_map.metadata.name,
                    namespace=namespace,
                    config_map=config_map,
                )
            else:
                raise

    async def replace_config_map(
        self, core_v1_api: CoreV1Api, name: str, namespace: str, config_map: V1ConfigMap
    ):
        await core_v1_api.replace_namespaced_config_map(
            name=name,
            namespace=namespace,
            body=config_map,
        )

    async def patch_config_map(
        self, core_v1_api: CoreV1Api, name: str, namespace: str, config_map: V1ConfigMap
    ):
        await core_v1_api.patch_namespaced_config_map(
            name=name,
            namespace=namespace,
            body=config_map,
        )

    async def create_persistent_volume_claim(
        self,
        core_v1_api: CoreV1Api,
        namespace: str,
        pvc: V1PersistentVolumeClaim,
    ):
        try:
            await core_v1_api.create_namespaced_persistent_volume_claim(
                namespace=namespace, body=pvc
            )
        except ApiException as ex:
            if already_exists_error(ex):
                await self.replace_persistent_volume_claim(
                    core_v1_api,
                    name=pvc.metadata.name,
                    namespace=namespace,
                    pvc=pvc,
                )
            else:
                raise
        
    async def fetch_persistent_volume_claim(
        self, core_v1_api: CoreV1Api, name: str, namespace: str
    ) -> V1PersistentVolumeClaim:
        try:
            return await core_v1_api.read_namespaced_persistent_volume_claim(
                name=name, namespace=namespace
            )
        except ApiException as ex:
            if ex.status == 404:
                return None
            raise
    
    async def replace_persistent_volume_claim(
        self,
        core_v1_api: CoreV1Api,
        name: str,
        namespace: str,
        pvc: V1PersistentVolumeClaim,
    ):
        await core_v1_api.replace_namespaced_persistent_volume_claim(
            name=name,
            namespace=namespace,
            body=pvc,
        )

    async def list_persistent_volume_claims(
        self, core_v1_api: CoreV1Api, namespace: str
    ) -> List[V1PersistentVolumeClaim]:
        return await core_v1_api.list_namespaced_persistent_volume_claim(namespace=namespace)

    async def patch_persistent_volume_claim(
        self,
        core_v1_api: CoreV1Api,
        name: str,
        namespace: str,
        pvc: V1PersistentVolumeClaim,
    ):
        await core_v1_api.patch_namespaced_persistent_volume_claim(
            name=name,
            namespace=namespace,
            body=pvc,
        )

    async def delete_persistent_volume_claim(
        self,
        core_v1_api: CoreV1Api,
        name: str,
        namespace: str,
    ):
        """Delete a PersistentVolumeClaim.
        
        Args:
            core_v1_api: CoreV1Api instance
            name: Name of the PVC to delete
            namespace: Namespace containing the PVC
        """
        try:
            await core_v1_api.delete_namespaced_persistent_volume_claim(
                name=name,
                namespace=namespace,
                body=V1DeleteOptions(),
            )
        except ApiException as ex:
            if ex.status == 404:
                # PVC already deleted, ignore
                return
            raise

    async def get_custom_object(
        self,
        custom_objects_api: CustomObjectsApi,
        namespace: str,
        group: str,
        version: str,
        plural: str,
        name: str,
    ):
        try:
            return await custom_objects_api.get_namespaced_custom_object(
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

    async def list_custom_objects(
        self,
        custom_objects_api: CustomObjectsApi,
        namespace: str,
        group: str,
        version: str,
        plural: str,
        label_selector: str = None,
    ):
        return await custom_objects_api.list_namespaced_custom_object(
            group=group,
            version=version,
            namespace=namespace,
            plural=plural,
            label_selector=label_selector,
        )
    
    async def fetch_hpa(
        self, autoscaling_v2_api: AutoscalingV2Api, name: str, namespace: str
    ) -> V2HorizontalPodAutoscaler:
        try:
            return await autoscaling_v2_api.read_namespaced_horizontal_pod_autoscaler(name=name, namespace=namespace)
        except ApiException as ex:
            if ex.status == 404:
                return None
            raise

    async def create_hpa(
        self,
        autoscaling_v2_api: AutoscalingV2Api,
        namespace: str,
        hpa: V2HorizontalPodAutoscaler,
    ):
        try:
            await autoscaling_v2_api.create_namespaced_horizontal_pod_autoscaler(
                namespace=namespace, body=hpa
            )
        except ApiException as ex:
            if already_exists_error(ex):
                await self.replace_hpa(
                    autoscaling_v2_api,
                    name=hpa.metadata.name,
                    namespace=namespace,
                    hpa=hpa,
                )
            else:
                raise

    async def replace_hpa(
        self,
        autoscaling_v2_api: AutoscalingV2Api,
        name: str,
        namespace: str,
        hpa: V2HorizontalPodAutoscaler,
    ):
        await autoscaling_v2_api.replace_namespaced_horizontal_pod_autoscaler(
            name=name, namespace=namespace, body=hpa
        )

    async def patch_hpa(
        self,
        autoscaling_v2_api: AutoscalingV2Api,
        name: str,
        namespace: str,
        hpa: V2HorizontalPodAutoscaler,
    ):
        await autoscaling_v2_api.patch_namespaced_horizontal_pod_autoscaler(
            name=name, namespace=namespace, body=hpa
        )

    async def delete_hpa(
        self,
        autoscaling_v2_api: AutoscalingV2Api,
        name: str,
        namespace: str
    ):
        try:
            await autoscaling_v2_api.delete_namespaced_horizontal_pod_autoscaler(name, namespace)
        except ApiException as ex:
            if ex.status == 404:
                return
            raise
    
    async def delete_pod(
        self,
        core_v1_api: CoreV1Api,
        name: str,
        namespace: str,
        delete_options: V1DeleteOptions = None
    ):
        """Delete a pod.
        
        Args:
            core_v1_api: CoreV1Api instance
            name: Name of the pod to delete
            namespace: Namespace of the pod
            delete_options: Optional delete options (e.g., grace period, propagation policy)
        """
        try:
            await core_v1_api.delete_namespaced_pod(
                name=name,
                namespace=namespace,
                body=delete_options
            )
        except ApiException as ex:
            if ex.status == 404:
                return
            raise

    async def list_pods(
        self, core_v1_api: CoreV1Api, namespace: str, label_selector: dict = None
    ) -> List[V1PodList]:
        """List pods in namespace, optionally filtered by label selector.
        
        Args:
            core_v1_api: CoreV1Api instance
            namespace: Namespace to list pods in
            label_selector: Dictionary of label key-value pairs to filter pods
            
        Returns:
            V1PodList object containing matching pods
        """
        # Convert label selector dict to string format
        label_selector_str = None
        if label_selector:
            label_selector_str = ",".join([f"{k}={v}" for k, v in label_selector.items()])
        
        return await core_v1_api.list_namespaced_pod(
            namespace=namespace,
            label_selector=label_selector_str
        )