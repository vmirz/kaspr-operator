import kopf
import time
from typing import List, Dict, Optional
from kaspr.utils.objects import cached_property
from kaspr.types.models.kasprapp_spec import KasprAppSpec
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
from kaspr.types.models.storage import KasprAppStorage
from kaspr.types.models.resource_requirements import ResourceRequirements
from kaspr.types.models.probe import Probe
from kubernetes.client import (
    AppsV1Api,
    CoreV1Api,
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
    V1PersistentVolumeClaimSpec,
    V1PersistentVolumeClaim,
    V1PersistentVolumeClaimTemplate,
    V1StatefulSetPersistentVolumeClaimRetentionPolicy,
    V1ConfigMap,
    V1EnvVar,
    V1EnvVarSource,
    V1ConfigMapKeySelector,
    V1SecretKeySelector,
    V1ResourceRequirements,
    V1Probe,
    V1DeleteOptions,
)

from kaspr.resources.base import BaseResource
from kaspr.common.models.labels import Labels


class KasprApp(BaseResource):
    """Kaspr App kubernetes resource."""

    KIND = "KasprApp"
    COMPONENT_TYPE = "app"
    WEB_PORT_NAME = "http"
    KASPR_CONTAINER_NAME = "kaspr"

    DEFAULT_REPLICAS = 1
    DEFAULT_TABLE_DIR = "/var/lib/data/tables"
    DEFAULT_WEB_PORT = 6065

    replicas: int
    image: str
    service_name: str
    config_map_name: str
    persistent_volume_claim_name: str
    stateful_set_name: str
    bootstrap_servers: str

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
    _service: V1Service = None
    _persistent_volume_claim: V1PersistentVolumeClaim = None
    _persistent_volume_claim_retention_policy: V1StatefulSetPersistentVolumeClaimRetentionPolicy = None
    _settings_config_map: V1ConfigMap = None
    _env_vars: List[V1EnvVar] = None
    _volume_mounts: List[V1VolumeMount] = None
    _container_ports: List[V1ContainerPort] = None
    _stateful_set: V1StatefulSet = None
    _kaspr_container: V1Container = None
    _pod_template: V1PodTemplateSpec = None

    # TODO: Templates allow customizing k8s behavior
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
    ):
        component_name = KasprAppResources.component_name(name)
        labels = Labels.generate_default_labels(
            name,
            kind,
            component_name,
            component_type,
            self.KASPR_OPERATOR_NAME,
        )
        super().__init__(
            cluster=name,
            namespace=namespace,
            component_name=component_name,
            labels=labels,
        )

    @classmethod
    def from_spec(
        self, name: str, kind: str, namespace: str, spec: KasprAppSpec
    ) -> "KasprApp":
        app = KasprApp(name, kind, namespace, self.KIND)
        app.service_name = KasprAppResources.service_name(name)
        app.config_map_name = KasprAppResources.settings_config_name(name)
        app.stateful_set_name = KasprAppResources.stateful_set_name(name)
        app.persistent_volume_claim_name = (
            KasprAppResources.persistent_volume_claim_name(name)
        )
        app._version = spec.version
        app._image = spec.image
        app.replicas = spec.replicas or self.DEFAULT_REPLICAS
        app.bootstrap_servers = spec.bootstrap_servers
        app.tls = spec.tls
        app.authentication = spec.authentication
        app.config = spec.config
        app.resources = spec.resources
        app.liveness_probe = spec.liveness_probe
        app.readiness_probe = spec.readiness_probe
        app.storage = spec.storage
        return app

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
        labels = self.labels.as_dict()
        service = V1Service(
            api_version="v1",
            kind="Service",
            metadata=V1ObjectMeta(name=self.service_name, labels=labels),
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
        return service

    def prepare_config_map(self) -> V1ConfigMap:
        """Build a config map resource."""
        return V1ConfigMap(
            metadata=V1ObjectMeta(
                name=self.config_map_name,
                namespace=self.namespace,
                labels=self.labels.as_dict(),
            ),
            data=self.prepare_env_dict(),
        )

    def prepare_persistent_volume_claim(self) -> V1PersistentVolumeClaim:
        """Build a PVC resource for statefulset."""
        return V1PersistentVolumeClaimTemplate(
            metadata=V1ObjectMeta(name=self.persistent_volume_claim_name),
            spec=V1PersistentVolumeClaimSpec(
                access_modes=["ReadWriteOnce"],
                resources=V1ResourceRequirements(
                    requests={"storage": self.storage.size}
                ),
                storage_class_name=self.storage.storage_class,
            ),
        )

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

        # include config hash
        env_vars.append(V1EnvVar(name="CONFIG_HASH", value=self.config_hash))

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
            env_for("table_dir"): self.table_dir_path,
            env_for("kms_enabled"): "false",
            env_for("topic_prefix"): self.topic_prefix,
        }
        _envs = {**config_envs}
        _envs.update(overrides)
        return _envs

    def prepare_volume_mounts(self) -> List[V1VolumeMount]:
        volume_mounts = []
        volume_mounts.append(
            V1VolumeMount(
                name=self.persistent_volume_claim_name, mount_path=self.table_dir_path
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
        return V1PodTemplateSpec(
            metadata=V1ObjectMeta(labels=self.labels.as_dict()),
            spec=V1PodSpec(
                containers=[self.kaspr_container],
            ),
        )

    def prepare_statefulset(self) -> V1StatefulSetSpec:
        return V1StatefulSet(
            api_version="apps/v1",
            kind="StatefulSet",
            metadata=V1ObjectMeta(name=self.component_name),
            spec=V1StatefulSetSpec(
                replicas=self.replicas,
                service_name=self.service_name,
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
        self.create_config_map(
            self.core_v1_api, self.namespace, self.settings_config_map
        )
        self.create_service(self.core_v1_api, self.namespace, self.service)
        self.create_stateful_set(self.apps_v1_api, self.namespace, self.stateful_set)

    def patch_replicas(self):
        self.patch_stateful_set(
            self.apps_v1_api,
            self.stateful_set_name,
            self.namespace,
            stateful_set={"spec": {"replicas": self.replicas}},
        )

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
        self.patch_config_map(
            self.core_v1_api,
            self.config_map_name,
            self.namespace,
            self.settings_config_map,
        )
        service = self.fetch_service(
            self.core_v1_api, self.service_name, self.namespace
        )
        if service:
            service.spec.ports[0].port = self.web_port
            service.spec.ports[0].target_port = self.web_port
            self.replace_service(
                self.core_v1_api, self.service_name, self.namespace, service
            )
        stateful_set = self.fetch_stateful_set(
            self.apps_v1_api, self.stateful_set_name, self.namespace
        )
        if stateful_set:
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
        self.patch_stateful_set(
            self.apps_v1_api, self.stateful_set_name, self.namespace, stateful_set=patch
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
            time.sleep(5)
        self.unite()
        # Recreate the statefulset with new storage size PVC template
        self.create_stateful_set(self.apps_v1_api, self.namespace, self.stateful_set)
        # Update existing PVCs
        pvcs = self.list_persistent_volume_claims(
            self.core_v1_api, namespace=self.namespace
        )
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

    def unite(self):
        """Ensure all child resources are owned by the root resource"""
        children = [self.settings_config_map, self.service, self.stateful_set]
        kopf.adopt(children)

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
    def table_dir_path(self):
        return getattr(self.config, "table_dir", self.DEFAULT_TABLE_DIR)

    @cached_property
    def topic_prefix(self):
        return getattr(self.config, "topic_prefix", f"{self.cluster}.")

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
    def service(self) -> V1Service:
        if self._service is None:
            self._service = self.prepare_service()
        return self._service

    @cached_property
    def settings_config_map(self) -> V1ConfigMap:
        if self._settings_config_map is None:
            self._settings_config_map = self.prepare_config_map()
        return self._settings_config_map

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
    def stateful_set(self) -> V1StatefulSet:
        if self._stateful_set is None:
            self._stateful_set = self.prepare_statefulset()
        return self._stateful_set
