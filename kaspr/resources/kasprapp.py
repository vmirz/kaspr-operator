import asyncio
import kopf
import time
import logging
from logging import Logger
from typing import List, Dict, Optional
from kaspr.utils.objects import cached_property
from kaspr.utils.helpers import now
from kaspr.types.settings import Settings
from kaspr.types.models.kasprapp_spec import KasprAppSpec
from kaspr.types.models.storage import KasprAppStorage
from kaspr.types.models.config import KasprAppConfig
from kaspr.types.models.tls import ClientTls
from kaspr.types.models.kasprapp_resources import (
    KasprAppResources,
)
from kaspr.types.models.version_resources import KasprVersion, KasprVersionResources
from kaspr.types.models.authentication import (
    SASLCredentials,
    KafkaClientAuthentication,
)
from kaspr.types.models.resource_requirements import ResourceRequirements
from kaspr.types.models.probe import Probe
from kaspr.types.models.resource_template import ResourceTemplate
from kaspr.types.models.pod_template import PodTemplate
from kaspr.types.models.service_template import ServiceTemplate
from kaspr.types.models.container_template import ContainerTemplate
from kaspr.types.models.python_packages import PythonPackagesSpec
from kaspr.utils.python_packages import generate_install_script
from kubernetes_asyncio.client import (
    AppsV1Api,
    CoreV1Api,
    CustomObjectsApi,
    AutoscalingV2Api,
    V1ObjectMeta,
    V1Service,
    V1ServiceSpec,
    V1ServicePort,
    V1StatefulSet,
    V1StatefulSetSpec,
    V1StatefulSetUpdateStrategy,
    V1LabelSelector,
    V1PodTemplateSpec,
    V1PodSpec,
    V1Container,
    V1ContainerPort,
    V1VolumeMount,
    V1Volume,
    V1ConfigMapVolumeSource,
    V1KeyToPath,
    V1PersistentVolumeClaimSpec,
    V1PersistentVolumeClaim,
    V1PersistentVolumeClaimTemplate,
    V1PersistentVolumeClaimVolumeSource,
    V1StatefulSetPersistentVolumeClaimRetentionPolicy,
    V1ConfigMap,
    V1EnvVar,
    V1EnvVarSource,
    V1ObjectFieldSelector,
    V1ConfigMapKeySelector,
    V1SecretKeySelector,
    V1ResourceRequirements,
    V1Probe,
    V1DeleteOptions,
    V1ServiceAccount,
    V1SecretVolumeSource,
    V2HorizontalPodAutoscaler,
    V2HorizontalPodAutoscalerSpec,
    V2CrossVersionObjectReference,
    V2MetricSpec,
    V2ResourceMetricSource,
    V2MetricTarget,
    V2HorizontalPodAutoscalerBehavior,
    V2HPAScalingRules,
    V2HPAScalingPolicy,
)
from kubernetes_asyncio.client.api_client import ApiClient

from kaspr.resources.base import BaseResource
from kaspr.resources import KasprAgent, KasprWebView, KasprTable, KasprTask
from kaspr.common.models.labels import Labels
from kaspr.web import KasprWebClient
from kaspr.sensors import SensorDelegate


class KasprApp(BaseResource):
    """Kaspr App kubernetes resource."""

    logger: Logger
    conf: Settings
    web_client: KasprWebClient
    sensor: SensorDelegate
    shared_api_client: ApiClient = None  # Shared across all KasprApp instances

    KIND = "KasprApp"
    GROUP_NAME = "kaspr.io"
    GROUP_VERSION = "v1alpha1"
    COMPONENT_TYPE = "app"
    PLURAL_NAME = "kasprapps"
    KASPR_APP_NAME_LABEL = "kaspr.io/app"
    WEB_PORT_NAME = "http"
    KASPR_CONTAINER_NAME = "kaspr"

    DEFAULT_REPLICAS = 1
    DEFAULT_DATA_DIR = "/var/lib/data"
    DEFAULT_TABLE_DIR = "/var/lib/data/tables"
    DEFAULT_DEFINITIONS_DIR = "/var/lib/data/definitions"
    DEFAULT_WEB_PORT = 6065
    INITIAL_MAX_REPLICAS = 1
    
    # Python packages defaults
    DEFAULT_PACKAGES_PVC_SIZE = "256Mi"
    DEFAULT_PACKAGES_CACHE_ENABLED = True
    DEFAULT_PACKAGES_ACCESS_MODE = "ReadWriteMany"
    DEFAULT_PACKAGES_DELETE_CLAIM = True
    DEFAULT_PACKAGES_INSTALL_RETRIES = 3
    DEFAULT_PACKAGES_INSTALL_TIMEOUT = 600

    replicas: int
    image: str
    service_name: str
    headless_service_name: str
    service_account_name: str
    config_map_name: str
    persistent_volume_claim_name: str
    stateful_set_name: str
    bootstrap_servers: str
    hpa_name: str

    annotations: Dict[str, str] = None

    # CRD spec models
    tls: Optional[ClientTls]
    authentication: KafkaClientAuthentication
    config: KasprAppConfig
    resources: Optional[ResourceRequirements]
    liveness_probe: Probe
    readiness_probe: Probe
    storage: KasprAppStorage
    python_packages: Optional[PythonPackagesSpec]

    # derived from spec
    _env_dict: Dict[str, str] = None
    _config_hash: str = None
    _version: str = None
    _image: str = None

    # k8s resources
    _api_client: ApiClient = None
    _apps_v1_api: AppsV1Api = None
    _core_v1_api: CoreV1Api = None
    _custom_objects_api: CustomObjectsApi = None
    _autoscaling_v2_api: AutoscalingV2Api = None
    _service: V1Service = None
    _service_hash: str = None
    _headless_service: V1Service = None
    _headless_service_hash: str = None
    _service_account: V1ServiceAccount = None
    _service_account_hash: str = None
    _persistent_volume_claim: V1PersistentVolumeClaim = None
    _persistent_volume_claim_hash: str = None
    _persistent_volume_claim_retention_policy: V1StatefulSetPersistentVolumeClaimRetentionPolicy = None
    _packages_pvc: V1PersistentVolumeClaim = None
    _packages_pvc_hash: str = None
    _packages_pvc_name: str = None
    _packages_init_container: V1Container = None
    _settings_config_map: V1ConfigMap = None
    _settings_config_map_hash: str = None
    _env_vars: List[V1EnvVar] = None
    _volume_mounts: List[V1VolumeMount] = None
    _volumes: List[V1Volume] = None
    _container_ports: List[V1ContainerPort] = None
    _stateful_set: V1StatefulSet = None
    _stateful_set_hash: str = None
    _hpa_hash: str = None
    _kaspr_container: V1Container = None
    _pod_template: V1PodTemplateSpec = None
    _pod_spec: V1PodSpec = None
    _agent_pod_volumes: List[V1Volume] = None
    _webview_pod_volumes: List[V1Volume] = None
    _table_pod_volumes: List[V1Volume] = None
    _task_pod_volumes: List[V1Volume] = None
    _hpa: V2HorizontalPodAutoscaler = None

    # Reference to agent resources
    agents: List[KasprAgent] = None
    webviews: List[KasprWebView] = None
    tables: List[KasprTable] = None
    tasks: List[KasprTask] = None
    _webviews_hash: str = None
    _agents_hash: str = None
    _tables_hash: str = None
    _tasks_hash: str = None
    _packages_hash: str = None

    # TODO: Templates allow customizing k8s behavior
    template_service_account: ResourceTemplate
    template_pod: PodTemplate
    template_service: ServiceTemplate
    template_container: ContainerTemplate

    # PodDisruptionBudgetTemplate templatePodDisruptionBudget;
    # ResourceTemplate templateInitClusterRoleBinding;
    # DeploymentTemplate templateDeployment;
    # ResourceTemplate templatePodSet;
    # PodTemplate templatePod;
    # InternalServiceTemplate templateService;
    # InternalServiceTemplate templateHeadlessService;
    # ContainerTemplate templateInitContainer;

    def __init__(
        self,
        name: str,
        kind: str,
        namespace: str,
        component_type: str,
        labels: Optional[Dict[str, str]] = None,
    ):
        component_name = KasprAppResources.component_name(name)
        _labels = Labels.generate_default_labels(
            name,
            kind,
            component_name,
            component_type,
            self.KASPR_OPERATOR_NAME,
        )
        _labels.update(labels or {})
        _labels.update({self.KASPR_APP_NAME_LABEL: name})
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
        spec: KasprAppSpec,
        annotations: Optional[Dict[str, str]] = None,
        logger: Logger = None,
    ) -> "KasprApp":
        app = KasprApp(name, kind, namespace, self.KIND)
        app.logger = logger or logging.getLogger(__name__)
        app.annotations = annotations
        app.service_name = KasprAppResources.service_name(name)
        app.headless_service_name = KasprAppResources.headless_service_name(name)
        app.service_account_name = KasprAppResources.service_account_name(name)
        app.config_map_name = KasprAppResources.settings_config_name(name)
        app.stateful_set_name = KasprAppResources.stateful_set_name(name)
        app.persistent_volume_claim_name = (
            KasprAppResources.persistent_volume_claim_name(name)
        )
        app.hpa_name = KasprAppResources.hpa_name(name)
        app._version = spec.version
        app._image = spec.image
        app.replicas = (
            spec.replicas if spec.replicas is not None else self.DEFAULT_REPLICAS
        )
        app.bootstrap_servers = spec.bootstrap_servers
        app.tls = spec.tls
        app.authentication = spec.authentication
        app.config = spec.config
        app.resources = spec.resources
        app.liveness_probe = spec.liveness_probe
        app.readiness_probe = spec.readiness_probe
        app.storage = spec.storage
        app.python_packages = spec.python_packages if hasattr(spec, 'python_packages') else None
        app.template_service_account = spec.template.service_account
        app.template_pod = spec.template.pod
        app.template_service = spec.template.service
        app.template_container = spec.template.kaspr_container
        return app

    @classmethod
    def default(self) -> "KasprApp":
        """Create a default KasprApp resource."""
        return KasprApp(
            name="default",
            kind=self.KIND,
            namespace=None,
            component_type=self.COMPONENT_TYPE,
        )

    async def synchronize(self) -> "KasprApp":
        """Compare current state with desired state for all child resources and create/patch as needed."""
        await self.sync_auth_credentials()
        await self.sync_service()
        await self.sync_headless_service()
        await self.sync_service_account()
        await self.sync_settings_config_map()
        await self.sync_python_packages_pvc()
        await self.sync_hpa()
        await self.sync_stateful_set()

    async def sync_service(self):
        """Check current state of service and create/patch if needed."""
        service: V1Service = await self.fetch_service(
            self.core_v1_api, self.service_name, self.namespace
        )
        if not service:
            # Instrument create operation
            sensor_state = self.sensor.on_resource_sync_start(
                self.cluster, self.cluster, self.service.metadata.name, self.namespace, "service"
            )
            
            success = True
            try:
                await self.create_service(self.core_v1_api, self.namespace, self.service)
            except Exception:
                success = False
                raise
            finally:
                self.sensor.on_resource_sync_complete(
                    self.cluster, self.cluster, self.service.metadata.name, self.namespace, "service", sensor_state, "create", success
                )
        else:
            actual = self.prepare_service_watch_fields(service)
            desired = self.prepare_service_watch_fields(self.service)
            actual_hash = self.compute_hash(actual)
            desired_hash = self.compute_hash(desired)
            
            if actual_hash != desired_hash:
                # Detect drift
                self.sensor.on_resource_drift_detected(
                    self.cluster, self.cluster, self.service.metadata.name, self.namespace, "service", ["spec"]
                )
                
                # Instrument patch operation
                sensor_state = self.sensor.on_resource_sync_start(
                    self.cluster, self.cluster, self.service.metadata.name, self.namespace, "service"
                )
                
                success = True
                try:
                    await self.patch_service(
                        self.core_v1_api,
                        self.service_name,
                        self.namespace,
                        service=self.prepare_service_patch(self.service),
                    )
                except Exception:
                    success = False
                    raise
                finally:
                    self.sensor.on_resource_sync_complete(
                        self.cluster, self.cluster, self.service.metadata.name, self.namespace, "service", sensor_state, "patch", success
                    )

    async def sync_headless_service(self):
        """Check current state of headless service and create/patch if needed"""
        headless_service: V1Service = await self.fetch_service(
            self.core_v1_api, self.headless_service_name, self.namespace
        )
        if not headless_service:
            # Instrument create operation
            sensor_state = self.sensor.on_resource_sync_start(
                self.cluster, self.cluster, self.headless_service.metadata.name, self.namespace, "headless_service"
            )
            
            success = True
            try:
                await self.create_service(
                    self.core_v1_api, self.namespace, self.headless_service
                )
            except Exception:
                success = False
                raise
            finally:
                self.sensor.on_resource_sync_complete(
                    self.cluster, self.cluster, self.headless_service.metadata.name, self.namespace, "headless_service", sensor_state, "create", success
                )
        else:
            actual = self.prepare_headless_service_watch_fields(headless_service)
            desired = self.prepare_headless_service_watch_fields(self.headless_service)
            actual_hash = self.compute_hash(actual)
            desired_hash = self.compute_hash(desired)
            
            if actual_hash != desired_hash:
                # Detect drift
                self.sensor.on_resource_drift_detected(
                    self.cluster, self.cluster, self.headless_service.metadata.name, self.namespace, "headless_service", ["spec"]
                )
                
                # Instrument patch operation
                sensor_state = self.sensor.on_resource_sync_start(
                    self.cluster, self.cluster, self.headless_service.metadata.name, self.namespace, "headless_service"
                )
                
                success = True
                try:
                    await self.patch_service(
                        self.core_v1_api,
                        self.headless_service_name,
                        self.namespace,
                        service=self.prepare_headless_service_patch(self.headless_service),
                    )
                except Exception:
                    success = False
                    raise
                finally:
                    self.sensor.on_resource_sync_complete(
                        self.cluster, self.cluster, self.headless_service.metadata.name, self.namespace, "headless_service", sensor_state, "patch", success
                    )

    async def sync_service_account(self):
        """Check current state of service account and create/patch if needed."""
        service_account: V1ServiceAccount = await self.fetch_service_account(
            self.core_v1_api, self.service_account_name, self.namespace
        )
        if not service_account:
            # Instrument create operation
            sensor_state = self.sensor.on_resource_sync_start(
                self.cluster, self.cluster, self.service_account.metadata.name, self.namespace, "service_account"
            )
            
            success = True
            try:
                await self.create_service_account(
                    self.core_v1_api, self.namespace, self.service_account
                )
            except Exception:
                success = False
                raise
            finally:
                self.sensor.on_resource_sync_complete(
                    self.cluster, self.cluster, self.service_account.metadata.name, self.namespace, "service_account", sensor_state, "create", success
                )
        else:
            ...
            # not much to patch for a service account

    async def sync_settings_config_map(self):
        """Check current state of config map and create/patch if needed."""
        settings_config_map: V1ConfigMap = await self.fetch_config_map(
            self.core_v1_api, self.config_map_name, self.namespace
        )
        if not settings_config_map:
            # Instrument create operation
            sensor_state = self.sensor.on_resource_sync_start(
                self.cluster, self.cluster, self.settings_config_map.metadata.name, self.namespace, "config_map"
            )
            
            success = True
            try:
                await self.create_config_map(
                    self.core_v1_api, self.namespace, self.settings_config_map
                )
            except Exception:
                success = False
                raise
            finally:
                self.sensor.on_resource_sync_complete(
                    self.cluster, self.cluster, self.settings_config_map.metadata.name, self.namespace, "config_map", sensor_state, "create", success
                )
        else:
            actual = self.prepare_settings_config_map_watch_fields(settings_config_map)
            desired = self.prepare_settings_config_map_watch_fields(
                self.settings_config_map
            )
            actual_hash = self.compute_hash(actual)
            desired_hash = self.compute_hash(desired)
            
            if actual_hash != desired_hash:
                # Detect drift
                self.sensor.on_resource_drift_detected(
                    self.cluster, self.cluster, self.settings_config_map.metadata.name, self.namespace, "config_map", ["data"]
                )
                
                # Instrument patch operation
                sensor_state = self.sensor.on_resource_sync_start(
                    self.cluster, self.cluster, self.settings_config_map.metadata.name, self.namespace, "config_map"
                )
                
                success = True
                try:
                    await self.patch_config_map(
                        self.core_v1_api,
                        self.config_map_name,
                        self.namespace,
                        config_map=self.prepare_settings_config_map_patch(
                            self.settings_config_map
                        ),
                    )
                except Exception:
                    success = False
                    raise
                finally:
                    self.sensor.on_resource_sync_complete(
                        self.cluster, self.cluster, self.settings_config_map.metadata.name, self.namespace, "config_map", sensor_state, "patch", success
                    )

    async def sync_python_packages_pvc(self):
        """Check current state of python packages PVC and create/patch/delete as needed."""
        pvc: V1PersistentVolumeClaim = await self.fetch_persistent_volume_claim(
            self.core_v1_api, self.python_packages_pvc_name, self.namespace
        )
        
        should_create = self.should_create_packages_pvc()
        
        if pvc and not should_create:
            # PVC exists but feature is disabled - delete it
            self.sensor.on_resource_drift_detected(
                self.cluster, self.cluster, self.python_packages_pvc_name, self.namespace, "pvc", ["deleted"]
            )
            
            sensor_state = self.sensor.on_resource_sync_start(
                self.cluster, self.cluster, self.python_packages_pvc_name, self.namespace, "pvc"
            )
            
            success = True
            try:
                await self.delete_persistent_volume_claim(
                    self.core_v1_api, self.python_packages_pvc_name, self.namespace
                )
            except Exception:
                success = False
                raise
            finally:
                self.sensor.on_resource_sync_complete(
                    self.cluster, self.cluster, self.python_packages_pvc_name, self.namespace, "pvc", sensor_state, "delete", success
                )
        elif not pvc and should_create:
            # PVC doesn't exist but should be created
            sensor_state = self.sensor.on_resource_sync_start(
                self.cluster, self.cluster, self.python_packages_pvc.metadata.name, self.namespace, "pvc"
            )
            
            success = True
            try:
                await self.create_persistent_volume_claim(
                    self.core_v1_api, self.namespace, self.python_packages_pvc
                )
            except Exception:
                success = False
                raise
            finally:
                self.sensor.on_resource_sync_complete(
                    self.cluster, self.cluster, self.python_packages_pvc.metadata.name, self.namespace, "pvc", sensor_state, "create", success
                )
        elif pvc and should_create:
            # PVC exists - check if it needs patching
            actual = self.prepare_python_packages_pvc_watch_fields(pvc)
            desired = self.prepare_python_packages_pvc_watch_fields(self.python_packages_pvc)
            actual_hash = self.compute_hash(actual)
            desired_hash = self.compute_hash(desired)
            
            if actual_hash != desired_hash:
                # Detect drift
                self.sensor.on_resource_drift_detected(
                    self.cluster, self.cluster, self.python_packages_pvc_name, self.namespace, "pvc", ["spec"]
                )
                
                # Check if storage size is increasing (valid expansion)
                actual_size = actual.get("spec", {}).get("resources", {}).get("requests", {}).get("storage")
                desired_size = desired.get("spec", {}).get("resources", {}).get("requests", {}).get("storage")
                
                if actual_size and desired_size and self._is_storage_expansion(actual_size, desired_size):
                    # Storage expansion is allowed - patch the PVC
                    sensor_state = self.sensor.on_resource_sync_start(
                        self.cluster, self.cluster, self.python_packages_pvc_name, self.namespace, "pvc"
                    )
                    
                    success = True
                    try:
                        await self.patch_persistent_volume_claim(
                            self.core_v1_api,
                            self.python_packages_pvc_name,
                            self.namespace,
                            persistent_volume_claim=self.prepare_python_packages_pvc_patch(self.python_packages_pvc),
                        )
                    except Exception:
                        success = False
                        raise
                    finally:
                        self.sensor.on_resource_sync_complete(
                            self.cluster, self.cluster, self.python_packages_pvc_name, self.namespace, "pvc", sensor_state, "patch", success
                        )
                else:
                    # Other changes are not allowed (e.g., storage reduction, storage class change)
                    self.logger.warning(
                        f"Python packages PVC {self.python_packages_pvc_name} has drifted with unsupported changes. "
                        f"Storage can only be expanded, not reduced. Storage class cannot be changed. "
                        f"Manual intervention required (delete and recreate PVC)."
                    )

    async def sync_stateful_set(self):
        """Check current state of stateful set and create/patch if needed."""
        stateful_set: V1StatefulSet = await self.fetch_stateful_set(
            self.apps_v1_api, self.stateful_set_name, self.namespace
        )
        if stateful_set and self.statefulset_needs_migrations(stateful_set):
            await self.recreate_statefulset(stateful_set)
            return

        if not stateful_set:
            # Instrument create operation
            sensor_state = self.sensor.on_resource_sync_start(
                self.cluster, self.cluster, self.stateful_set.metadata.name, self.namespace, "stateful_set"
            )
            
            success = True
            try:
                await self.create_stateful_set(
                    self.apps_v1_api, self.namespace, self.stateful_set
                )
            except Exception:
                success = False
                raise
            finally:
                self.sensor.on_resource_sync_complete(
                    self.cluster, self.cluster, self.stateful_set.metadata.name, self.namespace, "stateful_set", sensor_state, "create", success
                )
        else:
            actual = self.prepare_statefulset_watch_fields(stateful_set)
            desired = self.prepare_statefulset_watch_fields(self.stateful_set)

            replicas_override = self.prepare_statefulset_desired_replicas(actual)
            if replicas_override is not None:
                desired["spec"]["replicas"] = replicas_override
            elif desired["spec"]["replicas"] is None:
                desired["spec"]["replicas"] = actual["spec"]["replicas"]

            actual_hash = self.compute_hash(actual)
            desired_hash = self.compute_hash(desired)
            
            if actual_hash != desired_hash:
                # Detect drift
                self.sensor.on_resource_drift_detected(
                    self.cluster, self.cluster, self.stateful_set.metadata.name, self.namespace, "stateful_set", ["spec"]
                )
                
                # Instrument patch operation
                sensor_state = self.sensor.on_resource_sync_start(
                    self.cluster, self.cluster, self.stateful_set.metadata.name, self.namespace, "stateful_set"
                )
                
                success = True
                try:
                    await self.patch_stateful_set(
                        self.apps_v1_api,
                        self.stateful_set_name,
                        self.namespace,
                        stateful_set=self.prepare_statefulset_patch(
                            self.stateful_set,
                            replicas_override=self.prepare_statefulset_desired_replicas(
                                actual
                            ),
                        ),
                    )
                except Exception:
                    success = False
                    raise
                finally:
                    self.sensor.on_resource_sync_complete(
                        self.cluster, self.cluster, self.stateful_set.metadata.name, self.namespace, "stateful_set", sensor_state, "patch", success
                    )

    async def sync_auth_credentials(self):
        """Sync credentials secret; We only need to check that password secret exists."""
        if self.authentication.sasl_enabled and self.sasl_credentials.password:
            secret = await self.fetch_secret(
                self.core_v1_api,
                self.sasl_credentials.password.secret_name,
                self.namespace,
            )
            if not secret:
                raise kopf.TemporaryError(
                    f"Secret `{self.sasl_credentials.password.secret_name}` not found in `{self.namespace}` namespace."
                )

    async def sync_hpa(self):
        """Check current state of HPA and create/delete/patch if needed."""
        hpa: V2HorizontalPodAutoscaler = await self.fetch_hpa(
            self.autoscaling_v2_api, self.hpa_name, self.namespace
        )
        # If reconciliation is paused, delete HPA so it does not interfere with manual changes to statefulset
        if hpa and self.reconciliation_paused:
            # Instrument delete operation
            sensor_state = self.sensor.on_resource_sync_start(
                self.cluster, self.cluster, self.hpa_name, self.namespace, "hpa"
            )
            
            success = True
            try:
                await self.delete_hpa(
                    self.autoscaling_v2_api, self.hpa_name, self.namespace
                )
            except Exception:
                success = False
                raise
            finally:
                self.sensor.on_resource_sync_complete(
                    self.cluster, self.cluster, self.hpa_name, self.namespace, "hpa", sensor_state, "delete", success
                )
            return
        elif hpa and self.replicas == 0:
            # Instrument delete operation
            sensor_state = self.sensor.on_resource_sync_start(
                self.cluster, self.cluster, self.hpa_name, self.namespace, "hpa"
            )
            
            success = True
            try:
                await self.delete_hpa(
                    self.autoscaling_v2_api, self.hpa_name, self.namespace
                )
            except Exception:
                success = False
                raise
            finally:
                self.sensor.on_resource_sync_complete(
                    self.cluster, self.cluster, self.hpa_name, self.namespace, "hpa", sensor_state, "delete", success
                )
            return
        elif self.replicas > 0:
            if not hpa:
                # Instrument create operation
                sensor_state = self.sensor.on_resource_sync_start(
                    self.cluster, self.cluster, self.hpa.metadata.name, self.namespace, "hpa"
                )
                
                success = True
                try:
                    await self.create_hpa(self.autoscaling_v2_api, self.namespace, self.hpa)
                except Exception:
                    success = False
                    raise
                finally:
                    self.sensor.on_resource_sync_complete(
                        self.cluster, self.cluster, self.hpa.metadata.name, self.namespace, "hpa", sensor_state, "create", success
                    )
            else:
                actual = self.prepare_hpa_watch_fields(hpa)
                desired = self.prepare_hpa_watch_fields(self.hpa)
                actual_hash = self.compute_hash(actual)
                desired_hash = self.compute_hash(desired)
                
                if actual_hash != desired_hash:
                    # Detect drift
                    self.sensor.on_resource_drift_detected(
                        self.cluster, self.cluster, self.hpa.metadata.name, self.namespace, "hpa", ["spec"]
                    )
                    
                    # Instrument patch operation
                    sensor_state = self.sensor.on_resource_sync_start(
                        self.cluster, self.cluster, self.hpa.metadata.name, self.namespace, "hpa"
                    )
                    
                    success = True
                    try:
                        await self.patch_hpa(
                            self.autoscaling_v2_api,
                            self.hpa_name,
                            self.namespace,
                            hpa=self.prepare_hpa_patch(self.hpa),
                        )
                    except Exception:
                        success = False
                        raise
                    finally:
                        self.sensor.on_resource_sync_complete(
                            self.cluster, self.cluster, self.hpa.metadata.name, self.namespace, "hpa", sensor_state, "patch", success
                        )

    async def recreate_statefulset(self, stateful_set: V1StatefulSet):
        """Check if statefulset needs migrations and perform them."""
        await self.delete_stateful_set(
            self.apps_v1_api,
            self.stateful_set_name,
            self.namespace,
            delete_options=V1DeleteOptions(propagation_policy="Orphan"),
        )
        # We need to wait a bit to allow k8s to actually execute the deletion
        # before moving on to recreate the statefulset.
        await asyncio.sleep(self.conf.statefulset_deletion_timeout_seconds)
        await self.sync_stateful_set()

    def with_agents(self, agents: List[KasprAgent]):
        """Apply agent resources to the app."""
        self.agents = agents
        self._agents_hash = None  # reset hash

    def with_webviews(self, webviews: List[KasprWebView]):
        """Apply webview resources to the app."""
        self.webviews = webviews
        self._webviews_hash = None  # reset hash

    def with_tables(self, tables: List[KasprTable]):
        """Apply table resources to the app."""
        self.tables = tables
        self._tables_hash = None  # reset hash

    def with_tasks(self, tasks: List[KasprTask]):
        """Apply task resources to the app."""
        self.tasks = tasks
        self._tasks_hash = None  # reset hash

    async def fetch(self, name: str, namespace: str):
        """Fetch actual KasprApp in kubernetes."""
        return await self.get_custom_object(
            self.custom_objects_api,
            namespace=namespace,
            group="kaspr.io",
            version=self.GROUP_VERSION,
            plural="kasprapps",
            name=name,
        )

    def supported_version(self, version: str) -> bool:
        """Return True if version is supported."""
        if version:
            return KasprVersionResources.is_supported_version(version)
        return False

    def prepare_version(self) -> KasprVersion:
        """Determine kaspr version to run."""
        _explicit_version = self._version
        if _explicit_version and not self.supported_version(_explicit_version):
            raise kopf.PermanentError(
                f"Version {_explicit_version} is not supported by this operator."
            )
        return (
            KasprVersionResources.default_version()
            if not _explicit_version
            else KasprVersionResources.from_version(_explicit_version)
        )

    def prepare_image(self) -> str:
        """Container image to use."""
        # Use image provide in spec, otherwise use the image defined for the given version
        return self._image if self._image else self.version.image

    def prepare_service(self) -> V1Service:
        """Build service resource."""
        annotations = self.template_service.metadata.annotations or {}
        labels = self.template_service.metadata.labels or {}
        labels.update(self.labels.as_dict())
        service = V1Service(
            api_version="v1",
            kind="Service",
            metadata=V1ObjectMeta(
                name=self.service_name, labels=labels, annotations=annotations
            ),
            spec=V1ServiceSpec(
                selector=self.labels.kasper_label_selectors().as_dict(),
                type="ClusterIP",
                ports=[
                    V1ServicePort(
                        name=self.WEB_PORT_NAME,
                        protocol="TCP",
                        port=self.web_port,
                        target_port=self.web_port,
                    )
                ],
            ),
        )
        annotations.update(
            self.prepare_hash_annotation(self.prepare_service_hash(service))
        )
        return service

    def prepare_service_hash(self, service: V1Service) -> str:
        """Compute hash for app's service resource."""
        return self.compute_hash(service.to_dict())

    def prepare_service_patch(self, service: V1Service) -> Dict:
        """Prepare patch for service resource.
        A service can only have certain fields updated via patch.
        This method should be used to prepare the patch.
        """
        patch = []

        patch.append(
            {
                "op": "replace",
                "path": "/spec/type",
                "value": service.spec.type,
            }
        )

        if service.spec.ports:
            patch.append(
                {
                    "op": "replace",
                    "path": "/spec/ports",
                    "value": service.spec.ports,
                }
            )

        return patch

    def prepare_service_watch_fields(self, service: V1Service) -> Dict:
        """
        Prepare fields of interest when comparing actual vs desired state.
        These fields are tracked for changes made outside the operator and are used to
        determine if a patch is needed.
        """
        return {
            "spec": {
                "ports": service.spec.ports,
            },
        }

    def prepare_headless_service(self) -> V1Service:
        """Build headless service resource."""
        annotations = {}
        if (
            self.template_service.metadata
            and self.template_service.metadata.annotations
        ):
            annotations = self.template_service.metadata.annotations
        labels = self.template_service.metadata.labels or {}
        labels.update(self.labels.as_dict())
        service = V1Service(
            api_version="v1",
            kind="Service",
            metadata=V1ObjectMeta(
                name=self.headless_service_name, labels=labels, annotations=annotations
            ),
            spec=V1ServiceSpec(
                selector=self.labels.kasper_label_selectors().as_dict(),
                cluster_ip="None",
                publish_not_ready_addresses=True,
                ports=[
                    V1ServicePort(
                        name=self.WEB_PORT_NAME,
                        protocol="TCP",
                        port=self.web_port,
                        target_port=self.web_port,
                    )
                ],
            ),
        )
        return service

    def prepare_headless_service_hash(self, service: V1Service) -> str:
        """Compute hash for app's headless service resource."""
        return self.compute_hash(service.to_dict())

    def prepare_headless_service_patch(self, service: V1Service) -> Dict:
        """Prepare patch for headless service resource.
        A service can only have certain fields updated via patch.
        This method should be used to prepare the patch.
        """
        patch = []

        if service.spec.ports:
            patch.append(
                {
                    "op": "replace",
                    "path": "/spec/ports",
                    "value": service.spec.ports,
                }
            )

        return patch

    def prepare_headless_service_watch_fields(self, service: V1Service) -> Dict:
        return {
            "spec": {
                "ports": service.spec.ports,
            },
        }

    def prepare_service_account(self) -> V1ServiceAccount:
        """Build service account resource."""
        labels, annotations = self.labels.as_dict(), {}
        if self.template_service_account:
            if self.template_service_account.metadata:
                if self.template_service_account.metadata.labels:
                    labels.update(self.template_service_account.metadata.labels)
                if self.template_service_account.metadata.annotations:
                    annotations.update(
                        self.template_service_account.metadata.annotations
                    )
        sa = V1ServiceAccount(
            api_version="v1",
            kind="ServiceAccount",
            metadata=V1ObjectMeta(
                name=self.service_account_name, labels=labels, annotations=annotations
            ),
        )
        annotations.update(
            self.prepare_hash_annotation(self.prepare_service_account_hash(sa))
        )
        return sa

    def prepare_service_account_hash(self, service_account: V1ServiceAccount) -> str:
        """Compute hash for service account resource."""
        return self.compute_hash(service_account.to_dict())

    def prepare_settings_config_map(self) -> V1ConfigMap:
        """Build a config map resource."""
        annotations = {}
        config_map = V1ConfigMap(
            metadata=V1ObjectMeta(
                name=self.config_map_name,
                namespace=self.namespace,
                labels=self.labels.as_dict(),
                annotations=annotations,
            ),
            data=self.prepare_env_dict(),
        )
        annotations.update(
            self.prepare_hash_annotation(
                self.prepare_settings_config_map_hash(config_map)
            )
        )
        return config_map

    def prepare_settings_config_map_hash(self, config_map: V1ConfigMap) -> str:
        """Compute hash for config map resource."""
        return self.compute_hash(config_map.to_dict())

    def prepare_settings_config_map_patch(self, config_map: V1ConfigMap) -> Dict:
        """Prepare patch for config map resource.
        A config map can only have certain fields updated via patch.
        This method should be used to prepare the patch.
        """
        patch = []

        if config_map.data:
            patch.append(
                {
                    "op": "replace",
                    "path": "/data",
                    "value": config_map.data,
                }
            )

        return patch

    def prepare_settings_config_map_watch_fields(self, config_map: V1ConfigMap) -> Dict:
        """
        Prepare fields of interest when comparing actual vs desired state.
        These fields are tracked for changes made outside the operator and are used to
        determine if a patch is needed.
        """
        return {
            "data": config_map.data,
        }

    def prepare_persistent_volume_claim(self) -> V1PersistentVolumeClaim:
        """Build a PVC resource for statefulset."""
        annotations = {}
        pvc = V1PersistentVolumeClaimTemplate(
            metadata=V1ObjectMeta(
                name=self.persistent_volume_claim_name, annotations=annotations
            ),
            spec=V1PersistentVolumeClaimSpec(
                access_modes=["ReadWriteOnce"],
                resources=V1ResourceRequirements(
                    requests={"storage": self.storage.size}
                ),
                storage_class_name=self.storage.storage_class,
            ),
        )
        annotations.update(
            self.prepare_hash_annotation(self.prepare_persistent_volume_claim_hash(pvc))
        )
        return pvc

    def prepare_persistent_volume_claim_hash(self, pvc: V1PersistentVolumeClaim) -> str:
        """Compute hash for PVC resource."""
        return self.compute_hash(pvc.to_dict())

    def prepare_persistent_volume_claim_retention_policy(self):
        return V1StatefulSetPersistentVolumeClaimRetentionPolicy(
            when_deleted="Delete" if self.storage.delete_claim else "Retain",
            when_scaled="Retain",
        )

    def prepare_python_packages_pvc(self) -> Optional[V1PersistentVolumeClaim]:
        """Build a standalone PVC resource for Python packages cache (shared by all pods)."""
        if not self.should_create_packages_pvc():
            return None
        
        cache = getattr(self.python_packages, 'cache', None)
        # Get cache configuration with defaults
        size = cache.size if cache and hasattr(cache, 'size') and cache.size else self.DEFAULT_PACKAGES_PVC_SIZE
        storage_class = cache.storage_class if cache and hasattr(cache, 'storage_class') else None
        access_mode = cache.access_mode if cache and hasattr(cache, 'access_mode') and cache.access_mode else self.DEFAULT_PACKAGES_ACCESS_MODE
        
        # Create labels with component identifier
        labels = self.labels.as_dict()
        labels["kaspr.io/component"] = "python-packages"
        
        annotations = {}
        pvc = V1PersistentVolumeClaim(
            api_version="v1",
            kind="PersistentVolumeClaim",
            metadata=V1ObjectMeta(
                name=self.python_packages_pvc_name,
                labels=labels,
                annotations=annotations,
                namespace=self.namespace,
            ),
            spec=V1PersistentVolumeClaimSpec(
                access_modes=[access_mode],
                resources=V1ResourceRequirements(
                    requests={"storage": size}
                ),
                storage_class_name=storage_class,
            ),
        )
        annotations.update(
            self.prepare_hash_annotation(self.prepare_python_packages_pvc_hash(pvc))
        )
        return pvc

    def prepare_python_packages_pvc_hash(self, pvc: V1PersistentVolumeClaim) -> str:
        """Compute hash for packages PVC resource."""
        return self.compute_hash(pvc.to_dict())
    
    def prepare_python_packages_pvc_watch_fields(self, pvc: V1PersistentVolumeClaim) -> Dict:
        """Prepare fields of interest when comparing actual vs desired state for packages PVC.
        
        For PVCs, we only track storage size (can be expanded but not reduced).
        Note: Storage class cannot be changed after creation.
        """
        storage_size = None
        if pvc.spec and pvc.spec.resources and pvc.spec.resources.requests:
            storage_size = pvc.spec.resources.requests.get("storage")
        
        return {
            "spec": {
                "resources": {
                    "requests": {
                        "storage": storage_size,
                    }
                }
            },
        }
    
    def prepare_python_packages_pvc_patch(self, pvc: V1PersistentVolumeClaim) -> Dict:
        """Prepare patch for Python packages PVC resource.
        
        Only storage size expansion is allowed to be patched.
        """
        patch = []
        
        if pvc.spec and pvc.spec.resources and pvc.spec.resources.requests:
            storage = pvc.spec.resources.requests.get("storage")
            if storage:
                patch.append(
                    {
                        "op": "replace",
                        "path": "/spec/resources/requests/storage",
                        "value": storage,
                    }
                )
        
        return patch
    
    def _is_storage_expansion(self, actual_size: str, desired_size: str) -> bool:
        """Check if desired size is larger than actual size.
        
        Parses Kubernetes quantity strings (e.g., "1Gi", "500Mi") and compares them.
        """
        def parse_size(size_str: str) -> int:
            """Parse Kubernetes quantity string to bytes."""
            if not size_str:
                return 0
            
            # Common Kubernetes storage units
            units = {
                'Ki': 1024,
                'Mi': 1024 ** 2,
                'Gi': 1024 ** 3,
                'Ti': 1024 ** 4,
                'Pi': 1024 ** 5,
                'K': 1000,
                'M': 1000 ** 2,
                'G': 1000 ** 3,
                'T': 1000 ** 4,
                'P': 1000 ** 5,
            }
            
            size_str = size_str.strip()
            
            # Try to find unit suffix
            for unit, multiplier in units.items():
                if size_str.endswith(unit):
                    number = size_str[:-len(unit)]
                    try:
                        return int(float(number) * multiplier)
                    except ValueError:
                        return 0
            
            # No unit, assume bytes
            try:
                return int(size_str)
            except ValueError:
                return 0
        
        actual_bytes = parse_size(actual_size)
        desired_bytes = parse_size(desired_size)
        
        return desired_bytes > actual_bytes
    
    def should_create_packages_pvc(self) -> bool:
        """Check if python packages PVC should be created."""
        if not self.python_packages:
            return False
        
        cache = self.python_packages.cache if hasattr(self.python_packages, 'cache') and self.python_packages.cache else None
        enabled = cache.enabled if cache and hasattr(cache, 'enabled') else self.DEFAULT_PACKAGES_CACHE_ENABLED
        
        return enabled

    def prepare_packages_init_container(self) -> Optional[V1Container]:
        """Build init container for installing Python packages."""
        if not self.python_packages:
            return None
        
        cache = self.python_packages.cache if hasattr(self.python_packages, 'cache') and self.python_packages.cache else None
        enabled = cache.enabled if cache and hasattr(cache, 'enabled') else self.DEFAULT_PACKAGES_CACHE_ENABLED
        
        if not enabled:
            return None
        
        # Generate the install script
        cache_path = "/opt/kaspr/packages"
        lock_file = "/opt/kaspr/packages/.install.lock"
        install_policy = self.python_packages.install_policy if hasattr(self.python_packages, 'install_policy') else None
        timeout = install_policy.timeout if install_policy and hasattr(install_policy, 'timeout') and install_policy.timeout else self.DEFAULT_PACKAGES_INSTALL_TIMEOUT
        retries = install_policy.retries if install_policy and hasattr(install_policy, 'retries') and install_policy.retries is not None else self.DEFAULT_PACKAGES_INSTALL_RETRIES
        
        script = generate_install_script(
            self.python_packages,
            cache_path=cache_path,
            lock_file=lock_file,
            timeout=timeout,
            retries=retries,
            packages_hash=self.packages_hash,
        )

        self.logger.info(f"Generated package install script for hash {self.packages_hash}")
        
        # Get resource requirements if specified
        resources_spec = self.python_packages.resources if hasattr(self.python_packages, 'resources') and self.python_packages.resources else None
        resource_requirements = None
        if resources_spec:
            resource_requirements = V1ResourceRequirements(
                requests=resources_spec.requests if hasattr(resources_spec, 'requests') else None,
                limits=resources_spec.limits if hasattr(resources_spec, 'limits') else None,
            )
        
        # Add PACKAGES_HASH env var to init container
        env_vars = []
        if self.packages_hash:
            env_vars.append(V1EnvVar(name="PACKAGES_HASH", value=self.packages_hash))
        
        return V1Container(
            name="install-packages",
            image=self.image,  # Use same image as main container
            command=["/bin/bash", "-c"],
            args=[script],
            env=env_vars if env_vars else None,
            volume_mounts=[
                V1VolumeMount(
                    name=f"{self.component_name}-packages",
                    mount_path=cache_path,
                )
            ],
            resources=resource_requirements,
        )

    def prepare_env_vars(self) -> List[V1EnvVar]:
        env_vars = []
        config_map = self.settings_config_map
        for key in self.env_dict.keys():
            env_vars.append(
                V1EnvVar(
                    name=key,
                    value_from=V1EnvVarSource(
                        config_map_key_ref=V1ConfigMapKeySelector(
                            key=key, name=config_map.metadata.name
                        )
                    ),
                )
            )

        # include secret(s)
        if self.authentication.sasl_enabled:
            password_env_key = self.config.env_for("kafka_auth_password")
            env_vars.append(
                V1EnvVar(
                    name=password_env_key,
                    value_from=V1EnvVarSource(
                        secret_key_ref=V1SecretKeySelector(
                            key=self.sasl_credentials.password.password_key,
                            name=self.sasl_credentials.password.secret_name,
                        )
                    ),
                )
            )

        if self.static_group_membership_enabled:
            # include consumer group instance id (for static membership)
            # the value is derived from the pod name, which is why we configure
            # here instead of in the config map
            env_vars.append(
                V1EnvVar(
                    name=self.config.env_for("consumer_group_instance_id"),
                    value_from=V1EnvVarSource(
                        field_ref=V1ObjectFieldSelector(
                            api_version="v1",
                            field_path="metadata.name",
                        )
                    ),
                )
            )

        # Add PYTHONPATH for installed packages
        if self.python_packages:
            cache = self.python_packages.cache if hasattr(self.python_packages, 'cache') and self.python_packages.cache else None
            enabled = cache.enabled if cache and hasattr(cache, 'enabled') else self.DEFAULT_PACKAGES_CACHE_ENABLED
            
            if enabled:
                env_vars.append(
                    V1EnvVar(
                        name="PYTHONPATH",
                        value="/opt/kaspr/packages:${PYTHONPATH}"
                    )
                )

        # include web host as FQDN of the pod
        # e.g. <pod_name>.<headless_service_name>.<namespace>.svc
        env_vars.append(
            V1EnvVar(
                name="POD_NAME",
                value_from=V1EnvVarSource(
                    field_ref=V1ObjectFieldSelector(field_path="metadata.name")
                ),
            )
        )
        env_vars.append(
            V1EnvVar(
                name=self.config.env_for("web_host"),
                value=f"$(POD_NAME).{self.headless_service_name}.{self.namespace}.svc.cluster.local",
            )
        )

        # include config hash
        env_vars.append(V1EnvVar(name="CONFIG_HASH", value=self.config_hash))

        # include agents hash
        if self.agents:
            env_vars.append(V1EnvVar(name="AGENTS_HASH", value=self.agents_hash))

        # include webviews hash
        if self.webviews:
            env_vars.append(V1EnvVar(name="WEBVIEWS_HASH", value=self.webviews_hash))

        # include tables hash
        if self.tables:
            env_vars.append(V1EnvVar(name="TABLES_HASH", value=self.tables_hash))

        # include tasks hash
        if self.tasks:
            env_vars.append(V1EnvVar(name="TASKS_HASH", value=self.tasks_hash))

        # include packages hash
        if self.python_packages:
            env_vars.append(V1EnvVar(name="PACKAGES_HASH", value=self.packages_hash))

        # template environment variables
        env_vars.extend(self.prepare_container_template_env_vars())

        return env_vars

    def prepare_container_template_env_vars(self) -> List[V1EnvVar]:
        """Prepare additional environment variables from template."""
        env_vars = []
        if self.template_container.env:
            for cev in self.template_container.env:
                if cev.value:
                    env_vars.append(V1EnvVar(name=cev.name, value=cev.value))
                elif cev.value_from:
                    if cev.value_from.config_map_key_ref:
                        env_vars.append(
                            V1EnvVar(
                                name=cev.name,
                                value_from=V1EnvVarSource(
                                    config_map_key_ref=V1ConfigMapKeySelector(
                                        key=cev.value_from.config_map_key_ref.key,
                                        name=cev.value_from.config_map_key_ref.name,
                                        optional=cev.value_from.config_map_key_ref.optional,
                                    )
                                ),
                            )
                        )
                    elif cev.value_from.secret_key_ref:
                        env_vars.append(
                            V1EnvVar(
                                name=cev.name,
                                value_from=V1EnvVarSource(
                                    secret_key_ref=V1SecretKeySelector(
                                        key=cev.value_from.secret_key_ref.key,
                                        name=cev.value_from.secret_key_ref.name,
                                        optional=cev.value_from.secret_key_ref.optional,
                                    )
                                ),
                            )
                        )
        return env_vars

    def prepare_kafka_credentials_env_dict(self) -> Dict[str, str]:
        """Prepare kafka credential environment variables. Password secret is handled separately."""
        env_for = self.config.env_for
        if self.authentication.sasl_enabled:
            credentials = self.sasl_credentials
            return {
                env_for("kafka_security_protocol"): credentials.protocol.value,
                env_for("kafka_sasl_mechanism"): credentials.mechanism.value,
                env_for("kafka_auth_username"): credentials.username,
            }
        if self.authentication.authentication_tls:
            # TODO: Support TLS authentication
            raise kopf.PermanentError("TLS authentication is not supported.")

        return {
            env_for(
                "kafka_security_protocol"
            ): self.authentication.security_protocol.value
        }

    def prepare_env_dict(self) -> Dict[str, str]:
        """Prepare a dict of environment variables to be used for KMS app."""
        env_for = self.config.env_for
        config_envs = self.config.as_envs()
        overrides = {
            env_for("app_name"): self.component_name,
            env_for("kafka_bootstrap_servers"): self.bootstrap_servers,
            **self.prepare_kafka_credentials_env_dict(),
            env_for("web_port"): str(self.web_port),
            env_for("data_dir"): self.data_dir_path,
            env_for("table_dir"): self.table_dir_path,
            env_for("definitions_dir"): self.definitions_dir_path,
        }
        _envs = {**config_envs}
        _envs.update(overrides)
        return _envs

    def prepare_agent_volume_mounts(self) -> List[V1VolumeMount]:
        volume_mounts = []
        for agent in self.agents if self.agents else []:
            volume_mounts.append(
                V1VolumeMount(
                    name=agent.volume_mount_name,
                    mount_path=self.prepare_agent_mount_path(agent),
                    read_only=True,
                    sub_path=agent.file_name,
                )
            )
        return volume_mounts

    def prepare_webview_volume_mounts(self) -> List[V1VolumeMount]:
        volume_mounts = []
        for webview in self.webviews if self.webviews else []:
            volume_mounts.append(
                V1VolumeMount(
                    name=webview.volume_mount_name,
                    mount_path=self.prepare_webview_mount_path(webview),
                    read_only=True,
                    sub_path=webview.file_name,
                )
            )
        return volume_mounts

    def prepare_table_volume_mounts(self) -> List[V1VolumeMount]:
        volume_mounts = []
        for table in self.tables if self.tables else []:
            volume_mounts.append(
                V1VolumeMount(
                    name=table.volume_mount_name,
                    mount_path=self.prepare_table_mount_path(table),
                    read_only=True,
                    sub_path=table.file_name,
                )
            )
        return volume_mounts

    def prepare_task_volume_mounts(self) -> List[V1VolumeMount]:
        volume_mounts = []
        for task in self.tasks if self.tasks else []:
            volume_mounts.append(
                V1VolumeMount(
                    name=task.volume_mount_name,
                    mount_path=self.prepare_task_mount_path(task),
                    read_only=True,
                    sub_path=task.file_name,
                )
            )
        return volume_mounts

    def prepare_agent_mount_path(self, agent: KasprAgent) -> str:
        return f"{self.definitions_dir_path}/{agent.file_name}"

    def prepare_webview_mount_path(self, webview: KasprWebView) -> str:
        return f"{self.definitions_dir_path}/{webview.file_name}"

    def prepare_table_mount_path(self, table: KasprTable) -> str:
        return f"{self.definitions_dir_path}/{table.file_name}"

    def prepare_task_mount_path(self, task: KasprTask) -> str:
        return f"{self.definitions_dir_path}/{task.file_name}"

    def prepare_volume_mounts(self) -> List[V1VolumeMount]:
        volume_mounts = []
        volume_mounts.extend(
            [
                V1VolumeMount(
                    name=self.persistent_volume_claim_name,
                    mount_path=self.table_dir_path,
                ),
                *self.prepare_agent_volume_mounts(),
                *self.prepare_webview_volume_mounts(),
                *self.prepare_table_volume_mounts(),
                *self.prepare_task_volume_mounts(),
                *self.prepare_container_template_volume_mounts(),
                *self.prepare_packages_volume_mounts(),
            ]
        )
        return volume_mounts

    def prepare_packages_volume_mounts(self) -> List[V1VolumeMount]:
        """Prepare volume mount for Python packages cache."""
        volume_mounts = []
        if self.python_packages:
            cache = self.python_packages.cache if hasattr(self.python_packages, 'cache') and self.python_packages.cache else None
            enabled = cache.enabled if cache and hasattr(cache, 'enabled') else self.DEFAULT_PACKAGES_CACHE_ENABLED
            
            if enabled:
                volume_mounts.append(
                    V1VolumeMount(
                        name=f"{self.component_name}-packages",
                        mount_path="/opt/kaspr/packages",
                        read_only=True,  # Main container only reads installed packages
                    )
                )
        return volume_mounts

    def prepare_container_template_volume_mounts(self) -> List[V1VolumeMount]:
        """Prepare additional volume mounts from template."""
        volume_mounts = []
        if self.template_container.volume_mounts:
            for vm in self.template_container.volume_mounts:
                volume_mounts.append(
                    V1VolumeMount(
                        name=vm.name,
                        mount_path=vm.mount_path,
                        sub_path=vm.sub_path,
                        read_only=vm.read_only,
                        mount_propagation=vm.mount_propagation,
                        sub_path_expr=vm.sub_path_expr,
                    )
                )
        return volume_mounts

    def prepare_container_resource_requirements(
        self,
    ) -> Dict[str, ResourceRequirements]:
        """Build a container resource requirements."""
        # resource requirements are optional
        extras = {}
        if self.resources is not None:
            extras["resources"] = self.resources
        return extras

    def prepare_container_probes(self) -> Dict[str, V1Probe]:
        probes = {}
        # TODO
        # probes.update({
        #     "readiness_probe": self.readiness_probe,
        #     "liveness_probe": self.liveness_probe
        # })
        return probes

    def prepare_container_ports(self) -> List[V1ContainerPort]:
        """Build container ports."""
        ports = []
        ports.append(
            V1ContainerPort(container_port=self.web_port, name=self.WEB_PORT_NAME)
        )
        return ports

    def prepare_volumes(self) -> List[V1Volume]:
        volumes = []
        volumes.extend(self.prepare_agent_volumes())
        volumes.extend(self.prepare_webview_volumes())
        volumes.extend(self.prepare_table_volumes())
        volumes.extend(self.prepare_task_volumes())
        volumes.extend(self.prepare_pod_template_volumes())
        
        # Add python packages PVC volume if enabled
        if self.should_create_packages_pvc():
            volumes.append(
                V1Volume(
                    name=f"{self.component_name}-packages",
                    persistent_volume_claim=V1PersistentVolumeClaimVolumeSource(
                        claim_name=self.python_packages_pvc_name
                    )
                )
            )
        
        return volumes

    def prepare_pod_template_volumes(self) -> List[V1Volume]:
        """Prepare an additional volumes from the template pod."""
        volumes = []
        if self.template_pod.volumes:
            for volume in self.template_pod.volumes:
                if volume.secret:
                    volumes.append(
                        V1Volume(
                            name=volume.name,
                            secret=V1SecretVolumeSource(
                                secret_name=volume.secret.secret_name,
                                items=[
                                    V1KeyToPath(
                                        key=item.key, path=item.path, mode=item.mode
                                    )
                                    for item in volume.secret.items
                                ],
                            ),
                        )
                    )
                elif volume.config_map:
                    volumes.append(
                        V1Volume(
                            name=volume.name,
                            config_map=V1ConfigMapVolumeSource(
                                name=volume.config_map.name,
                                items=[
                                    V1KeyToPath(
                                        key=item.key, path=item.path, mode=item.mode
                                    )
                                    for item in volume.config_map.items
                                ],
                            ),
                        )
                    )
                elif volume.empty_dir:
                    volumes.append(
                        V1Volume(name=volume.name, empty_dir=volume.empty_dir)
                    )
                else:
                    raise kopf.PermanentError("Unsupported volume type.")
        return volumes

    def prepare_agent_volumes(self) -> List[V1Volume]:
        volumes = []
        for agent in self.agents if self.agents else []:
            volumes.append(
                V1Volume(
                    name=agent.volume_mount_name,
                    config_map=V1ConfigMapVolumeSource(
                        name=agent.config_map_name,
                        items=[V1KeyToPath(key=agent.file_name, path=agent.file_name)],
                    ),
                )
            )
        return volumes

    def prepare_webview_volumes(self) -> List[V1Volume]:
        volumes = []
        for webview in self.webviews if self.webviews else []:
            volumes.append(
                V1Volume(
                    name=webview.volume_mount_name,
                    config_map=V1ConfigMapVolumeSource(
                        name=webview.config_map_name,
                        items=[
                            V1KeyToPath(key=webview.file_name, path=webview.file_name)
                        ],
                    ),
                )
            )
        return volumes

    def prepare_table_volumes(self) -> List[V1Volume]:
        volumes = []
        for table in self.tables if self.tables else []:
            volumes.append(
                V1Volume(
                    name=table.volume_mount_name,
                    config_map=V1ConfigMapVolumeSource(
                        name=table.config_map_name,
                        items=[V1KeyToPath(key=table.file_name, path=table.file_name)],
                    ),
                )
            )
        return volumes

    def prepare_task_volumes(self) -> List[V1Volume]:
        volumes = []
        for task in self.tasks if self.tasks else []:
            volumes.append(
                V1Volume(
                    name=task.volume_mount_name,
                    config_map=V1ConfigMapVolumeSource(
                        name=task.config_map_name,
                        items=[V1KeyToPath(key=task.file_name, path=task.file_name)],
                    ),
                )
            )
        return volumes

    def prepare_kaspr_container(self) -> V1Container:
        return V1Container(
            name=self.KASPR_CONTAINER_NAME,
            image=self.image,
            image_pull_policy="IfNotPresent",
            ports=self.container_ports,
            env=self.env_vars,
            **self.prepare_container_probes(),
            **self.prepare_container_resource_requirements(),
            volume_mounts=self.volume_mounts,
        )

    def prepare_pod_template(self) -> V1PodTemplateSpec:
        """Build pod template resource."""
        annotations = self.template_pod.metadata.annotations or {}
        labels = self.template_pod.metadata.labels or {}
        labels.update(self.labels.as_dict())
        return V1PodTemplateSpec(
            metadata=V1ObjectMeta(labels=labels, annotations=annotations),
            spec=self.pod_spec,
        )

    def prepare_pod_spec(self) -> V1PodSpec:
        """Build pod spec for kaspr app."""
        # Build init containers list
        init_containers = []
        if self.packages_init_container:
            init_containers.append(self.packages_init_container)
        
        return V1PodSpec(
            image_pull_secrets=self.template_pod.image_pull_secrets,
            security_context=self.template_pod.security_context,
            termination_grace_period_seconds=self.template_pod.termination_grace_period_seconds,
            node_selector=self.template_pod.node_selector,
            affinity=self.template_pod.affinity,
            tolerations=self.template_pod.tolerations,
            topology_spread_constraints=self.template_pod.topology_spread_constraints,
            priority_class_name=self.template_pod.priority_class_name,
            scheduler_name=self.template_pod.scheduler_name,
            host_aliases=self.template_pod.host_aliases,
            enable_service_links=self.template_pod.enable_service_links,
            init_containers=init_containers if init_containers else None,
            containers=[self.kaspr_container],
            volumes=self.volumes,
        )

    def prepare_statefulset(self) -> V1StatefulSetSpec:
        """Build stateful set resource."""
        labels, annotations = {}, {}
        
        # Only include main storage PVC in volume claim templates
        # Python packages PVC is now a standalone shared PVC
        volume_claim_templates = [self.persistent_volume_claim]
        
        stateful_set = V1StatefulSet(
            api_version="apps/v1",
            kind="StatefulSet",
            metadata=V1ObjectMeta(
                name=self.component_name, labels=labels, annotations=annotations
            ),
            spec=V1StatefulSetSpec(
                replicas=self.replicas
                if self.replicas == 0
                else None,  # set only 0 replicas, otherwise we delegate to HPA
                service_name=self.headless_service_name,
                update_strategy=V1StatefulSetUpdateStrategy(type="RollingUpdate"),
                pod_management_policy="Parallel",
                selector=V1LabelSelector(
                    match_labels=self.labels.kasper_label_selectors().as_dict()
                ),
                template=self.pod_template,
                volume_claim_templates=volume_claim_templates,
                persistent_volume_claim_retention_policy=self.persistent_volume_claim_retention_policy,
            ),
        )
        annotations.update(
            self.prepare_hash_annotation(self.prepare_statefulset_hash(stateful_set))
        )
        
        return stateful_set

    def prepare_statefulset_hash(self, stateful_set: V1StatefulSet) -> str:
        """Compute hash for stateful set resource."""
        return self.compute_hash(stateful_set.to_dict())

    def prepare_statefulset_patch(
        self, stateful_set: V1StatefulSet, replicas_override: int = None
    ) -> Dict:
        """Prepare patch for stateful set resource.
        A statefulset can only have certain fields updated via patch.
        This method should be used to prepare the patch.
        Args:
            stateful_set: the desired stateful set
            replicas: if provided, explicitly overrides the replicas in the stateful set
        """
        patch = []

        spec: V1StatefulSetSpec = stateful_set.spec

        if replicas_override is not None:
            patch.append(
                {
                    "op": "replace",
                    "path": "/spec/replicas",
                    "value": replicas_override,
                }
            )
        elif self.replicas == 0 and spec.replicas is not None:
            patch.append(
                {
                    "op": "replace",
                    "path": "/spec/replicas",
                    "value": spec.replicas,
                }
            )

        if stateful_set.spec.template:
            patch.append(
                {
                    "op": "replace",
                    "path": "/spec/template",
                    "value": spec.template,
                }
            )

        if stateful_set.spec.update_strategy:
            patch.append(
                {
                    "op": "replace",
                    "path": "/spec/updateStrategy",
                    "value": spec.update_strategy,
                }
            )

        if stateful_set.spec.min_ready_seconds is not None:
            patch.append(
                {
                    "op": "replace",
                    "path": "/spec/minReadySeconds",
                    "value": spec.min_ready_seconds,
                }
            )

        if stateful_set.spec.persistent_volume_claim_retention_policy:
            patch.append(
                {
                    "op": "replace",
                    "path": "/spec/persistentVolumeClaimRetentionPolicy",
                    "value": spec.persistent_volume_claim_retention_policy,
                }
            )

        if spec.service_name:
            patch.append(
                {
                    "op": "replace",
                    "path": "/spec/serviceName",
                    "value": spec.service_name,
                }
            )

        return patch

    def prepare_statefulset_watch_fields(self, stateful_set: V1StatefulSet) -> Dict:
        """
        Prepare fields of interest when comparing actual vs desired state.
        These fields are tracked for changes made outside the operator and are used to
        determine if a patch is needed.
        """
        # Extract PACKAGES_HASH env var from init container if it exists
        packages_hash_env = None
        if stateful_set.spec.template.spec.init_containers:
            for init_container in stateful_set.spec.template.spec.init_containers:
                if init_container.name == "install-packages" and init_container.env:
                    for env_var in init_container.env:
                        if env_var.name == "PACKAGES_HASH":
                            packages_hash_env = env_var.value
                            break
                    if packages_hash_env is not None:
                        break
        
        watch_fields = {
            "spec": {
                "replicas": stateful_set.spec.replicas,
                "template": {
                    "spec": {
                        "containers": [
                            {
                                "image": stateful_set.spec.template.spec.containers[
                                    0
                                ].image
                            }
                        ]
                    }
                },
            }
        }
        
        # Include PACKAGES_HASH from init container in watch fields if present
        if packages_hash_env is not None:
            watch_fields["spec"]["template"]["spec"]["initContainers"] = [
                {
                    "name": "install-packages",
                    "env": [
                        {"name": "PACKAGES_HASH", "value": packages_hash_env}
                    ]
                }
            ]
        
        return watch_fields

    def prepare_statefulset_desired_replicas(self, actual: Dict) -> Dict:
        """Prepare desired replicas for stateful set.
        This is used to set the initial replicas when scaling the statefulset from 0 to >0.
        We set the initial replicas to INITIAL_MAX_REPLICAS to give the HPA metrics to begin
        scaling over INITIAL_MAX_REPLICAS, if needed.
        """
        if actual["spec"]["replicas"] == 0 and self.replicas > 0:
            return (
                self.replicas
                if self.replicas <= self.conf.initial_max_replicas
                else self.conf.initial_max_replicas
            )
        return None

    def prepare_hpa(self) -> V2HorizontalPodAutoscaler:
        """Build HPA resource.
        A horizontal pod autoscaler is used to mitigate common issues stemming from race conditions related to group rebalancing
        and assignment when starting many pods at once. The HPA is configured to scale up to N pods immediately, and then
        double the number of pods every Y seconds thereafter until max replicas is reached.

        The exploit here is that we use an average memory value of 1Mi which will always drive scale up behavior.
        """
        labels, annotations = {}, {}
        hpa = V2HorizontalPodAutoscaler(
            api_version="autoscaling/v2",
            kind="HorizontalPodAutoscaler",
            metadata=V1ObjectMeta(
                name=self.hpa_name, labels=labels, annotations=annotations
            ),
            spec=V2HorizontalPodAutoscalerSpec(
                scale_target_ref=V2CrossVersionObjectReference(
                    api_version="apps/v1",
                    kind="StatefulSet",
                    name=self.stateful_set_name,
                ),
                min_replicas=1,
                max_replicas=self.replicas,
                metrics=[
                    V2MetricSpec(
                        type="Resource",
                        resource=V2ResourceMetricSource(
                            name="memory",
                            target=V2MetricTarget(
                                type="AverageValue",
                                average_value="1Mi",
                            ),
                        ),
                    )
                ],
                behavior=V2HorizontalPodAutoscalerBehavior(
                    scale_up=V2HPAScalingRules(
                        policies=[
                            V2HPAScalingPolicy(
                                type="Percent",
                                value=100,
                                period_seconds=self.conf.hpa_scale_up_policy_period_seconds,
                            ),
                            V2HPAScalingPolicy(
                                type="Pods",
                                value=self.conf.hpa_scale_up_policy_pods_per_step,
                                period_seconds=self.conf.hpa_scale_up_policy_period_seconds,
                            ),
                        ],
                        select_policy="Max",
                        stabilization_window_seconds=0,
                    ),
                    scale_down=V2HPAScalingRules(
                        policies=[
                            V2HPAScalingPolicy(
                                type="Percent",
                                value=100,
                                period_seconds=1,
                            )
                        ],
                        select_policy="Max",
                        stabilization_window_seconds=0,
                    ),
                ),
            ),
        )
        annotations.update(self.prepare_hash_annotation(self.prepare_hpa_hash(hpa)))
        return hpa

    def prepare_hpa_hash(self, hpa: V2HorizontalPodAutoscaler) -> str:
        """Compute hash for HPA resource."""
        return self.compute_hash(hpa.to_dict())

    def prepare_hpa_patch(self, hpa: V2HorizontalPodAutoscaler) -> Dict:
        """Prepare patch for HPA resource.
        An HPA can only have certain fields updated via patch.
        This method should be used to prepare the patch.
        """
        patch = []

        if hpa.spec.min_replicas is not None:
            patch.append(
                {
                    "op": "replace",
                    "path": "/spec/minReplicas",
                    "value": hpa.spec.min_replicas,
                }
            )

        if hpa.spec.max_replicas is not None:
            patch.append(
                {
                    "op": "replace",
                    "path": "/spec/maxReplicas",
                    "value": hpa.spec.max_replicas,
                }
            )

        if (
            hpa.spec.behavior
            and hpa.spec.behavior.scale_up
            and hpa.spec.behavior.scale_up.policies
        ):
            patch.append(
                {
                    "op": "replace",
                    "path": "/spec/behavior/scaleUp/policies/0/periodSeconds",
                    "value": hpa.spec.behavior.scale_up.policies[0].period_seconds,
                }
            )
            patch.append(
                {
                    "op": "replace",
                    "path": "/spec/behavior/scaleUp/policies/1/periodSeconds",
                    "value": hpa.spec.behavior.scale_up.policies[1].period_seconds,
                }
            )
            patch.append(
                {
                    "op": "replace",
                    "path": "/spec/behavior/scaleUp/policies/1/value",
                    "value": hpa.spec.behavior.scale_up.policies[1].value,
                }
            )

        return patch

    def prepare_hpa_watch_fields(self, hpa: V2HorizontalPodAutoscaler) -> Dict:
        """
        Prepare fields of interest when comparing actual vs desired state.
        These fields are tracked for changes made outside the operator and are used to
        determine if a patch is needed.
        """
        return {
            "spec": {
                "minReplicas": hpa.spec.min_replicas,
                "maxReplicas": hpa.spec.max_replicas,
                "behavior": {
                    "scaleUp": {
                        "policies": [
                            {
                                "value": hpa.spec.behavior.scale_up.policies[0].value,
                                "periodSeconds": hpa.spec.behavior.scale_up.policies[
                                    0
                                ].period_seconds,
                            }
                        ]
                    }
                },
            }
        }

    async def patch_settings(self):
        """Update resources as a result of app settings change."""
        await self.patch_config_map(
            self.core_v1_api,
            self.config_map_name,
            self.namespace,
            self.settings_config_map,
        )
        await self.patch_stateful_set(
            self.apps_v1_api,
            self.stateful_set_name,
            self.namespace,
            stateful_set={"spec": {"template": self.pod_template}},
        )

    async def create(self):
        """Create KMS resources."""
        self.unite()
        await self.sync_service_account()
        await self.sync_settings_config_map()
        await self.sync_python_packages_pvc()
        await self.sync_service()
        await self.sync_headless_service()
        await self.sync_stateful_set()

    async def patch_replicas(self):
        if self.replicas == 0:
            # If replicas is set to 0, we don't want to patch the HPA as that would
            # result in an invalid configuration. Instead we just delete the HPA
            await self.delete_hpa(
                self.autoscaling_v2_api, self.hpa_name, self.namespace
            )
            await self.patch_stateful_set(
                self.apps_v1_api,
                self.stateful_set_name,
                self.namespace,
                stateful_set={"spec": {"replicas": self.replicas}},
            )
            return
        else:
            await self.sync_hpa()
            await self.sync_stateful_set()

    async def patch_version(self):
        await self.patch_stateful_set(
            self.apps_v1_api,
            self.stateful_set_name,
            self.namespace,
            stateful_set={"spec": {"template": self.pod_template}},
        )

    async def patch_kafka_credentials(self):
        await self.patch_settings()

    async def patch_resource_requirements(self):
        await self.patch_stateful_set(
            self.apps_v1_api,
            self.stateful_set_name,
            self.namespace,
            stateful_set={"spec": {"template": self.pod_template}},
        )

    async def patch_web_port(self):
        """Update resources to change app web port."""
        if not await self.fetch_config_map(
            self.core_v1_api, self.config_map_name, self.namespace
        ):
            raise kopf.TemporaryError(
                f"ConfigMap `{self.config_map_name}` not found in `{self.namespace}` namespace."
            )
        await self.patch_config_map(
            self.core_v1_api,
            self.config_map_name,
            self.namespace,
            self.settings_config_map,
        )
        service = await self.fetch_service(
            self.core_v1_api, self.service_name, self.namespace
        )
        if not service:
            raise kopf.TemporaryError(
                f"Service `{self.service_name}` not found in `{self.namespace}` namespace."
            )
        service.spec.ports[0].port = self.web_port
        service.spec.ports[0].target_port = self.web_port
        await self.replace_service(
            self.core_v1_api, self.service_name, self.namespace, service
        )
        stateful_set = await self.fetch_stateful_set(
            self.apps_v1_api, self.stateful_set_name, self.namespace
        )
        if not stateful_set:
            raise kopf.TemporaryError(
                f"StatefulSet `{self.stateful_set_name}` not found in `{self.namespace}` namespace."
            )
        stateful_set.spec.template.spec.containers[0].ports[
            0
        ].container_port = self.web_port
        await self.replace_stateful_set(
            self.apps_v1_api,
            self.stateful_set_name,
            self.namespace,
            stateful_set=stateful_set,
        )

    async def patch_storage_retention_policy(self):
        patch = {
            "spec": {
                "persistentVolumeClaimRetentionPolicy": self.persistent_volume_claim_retention_policy
            }
        }
        ss = await self.fetch_stateful_set(
            self.apps_v1_api, self.stateful_set_name, self.namespace
        )
        if not ss:
            raise kopf.TemporaryError(
                f"StatefulSet `{self.stateful_set_name}` not found in `{self.namespace}` namespace."
            )
        await self.patch_stateful_set(
            self.apps_v1_api,
            self.stateful_set_name,
            self.namespace,
            stateful_set=patch,
        )

    async def terminate_member(self, member_id: int) -> bool:
        """Terminate a member pod by its ID.
        
        Args:
            member_id: The member ID (corresponds to StatefulSet ordinal)
            
        Returns:
            True if termination succeeded, False otherwise
        """            
        pod_name = f"{self.component_name}-{member_id}"
        
        try:
            await self.delete_pod(
                self.core_v1_api,
                pod_name,
                self.namespace,
                delete_options=V1DeleteOptions(grace_period_seconds=10),
            )
            self.logger.info(f"Terminated member {member_id} pod {pod_name}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to terminate pod {pod_name} for member {member_id}: {e}")
            return False

    async def patch_storage_size(self):
        # We can't directly patch the stateful set PVC template with new storage size.
        # So must must do the following:
        #  - Delete the statefulset with orphaned pods.
        #  - Recreate the statefulset with the updated PVC template storage size
        #  - Update storage size on all existing PVCs
        stateful_set = await self.fetch_stateful_set(
            self.apps_v1_api, self.stateful_set_name, self.namespace
        )
        if stateful_set:
            await self.delete_stateful_set(
                self.apps_v1_api,
                self.stateful_set_name,
                self.namespace,
                delete_options=V1DeleteOptions(propagation_policy="Orphan"),
            )
            # We need to wait a bit to allow k8s to actually execute the deletion
            # before moving on to recreate the statefulset.
            time.sleep(self.conf.statefulset_deletion_timeout_seconds)
        self.unite()
        # Recreate the statefulset with new storage size PVC template
        await self.create_stateful_set(
            self.apps_v1_api, self.namespace, self.stateful_set
        )
        # Update existing PVCs
        pvcs = await self.list_persistent_volume_claims(
            self.core_v1_api, namespace=self.namespace
        )
        if pvcs and pvcs.items:
            app_labels = self.labels.kasper_label_selectors()
            statefulset_pvc_list = [
                pvc
                for pvc in pvcs.items
                if Labels(pvc.metadata.labels).contains(app_labels)
            ]
            for pvc in statefulset_pvc_list:
                pvc: V1PersistentVolumeClaim
                pvc.spec.resources.requests["storage"] = self.storage.size
                await self.patch_persistent_volume_claim(
                    self.core_v1_api, pvc.metadata.name, self.namespace, pvc
                )

    async def patch_volume_mounted_resources(self):
        """Update resources as a result of volume mounted resources change."""
        patch = [
            {
                "op": "replace",
                "path": "/spec/template/spec/containers/0/volumeMounts",
                "value": self.volume_mounts,
            },
            {
                "op": "replace",
                "path": "/spec/template/spec/volumes",
                "value": self.volumes,
            },
            {
                "op": "replace",
                "path": "/spec/template/spec/containers/0/env",
                "value": self.env_vars,
            },
        ]
        if not await self.fetch_stateful_set(
            self.apps_v1_api, self.stateful_set_name, self.namespace
        ):
            raise kopf.TemporaryError(
                f"StatefulSet `{self.stateful_set_name}` not found in `{self.namespace}` namespace."
            )
        await self.patch_stateful_set(
            self.apps_v1_api,
            self.stateful_set_name,
            self.namespace,
            stateful_set=patch,
        )

    async def patch_template_service_account(self):
        patch = [
            {
                "op": "replace",
                "path": "/metadata/labels",
                "value": self.service_account.metadata.labels,
            },
            {
                "op": "replace",
                "path": "/metadata/annotations",
                "value": self.service_account.metadata.annotations,
            },
        ]
        sa = await self.fetch_service_account(
            self.core_v1_api, self.service_account_name, self.namespace
        )
        if not sa:
            raise kopf.TemporaryError(
                f"ServiceAccount `{self.service_account_name}` not found in `{self.namespace}` namespace."
            )
        await self.patch_service_account(
            self.core_v1_api,
            self.service_account_name,
            self.namespace,
            patch,
        )

    async def patch_template_pod(self):
        """Update pod template."""
        patch = [
            {
                "op": "replace",
                "path": "/spec/template",
                "value": self.pod_template,
            },
        ]
        if not await self.fetch_stateful_set(
            self.apps_v1_api, self.stateful_set_name, self.namespace
        ):
            raise kopf.TemporaryError(
                f"StatefulSet `{self.stateful_set_name}` not found in `{self.namespace}` namespace."
            )
        await self.patch_stateful_set(
            self.apps_v1_api,
            self.stateful_set_name,
            self.namespace,
            stateful_set=patch,
        )

    async def patch_template_service(self):
        """Update pod template with new labels."""
        patch = [
            {
                "op": "replace",
                "path": "/metadata/labels",
                "value": self.service.metadata.labels,
            },
            {
                "op": "replace",
                "path": "/metadata/annotations",
                "value": self.service.metadata.annotations,
            },
        ]
        if not await self.fetch_service(
            self.core_v1_api, self.service_name, self.namespace
        ):
            raise kopf.TemporaryError(
                f"Service `{self.service_name}` not found in `{self.namespace}` namespace."
            )
        await self.patch_service(
            self.core_v1_api,
            self.service_name,
            self.namespace,
            patch,
        )

    def unite(self):
        """Ensure all child resources are owned by the root resource"""
        children = [
            self.service_account,
            self.settings_config_map,
            self.service,
            self.headless_service,
            self.stateful_set,
            self.hpa,
        ]
        
        # Conditionally adopt python packages PVC based on delete_claim setting
        if self.should_create_packages_pvc() and self.python_packages_pvc:
            cache = getattr(self.python_packages, 'cache', None)
            delete_claim = cache.delete_claim if cache and hasattr(cache, 'delete_claim') and cache.delete_claim is not None else self.DEFAULT_PACKAGES_DELETE_CLAIM
            
            if delete_claim:
                children.append(self.python_packages_pvc)
        
        kopf.adopt(children)

    async def search(self, namespace: str, apps: List[str] = None):
        """Search for KasprApps in kubernetes."""
        label_selector = (
            ",".join(f"{self.KASPR_APP_NAME_LABEL}={app}" for app in apps)
            if apps
            else None
        )
        return await self.list_custom_objects(
            self.custom_objects_api,
            namespace=namespace,
            group=self.GROUP_NAME,
            version=self.GROUP_VERSION,
            plural=self.PLURAL_NAME,
            label_selector=label_selector,
        )

    def agents_status(self) -> Dict:
        """Return status of all agents."""
        return [agent.info() for agent in self.agents]

    def webviews_status(self) -> Dict:
        """Return status of all webviews."""
        return [webview.info() for webview in self.webviews]

    def tables_status(self) -> Dict:
        """Return status of all tables."""
        return [table.info() for table in self.tables]

    def tasks_status(self) -> Dict:
        """Return status of all tasks."""
        return [task.info() for task in self.tasks]

    async def fetch_app_status(self) -> Dict:
        """Fetch status of application's statefulset/pods"""
        stateful_set = await self.fetch_stateful_set(
            self.apps_v1_api, self.stateful_set_name, self.namespace
        )
        if not stateful_set:
            return

        kaspr_container: V1Container = next(
            (
                c
                for c in stateful_set.spec.template.spec.containers
                if c.name == "kaspr" and c.image
            ),
            None,
        )

        member_statuses = []
        if stateful_set.status.available_replicas > 0 and kaspr_container:
            # Fetch status from all members using dedicated method
            member_statuses = await self.fetch_all_member_statuses(
                stateful_set.status.available_replicas
            )

        kaspr_ver = kaspr_container.image.split(":")[-1] if kaspr_container else None
        available_replicas = (
            stateful_set.status.available_replicas if stateful_set.status else 0
        )
        rollout_in_progress = (
            (
                stateful_set.status.current_replicas
                != stateful_set.status.updated_replicas
            )
            if stateful_set.status and hasattr(stateful_set.status, "updated_replicas")
            else False
        )

        return {
            "kasprVersion": kaspr_ver,
            "availableMembers": available_replicas,
            "desiredMembers": self.replicas,
            "rolloutInProgress": rollout_in_progress,
            "members": member_statuses if available_replicas > 0 else [],
        }

    async def fetch_all_member_statuses(self, available_replicas: int) -> List[Dict]:
        """Fetch status from all available worker instances concurrently.

        Args:
            available_replicas: Number of available replicas to check

        Returns:
            Dictionary mapping worker index to status data for successful calls
        """
        if not self.conf.client_status_check_enabled:
            return []

        async def fetch_member_status(idx: int):
            """Fetch status from a single member."""
            try:
                url = self.prepare_member_url(idx)
                status = await self.web_client.get_status(url)
                return idx, status
            except Exception as e:
                self.logger.warning(f"Failed to get status from member {idx}: {e}")
                return idx, None

        # Create tasks for all members
        tasks = [fetch_member_status(idx) for idx in range(available_replicas)]

        try:
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=self.conf.client_status_check_timeout_seconds,
            )

            # Filter out failed calls and collect successful results
            member_statuses = []
            for result in results:
                if isinstance(result, Exception):
                    # This shouldn't happen since we handle exceptions in fetch_member_status
                    continue
                idx, status = result
                if status is not None:
                    member_statuses.append(
                        {"id": idx, "lastUpdateTime": now(), **status}
                    )

            if not member_statuses:
                self.logger.warning("All worker status checks failed")

            return member_statuses

        except asyncio.TimeoutError:
            self.logger.warning(
                f"Timed out fetching member statuses after {self.conf.client_status_check_timeout_seconds} seconds."
            )
            return []

    def prepare_member_url(self, pod_index: int) -> str:
        """Prepare the worker URL for a given pod index."""
        return f"http://{self.prepare_fqdn(pod_index)}:{self.web_port}"

    def prepare_fqdn(self, pod_index: int) -> str:
        """Prepare the fully qualified domain name for a given pod index."""
        return f"{self.component_name}-{pod_index}.{self.headless_service_name}.{self.namespace}.svc.cluster.local"

    def statefulset_needs_migrations(self, stateful_set: V1StatefulSet) -> bool:
        """Check if statefulset needs a migration."""

        # Needs migration due to change of service name to headless service name
        # TODO: Remove after upgrade to v0.8.0
        # ----
        if stateful_set is None:
            return False
        if stateful_set.spec.service_name != self.headless_service_name:
            return True
        return False

    async def request_rebalance(self) -> bool:
        """Request a cluster rebalance when the app cluster is in ready state.

        Ready state is defined as:
        - availableReplicas equals desiredReplicas
        - At least one member is a leader

        Raises:
            Exception: If cluster is not in ready state or rebalance fails
        """
        status = await self.fetch_app_status()

        if not status:
            return False, "App status not available"

        # Check if cluster is in ready state
        available_replicas = status.get("availableReplicas", 0)
        desired_replicas = status.get("desiredReplicas", 0)
        members = status.get("members", [])

        if available_replicas != desired_replicas:
            self.logger.warning(
                f"Cannot request rebalance: cluster not ready "
                f"(available={available_replicas}, desired={desired_replicas})"
            )
            return False, "Cluster not ready"

        if not members:
            self.logger.warning("Cannot request rebalance: no member status available")
            return False, "No member status available"

        # Find the leader member
        leader_idx = None
        for member_status in members:
            if member_status.get("leader"):
                leader_idx = member_status["id"]
                break

        if leader_idx is None:
            self.logger.warning("Cannot request rebalance: leader member not found")
            return False, "Leader member not found"

        # Request rebalance on the leader member
        try:
            # Convert string index to int for prepare_member_url
            leader_url = self.prepare_member_url(int(leader_idx))
            self.logger.info(
                f"Requesting rebalance on leader member {leader_idx} at {leader_url}"
            )
            await self.web_client.rebalance(leader_url)
            self.logger.info(f"Rebalance successfully requested on member {leader_idx}")
            return True, "Rebalance requested successfully"
        except Exception as e:
            self.logger.error(
                f"Failed to request rebalance on member {leader_idx}: {e}"
            )
            raise

    @cached_property
    def static_group_membership_enabled(self) -> bool:
        """Check if static group membership is enabled."""
        return "kaspr.io/disable-static-group-membership" not in self.annotations or (
            self.annotations["kaspr.io/disable-static-group-membership"].lower() != "true"
        )

    @property
    def reconciliation_paused(self) -> bool:
        """Check if reconciliation is paused."""
        return (
            "kaspr.io/pause-reconciliation" in self.annotations
            and self.annotations["kaspr.io/pause-reconciliation"].lower() == "true"
        )

    @cached_property
    def version(self) -> KasprVersion:
        return self.prepare_version()

    @cached_property
    def image(self) -> str:
        return self.prepare_image()

    @cached_property
    def web_port(self) -> int:
        return getattr(self.config, "web_port", self.DEFAULT_WEB_PORT)

    @cached_property
    def data_dir_path(self):
        return getattr(self.config, "data_dir", self.DEFAULT_DATA_DIR)

    @cached_property
    def table_dir_path(self):
        return getattr(self.config, "table_dir", self.DEFAULT_TABLE_DIR)

    @cached_property
    def definitions_dir_path(self):
        return getattr(self.config, "definitions_dir", self.DEFAULT_DEFINITIONS_DIR)

    @cached_property
    def api_client(self) -> ApiClient:
        if self._api_client is None:
            # Use the shared API client if available, otherwise create a new one
            if self.shared_api_client is not None:
                self._api_client = self.shared_api_client
            else:
                self._api_client = ApiClient()
        return self._api_client

    @cached_property
    def apps_v1_api(self) -> AppsV1Api:
        if self._apps_v1_api is None:
            self._apps_v1_api = AppsV1Api(self.api_client)
        return self._apps_v1_api

    @cached_property
    def core_v1_api(self) -> CoreV1Api:
        if self._core_v1_api is None:
            self._core_v1_api = CoreV1Api(self.api_client)
        return self._core_v1_api

    @cached_property
    def autoscaling_v2_api(self) -> AutoscalingV2Api:
        if self._autoscaling_v2_api is None:
            self._autoscaling_v2_api = AutoscalingV2Api(self.api_client)
        return self._autoscaling_v2_api

    @cached_property
    def custom_objects_api(self) -> CustomObjectsApi:
        if self._custom_objects_api is None:
            self._custom_objects_api = CustomObjectsApi(self.api_client)
        return self._custom_objects_api

    @cached_property
    def service(self) -> V1Service:
        if self._service is None:
            self._service = self.prepare_service()
        return self._service

    @cached_property
    def service_hash(self) -> str:
        if self._service_hash is None:
            self._service_hash = self.prepare_service_hash(self.service)
        return self._service_hash

    @cached_property
    def headless_service(self) -> V1Service:
        if self._headless_service is None:
            self._headless_service = self.prepare_headless_service()
        return self._headless_service

    @cached_property
    def headless_service_hash(self) -> str:
        if self._headless_service is None:
            self._headless_service = self.prepare_headless_service_hash(
                self.headless_service
            )
        return self._headless_service_hash

    @cached_property
    def service_account(self) -> V1ServiceAccount:
        if self._service_account is None:
            self._service_account = self.prepare_service_account()
        return self._service_account

    @cached_property
    def service_account_hash(self) -> str:
        if self._service_account_hash is None:
            self._service_account_hash = self.prepare_service_account_hash(
                self.service_account
            )
        return self._service_account_hash

    @cached_property
    def settings_config_map(self) -> V1ConfigMap:
        if self._settings_config_map is None:
            self._settings_config_map = self.prepare_settings_config_map()
        return self._settings_config_map

    @cached_property
    def settings_config_map_hash(self) -> str:
        if self._settings_config_map_hash is None:
            self._settings_config_map_hash = self.prepare_settings_config_map_hash(
                self.settings_config_map
            )
        return self._settings_config_map_hash

    @cached_property
    def env_dict(self) -> Dict[str, str]:
        if self._env_dict is None:
            self._env_dict = self.prepare_env_dict()
        return self._env_dict

    @cached_property
    def config_hash(self) -> str:
        if self._config_hash is None:
            self._config_hash = self.compute_hash(self.settings_config_map.data)
        return self._config_hash

    @cached_property
    def sasl_credentials(self) -> SASLCredentials:
        return self.authentication.sasl_credentials

    @cached_property
    def env_vars(self) -> List[V1EnvVar]:
        if self._env_vars is None:
            self._env_vars = self.prepare_env_vars()
        return self._env_vars

    @cached_property
    def container_ports(self) -> List[V1ContainerPort]:
        if self._container_ports is None:
            self._container_ports = self.prepare_container_ports()
        return self._container_ports

    @cached_property
    def persistent_volume_claim(self) -> V1PersistentVolumeClaim:
        if self._persistent_volume_claim is None:
            self._persistent_volume_claim = self.prepare_persistent_volume_claim()
        return self._persistent_volume_claim

    @cached_property
    def persistent_volume_claim_hash(self) -> str:
        if self._persistent_volume_claim_hash is None:
            self._persistent_volume_claim_hash = (
                self.prepare_persistent_volume_claim_hash(self.persistent_volume_claim)
            )
        return self._persistent_volume_claim_hash

    @cached_property
    def persistent_volume_claim_retention_policy(self):
        if self._persistent_volume_claim_retention_policy is None:
            self._persistent_volume_claim_retention_policy = (
                self.prepare_persistent_volume_claim_retention_policy()
            )
        return self._persistent_volume_claim_retention_policy

    @cached_property
    def python_packages_pvc_name(self) -> str:
        if self._packages_pvc_name is None:
            self._packages_pvc_name = f"{self.component_name}-python-packages"
        return self._packages_pvc_name

    @cached_property
    def python_packages_pvc(self) -> Optional[V1PersistentVolumeClaim]:
        if self._packages_pvc is None:
            self._packages_pvc = self.prepare_python_packages_pvc()
        return self._packages_pvc

    @cached_property
    def python_packages_pvc_hash(self) -> Optional[str]:
        if self._packages_pvc_hash is None and self.python_packages_pvc:
            self._packages_pvc_hash = self.prepare_python_packages_pvc_hash(self.python_packages_pvc)
        return self._packages_pvc_hash

    @cached_property
    def packages_init_container(self) -> Optional[V1Container]:
        if self._packages_init_container is None:
            self._packages_init_container = self.prepare_packages_init_container()
        return self._packages_init_container

    @cached_property
    def volume_mounts(self) -> List[V1VolumeMount]:
        if self._volume_mounts is None:
            self._volume_mounts = self.prepare_volume_mounts()
        return self._volume_mounts

    @cached_property
    def volumes(self) -> List[V1Volume]:
        if self._volumes is None:
            self._volumes = self.prepare_volumes()
        return self._volumes

    @cached_property
    def kaspr_container(self) -> V1Container:
        if self._kaspr_container is None:
            self._kaspr_container = self.prepare_kaspr_container()
        return self._kaspr_container

    @cached_property
    def pod_template(self) -> V1PodTemplateSpec:
        if self._pod_template is None:
            self._pod_template = self.prepare_pod_template()
        return self._pod_template

    @cached_property
    def pod_spec(self) -> V1PodSpec:
        if self._pod_spec is None:
            self._pod_spec = self.prepare_pod_spec()
        return self._pod_spec

    @cached_property
    def stateful_set(self) -> V1StatefulSet:
        if self._stateful_set is None:
            self._stateful_set = self.prepare_statefulset()
        return self._stateful_set

    @cached_property
    def stateful_set_hash(self) -> str:
        if self._stateful_set_hash is None:
            self._stateful_set_hash = self.prepare_statefulset_hash(self.stateful_set)
        return self._stateful_set_hash

    @cached_property
    def hpa_hash(self) -> str:
        if self._hpa_hash is None:
            self._hpa_hash = self.prepare_hpa_hash(self.hpa)
        return self._hpa_hash

    @cached_property
    def agent_pod_volumes(self) -> List[V1Volume]:
        if self._agent_pod_volumes is None:
            self._agent_pod_volumes = self.prepare_agent_volumes()
        return self._agent_pod_volumes

    @cached_property
    def webview_pod_volumes(self) -> List[V1Volume]:
        if self._webview_pod_volumes is None:
            self._webview_pod_volumes = self.prepare_webview_volumes()
        return self._webview_pod_volumes

    @cached_property
    def table_pod_volumes(self) -> List[V1Volume]:
        if self._table_pod_volumes is None:
            self._table_pod_volumes = self.prepare_table_volumes()
        return self._table_pod_volumes

    @cached_property
    def task_pod_volumes(self) -> List[V1Volume]:
        if self._task_pod_volumes is None:
            self._task_pod_volumes = self.prepare_task_volumes()
        return self._task_pod_volumes

    @cached_property
    def hpa(self) -> V2HorizontalPodAutoscaler:
        if self._hpa is None:
            self._hpa = self.prepare_hpa()
        return self._hpa

    @cached_property
    def agents_hash(self) -> str:
        """Hash of all agents."""
        if self._agents_hash is None:
            self._agents_hash = (
                self.compute_hash("".join(agent.hash for agent in self.agents))
                if self.agents
                else None
            )
        return self._agents_hash

    @cached_property
    def webviews_hash(self) -> str:
        """Hash of all webviews."""
        if self._webviews_hash is None:
            self._webviews_hash = (
                self.compute_hash("".join(webview.hash for webview in self.webviews))
                if self.webviews
                else None
            )
        return self._webviews_hash

    @cached_property
    def tables_hash(self) -> str:
        """Hash of all tables."""
        if self._tables_hash is None:
            self._tables_hash = (
                self.compute_hash("".join(table.hash for table in self.tables))
                if self.tables
                else None
            )
        return self._tables_hash

    @cached_property
    def tasks_hash(self) -> str:
        """Hash of all tasks."""
        if self._tasks_hash is None:
            self._tasks_hash = (
                self.compute_hash("".join(task.hash for task in self.tasks))
                if self.tasks
                else None
            )
        return self._tasks_hash

    @cached_property
    def packages_hash(self) -> Optional[str]:
        """Hash of Python packages configuration."""
        if self._packages_hash is None and self.python_packages:
            # Import here to avoid circular dependency
            from kaspr.utils.python_packages import compute_packages_hash
            self._packages_hash = compute_packages_hash(self.python_packages)
        return self._packages_hash
