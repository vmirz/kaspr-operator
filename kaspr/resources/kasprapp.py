import kopf
import time
from typing import List, Dict, Optional
from kaspr.utils.objects import cached_property
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
from kubernetes.client import (
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

from kaspr.resources.base import BaseResource
from kaspr.resources import KasprAgent, KasprWebView, KasprTable
from kaspr.common.models.labels import Labels
from kaspr.web import KasprWebClient


class KasprApp(BaseResource):
    """Kaspr App kubernetes resource."""

    conf: Settings
    web_client: KasprWebClient

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

    # derived from spec
    _env_dict: Dict[str, str] = None
    _config_hash: str = None
    _version: str = None
    _image: str = None

    # k8s resources
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
    _hpa: V2HorizontalPodAutoscaler = None

    # Reference to agent resources
    agents: List[KasprAgent] = None
    webviews: List[KasprWebView] = None
    tables: List[KasprTable] = None
    _webviews_hash: str = None
    _agents_hash: str = None
    _tables_hash: str = None

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
    ) -> "KasprApp":
        app = KasprApp(name, kind, namespace, self.KIND)
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

    def synchronize(self) -> "KasprApp":
        """Compare current state with desired state for all child resources and create/patch as needed."""
        self.sync_auth_credentials()
        self.sync_service()
        self.sync_headless_service()
        self.sync_service_account()
        self.sync_settings_config_map()
        self.sync_hpa()
        self.sync_stateful_set()

    def sync_service(self):
        """Check current state of service and create/patch if needed."""
        service: V1Service = self.fetch_service(
            self.core_v1_api, self.service_name, self.namespace
        )
        if not service:
            self.create_service(self.core_v1_api, self.namespace, self.service)
        else:
            actual = self.prepare_service_watch_fields(service)
            desired = self.prepare_service_watch_fields(self.service)
            if self.compute_hash(actual) != self.compute_hash(desired):
                self.patch_service(
                    self.core_v1_api,
                    self.service_name,
                    self.namespace,
                    service=self.prepare_service_patch(self.service),
                )

    def sync_headless_service(self):
        """Check current state of headless service and create/patch if needed"""
        headless_service: V1Service = self.fetch_service(
            self.core_v1_api, self.headless_service_name, self.namespace
        )
        if not headless_service:
            self.create_service(self.core_v1_api, self.namespace, self.headless_service)
        else:
            actual = self.prepare_headless_service_watch_fields(headless_service)
            desired = self.prepare_headless_service_watch_fields(self.headless_service)
            if self.compute_hash(actual) != self.compute_hash(desired):
                self.patch_service(
                    self.core_v1_api,
                    self.service_name,
                    self.namespace,
                    service=self.prepare_headless_service_patch(self.headless_service),
                )

    def sync_service_account(self):
        """Check current state of service account and create/patch if needed."""
        service_account: V1ServiceAccount = self.fetch_service_account(
            self.core_v1_api, self.service_account_name, self.namespace
        )
        if not service_account:
            self.create_service_account(
                self.core_v1_api, self.namespace, self.service_account
            )
        else:
            ...
            # not much to patch for a service account

    def sync_settings_config_map(self):
        """Check current state of config map and create/patch if needed."""
        settings_config_map: V1ConfigMap = self.fetch_config_map(
            self.core_v1_api, self.config_map_name, self.namespace
        )
        if not settings_config_map:
            self.create_config_map(
                self.core_v1_api, self.namespace, self.settings_config_map
            )
        else:
            actual = self.prepare_settings_config_map_watch_fields(settings_config_map)
            desired = self.prepare_settings_config_map_watch_fields(
                self.settings_config_map
            )
            if self.compute_hash(actual) != self.compute_hash(desired):
                self.patch_config_map(
                    self.core_v1_api,
                    self.config_map_name,
                    self.namespace,
                    config_map=self.prepare_settings_config_map_patch(
                        self.settings_config_map
                    ),
                )

    def sync_stateful_set(self):
        """Check current state of stateful set and create/patch if needed."""
        stateful_set: V1StatefulSet = self.fetch_stateful_set(
            self.apps_v1_api, self.stateful_set_name, self.namespace
        )
        if stateful_set and self.statefulset_needs_migrations(stateful_set):
            self.recreate_statefulset(stateful_set)
            return

        if not stateful_set:
            self.create_stateful_set(
                self.apps_v1_api, self.namespace, self.stateful_set
            )
        else:
            actual = self.prepare_statefulset_watch_fields(stateful_set)
            desired = self.prepare_statefulset_watch_fields(self.stateful_set)

            replicas_override = self.prepare_statefulset_desired_replicas(actual)
            if replicas_override is not None:
                desired["spec"]["replicas"] = replicas_override
            elif desired["spec"]["replicas"] is None:
                desired["spec"]["replicas"] = actual["spec"]["replicas"]

            if self.compute_hash(actual) != self.compute_hash(desired):
                self.patch_stateful_set(
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

    def sync_auth_credentials(self):
        """Sync credentials secret; We only need to check that password secret exists."""
        if self.authentication.sasl_enabled and self.sasl_credentials.password:
            secret = self.fetch_secret(
                self.core_v1_api,
                self.sasl_credentials.password.secret_name,
                self.namespace,
            )
            if not secret:
                raise kopf.TemporaryError(
                    f"Secret `{self.sasl_credentials.password.secret_name}` not found in `{self.namespace}` namespace."
                )

    def sync_hpa(self):
        """Check current state of HPA and create/delete/patch if needed."""
        hpa: V2HorizontalPodAutoscaler = self.fetch_hpa(
            self.autoscaling_v2_api, self.hpa_name, self.namespace
        )
        # If reconciliation is paused, delete HPA so it does not interfere with manual changes to statefulset
        if hpa and self.reconciliation_paused:
            self.delete_hpa(self.autoscaling_v2_api, self.hpa_name, self.namespace)
            return
        elif hpa and self.replicas == 0:
            self.delete_hpa(self.autoscaling_v2_api, self.hpa_name, self.namespace)
            return
        elif self.replicas > 0:
            if not hpa:
                self.create_hpa(self.autoscaling_v2_api, self.namespace, self.hpa)
            else:
                actual = self.prepare_hpa_watch_fields(hpa)
                desired = self.prepare_hpa_watch_fields(self.hpa)
                if self.compute_hash(actual) != self.compute_hash(desired):
                    self.patch_hpa(
                        self.autoscaling_v2_api,
                        self.hpa_name,
                        self.namespace,
                        hpa=self.prepare_hpa_patch(self.hpa),
                    )

    def recreate_statefulset(self, stateful_set: V1StatefulSet):
        """Check if statefulset needs migrations and perform them."""
        self.delete_stateful_set(
            self.apps_v1_api,
            self.stateful_set_name,
            self.namespace,
            delete_options=V1DeleteOptions(propagation_policy="Orphan"),
        )
        # We need to wait a bit to allow k8s to actually execute the deletion
        # before moving on to recreate the statefulset.
        time.sleep(self.conf.statefulset_deletion_timeout_seconds)
        self.sync_stateful_set()

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

    def fetch(self, name: str, namespace: str):
        """Fetch actual KasprApp in kubernetes."""
        return self.get_custom_object(
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

        # include consumer group instance id (for static membership)
        # the value is derived from the pod name, which is why we configure
        # here instead of in the config map
        env_vars.append(
            V1EnvVar(
                name=self.config.env_for("consumer_group_instance_id"),
                value_from=V1EnvVarSource(
                    field_ref=V1ObjectFieldSelector(field_path="metadata.name")
                ),
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

    def prepare_agent_mount_path(self, agent: KasprAgent) -> str:
        return f"{self.definitions_dir_path}/{agent.file_name}"

    def prepare_webview_mount_path(self, webview: KasprWebView) -> str:
        return f"{self.definitions_dir_path}/{webview.file_name}"

    def prepare_table_mount_path(self, table: KasprTable) -> str:
        return f"{self.definitions_dir_path}/{table.file_name}"

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
                *self.prepare_container_template_volume_mounts(),
            ]
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
        volumes.extend(self.prepare_pod_template_volumes())
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
            containers=[self.kaspr_container],
            volumes=self.volumes,
        )

    def prepare_statefulset(self) -> V1StatefulSetSpec:
        """Build stateful set resource."""
        labels, annotations = {}, {}
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
                volume_claim_templates=[self.persistent_volume_claim],
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
        return {
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

    def patch_settings(self):
        """Update resources as a result of app settings change."""
        self.patch_config_map(
            self.core_v1_api,
            self.config_map_name,
            self.namespace,
            self.settings_config_map,
        )
        self.patch_stateful_set(
            self.apps_v1_api,
            self.stateful_set_name,
            self.namespace,
            stateful_set={"spec": {"template": self.pod_template}},
        )

    def create(self):
        """Create KMS resources."""
        self.unite()
        self.sync_service_account()
        self.sync_settings_config_map()
        self.sync_service()
        self.sync_headless_service()
        self.sync_stateful_set()

    def patch_replicas(self):
        if self.replicas == 0:
            # If replicas is set to 0, we don't want to patch the HPA as that would
            # result in an invalid configuration. Instead we just delete the HPA
            self.delete_hpa(self.autoscaling_v2_api, self.hpa_name, self.namespace)
            self.patch_stateful_set(
                self.apps_v1_api,
                self.stateful_set_name,
                self.namespace,
                stateful_set={"spec": {"replicas": self.replicas}},
            )
            return
        else:
            self.sync_hpa()
            self.sync_stateful_set()

    def patch_version(self):
        self.patch_stateful_set(
            self.apps_v1_api,
            self.stateful_set_name,
            self.namespace,
            stateful_set={"spec": {"template": self.pod_template}},
        )

    def patch_kafka_credentials(self):
        self.patch_settings()

    def patch_resource_requirements(self):
        self.patch_stateful_set(
            self.apps_v1_api,
            self.stateful_set_name,
            self.namespace,
            stateful_set={"spec": {"template": self.pod_template}},
        )

    def patch_web_port(self):
        """Update resources to change app web port."""
        if not self.fetch_config_map(
            self.core_v1_api, self.config_map_name, self.namespace
        ):
            raise kopf.TemporaryError(
                f"ConfigMap `{self.config_map_name}` not found in `{self.namespace}` namespace."
            )
        self.patch_config_map(
            self.core_v1_api,
            self.config_map_name,
            self.namespace,
            self.settings_config_map,
        )
        service = self.fetch_service(
            self.core_v1_api, self.service_name, self.namespace
        )
        if not service:
            raise kopf.TemporaryError(
                f"Service `{self.service_name}` not found in `{self.namespace}` namespace."
            )
        service.spec.ports[0].port = self.web_port
        service.spec.ports[0].target_port = self.web_port
        self.replace_service(
            self.core_v1_api, self.service_name, self.namespace, service
        )
        stateful_set = self.fetch_stateful_set(
            self.apps_v1_api, self.stateful_set_name, self.namespace
        )
        if not stateful_set:
            raise kopf.TemporaryError(
                f"StatefulSet `{self.stateful_set_name}` not found in `{self.namespace}` namespace."
            )
        stateful_set.spec.template.spec.containers[0].ports[
            0
        ].container_port = self.web_port
        self.replace_stateful_set(
            self.apps_v1_api,
            self.stateful_set_name,
            self.namespace,
            stateful_set=stateful_set,
        )

    def patch_storage_retention_policy(self):
        patch = {
            "spec": {
                "persistentVolumeClaimRetentionPolicy": self.persistent_volume_claim_retention_policy
            }
        }
        if not self.fetch_stateful_set(
            self.apps_v1_api, self.stateful_set_name, self.namespace
        ):
            raise kopf.TemporaryError(
                f"StatefulSet `{self.stateful_set_name}` not found in `{self.namespace}` namespace."
            )
        self.patch_stateful_set(
            self.apps_v1_api,
            self.stateful_set_name,
            self.namespace,
            stateful_set=patch,
        )

    def patch_storage_size(self):
        # We can't directly patch the stateful set PVC template with new storage size.
        # So must must do the following:
        #  - Delete the statefulset with orphaned pods.
        #  - Recreate the statefulset with the updated PVC template storage size
        #  - Update storage size on all existing PVCs
        stateful_set = self.fetch_stateful_set(
            self.apps_v1_api, self.stateful_set_name, self.namespace
        )
        if stateful_set:
            self.delete_stateful_set(
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
        self.create_stateful_set(self.apps_v1_api, self.namespace, self.stateful_set)
        # Update existing PVCs
        pvcs = self.list_persistent_volume_claims(
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
                self.patch_persistent_volume_claim(
                    self.core_v1_api, pvc.metadata.name, self.namespace, pvc
                )

    def patch_volume_mounted_resources(self):
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
        if not self.fetch_stateful_set(
            self.apps_v1_api, self.stateful_set_name, self.namespace
        ):
            raise kopf.TemporaryError(
                f"StatefulSet `{self.stateful_set_name}` not found in `{self.namespace}` namespace."
            )
        self.patch_stateful_set(
            self.apps_v1_api,
            self.stateful_set_name,
            self.namespace,
            stateful_set=patch,
        )

    def patch_template_service_account(self):
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
        if not self.fetch_service_account(
            self.core_v1_api, self.service_account_name, self.namespace
        ):
            raise kopf.TemporaryError(
                f"ServiceAccount `{self.service_account_name}` not found in `{self.namespace}` namespace."
            )
        self.patch_service_account(
            self.core_v1_api,
            self.service_account_name,
            self.namespace,
            patch,
        )

    def patch_template_pod(self):
        """Update pod template."""
        patch = [
            {
                "op": "replace",
                "path": "/spec/template",
                "value": self.pod_template,
            },
        ]
        if not self.fetch_stateful_set(
            self.apps_v1_api, self.stateful_set_name, self.namespace
        ):
            raise kopf.TemporaryError(
                f"StatefulSet `{self.stateful_set_name}` not found in `{self.namespace}` namespace."
            )
        self.patch_stateful_set(
            self.apps_v1_api,
            self.stateful_set_name,
            self.namespace,
            stateful_set=patch,
        )

    def patch_template_service(self):
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
        if not self.fetch_service(self.core_v1_api, self.service_name, self.namespace):
            raise kopf.TemporaryError(
                f"Service `{self.service_name}` not found in `{self.namespace}` namespace."
            )
        self.patch_service(
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
        kopf.adopt(children)

    def search(self, namespace: str, apps: List[str] = None):
        """Search for KasprApps in kubernetes."""
        label_selector = (
            ",".join(f"{self.KASPR_APP_NAME_LABEL}={app}" for app in apps)
            if apps
            else None
        )
        return self.list_custom_objects(
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

    async def fetch_app_status(self) -> Dict:
        """Fetch status of application's statefulset/pods"""
        stateful_set = self.fetch_stateful_set(
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

        if stateful_set.status.available_replicas > 0 and kaspr_container:
            if self.conf.client_status_check_enabled:
                # Fetch status from all workers concurrently
                async def fetch_worker_status(idx: int):
                    """Fetch status from a single worker."""
                    try:
                        url = self.prepare_worker_url(idx)
                        status = await self.web_client.get_status(url)
                        return idx, status
                    except Exception as e:
                        print(f"Failed to get status from Kaspr instance {idx}: {e}")
                        return idx, None
                
                # Create tasks for all workers
                tasks = [
                    fetch_worker_status(idx) 
                    for idx in range(stateful_set.status.available_replicas)
                ]
                
                # Wait for all tasks with 5 second timeout
                try:
                    results = await asyncio.wait_for(
                        asyncio.gather(*tasks, return_exceptions=False),
                        timeout=5.0
                    )
                    
                    # Filter out failed calls and collect successful results
                    worker_statuses = {}
                    for idx, status in results:
                        if status is not None:
                            worker_statuses[idx] = status
                            print(f"Kaspr instance {idx} status: {status}")
                    
                    if not worker_statuses:
                        print("Warning: All worker status checks failed")
                    
                except asyncio.TimeoutError:
                    raise Exception("Timeout: Failed to fetch worker statuses within 5 seconds")

        kaspr_ver = kaspr_container.image.split(":")[-1] if kaspr_container else None
        available_replicas = (
            stateful_set.status.available_replicas if stateful_set.status else 0
        )

        return {
            "kasprVersion": kaspr_ver,
            "availableReplicas": available_replicas,
            "desiredReplicas": self.replicas,
        }

    def prepare_worker_url(self, pod_index: int) -> str:
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
    def apps_v1_api(self) -> AppsV1Api:
        if self._apps_v1_api is None:
            self._apps_v1_api = AppsV1Api()
        return self._apps_v1_api

    @cached_property
    def core_v1_api(self) -> CoreV1Api:
        if self._core_v1_api is None:
            self._core_v1_api = CoreV1Api()
        return self._core_v1_api

    @cached_property
    def autoscaling_v2_api(self) -> AutoscalingV2Api:
        if self._autoscaling_v2_api is None:
            self._autoscaling_v2_api = AutoscalingV2Api()
        return self._autoscaling_v2_api

    @cached_property
    def custom_objects_api(self) -> CustomObjectsApi:
        if self._custom_objects_api is None:
            self._custom_objects_api = CustomObjectsApi()
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
