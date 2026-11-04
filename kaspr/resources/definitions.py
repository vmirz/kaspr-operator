"""How a KasprApp's components reach its pods (docs/design/definitions-bundle.md).

In ``components`` mode every component has a ConfigMap of its own, mounted into the
pods as one file. In ``bundle`` mode the KasprApp writes all of its components into
one YAML document, kept in immutable, content-addressed ConfigMaps (shards) that the
app owns, each mounted as one file.
"""

import hashlib
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Set

import kopf
import yaml
from kubernetes_asyncio.client import (
    V1ConfigMap,
    V1ConfigMapVolumeSource,
    V1KeyToPath,
    V1ObjectMeta,
    V1StatefulSet,
    V1Volume,
    V1VolumeMount,
)

from kaspr.types.models import KasprAppComponents
from kaspr.types.schemas import KasprAppComponentsSchema
from kaspr.utils.helpers import ordered_dict_to_dict

DELIVERY_ANNOTATION = "kaspr.io/definitions-delivery"
COMPONENTS = "components"
BUNDLE = "bundle"
MODES = (COMPONENTS, BUNDLE)

APP_LABEL = "kaspr.io/app"
SHARD_LABEL = "kaspr.io/component"
SHARD_LABEL_VALUE = "definitions"
SHARD_INDEX_ANNOTATION = "kaspr.io/definitions-shard"
SHARD_COMPONENTS_ANNOTATION = "kaspr.io/definitions-components"
SHARD_KEY = "definitions.yaml"
VOLUME_PREFIX = "kaspr-definitions-"

# A ConfigMap holds at most 1 MiB of data; shards stay below that with room to spare.
HARD_LIMIT_BYTES = 1_000_000
MIN_SHARD_BYTES = 64 * 1024
DEFAULT_SHARD_BYTES = 512 * 1024

# Kaspr builds tables, joins, tasks and agents in this order within one file, and
# files in directory order. A join needs its tables and an agent may read a join's
# channel, so these kinds always share the first shard. Webviews are registered
# once every file is built, so they may spill into further shards.
CORE_KINDS = ("tables", "joins", "tasks", "agents")
KINDS = CORE_KINDS + ("webviews",)

# The kinds that own per-component ConfigMaps, and the suffix of those ConfigMaps' names.
COMPONENT_API_VERSION = "kaspr.io/v1alpha1"
COMPONENT_CONFIG_MAP_SUFFIXES = {
    "KasprAgent": "-agent",
    "KasprWebView": "-webview",
    "KasprTable": "-table",
    "KasprTask": "-task",
    "KasprJoin": "-join",
}

try:
    _SafeLoader = yaml.CSafeLoader
except AttributeError:  # PyYAML built without LibYAML
    _SafeLoader = yaml.SafeLoader


class DefinitionsTooLarge(kopf.PermanentError):
    """A shard would hold more than a ConfigMap can."""


class DefinitionsConflict(kopf.PermanentError):
    """A shard's name is taken by an object that is not that shard."""


def normalize_mode(value: Optional[str]) -> Optional[str]:
    """The delivery mode a setting or annotation names, or None if it names none."""
    if value is None:
        return None
    value = str(value).strip().lower()
    return value if value in MODES else None


@dataclass(frozen=True)
class Shard:
    """One definitions document, kept in one ConfigMap and mounted as one file."""

    index: int
    name: str
    document: str
    components: int

    @property
    def size(self) -> int:
        return len(self.document.encode())

    @property
    def volume_name(self) -> str:
        return f"{VOLUME_PREFIX}{self.index}"

    @property
    def file_name(self) -> str:
        return f"{VOLUME_PREFIX}{self.index}.yaml"


def shard_name(component_name: str, document: str) -> str:
    """The name of the ConfigMap holding a document: the app's name and the document's digest."""
    digest = hashlib.sha256(document.encode()).hexdigest()[:10]
    return f"{component_name}-definitions-{digest}"


def _size(component) -> int:
    return len(component.yaml_str.encode())


def plan_shards(components: Mapping[str, Sequence], budget: int) -> List[Dict[str, List]]:
    """Group components, by kind, into the contents of each shard.

    The first shard holds every table, join, task and agent, then webviews by name
    while it stays within the budget; the remaining webviews fill further shards.
    """
    core = {
        kind: sorted(components.get(kind) or (), key=lambda c: c.cluster)
        for kind in CORE_KINDS
    }
    webviews = sorted(components.get("webviews") or (), key=lambda c: c.cluster)
    shards: List[Dict[str, List]] = [{kind: items for kind, items in core.items() if items}]
    size = sum(_size(c) for items in core.values() for c in items)
    for webview in webviews:
        webview_size = _size(webview)
        if shards[-1] and size + webview_size > budget:
            shards.append({})
            size = 0
        shards[-1].setdefault("webviews", []).append(webview)
        size += webview_size
    return [shard for shard in shards if shard]


def build_shards(
    component_name: str, components: Mapping[str, Sequence], budget: int
) -> List[Shard]:
    """Render an app's components into shards.

    Raises:
        DefinitionsTooLarge: a shard exceeds the hard limit.
        kopf.PermanentError: a document does not read back as the data dumped into it.
    """
    shards = []
    for index, contents in enumerate(plan_shards(components, budget)):
        specs = {kind: [c.spec for c in contents[kind]] for kind in KINDS if kind in contents}
        data = ordered_dict_to_dict(
            KasprAppComponentsSchema().dump(KasprAppComponents(**specs))
        )
        document = yaml.dump(data, default_flow_style=False)
        count = sum(len(items) for items in specs.values())
        size = len(document.encode())
        if size > HARD_LIMIT_BYTES:
            raise DefinitionsTooLarge(
                f"Definitions shard {index} holds {count} components in {size} bytes, more "
                f"than the {HARD_LIMIT_BYTES} bytes a shard may hold."
            )
        if yaml.load(document, Loader=_SafeLoader) != data:
            raise kopf.PermanentError(
                f"Definitions shard {index} does not read back as the components written into it."
            )
        shards.append(Shard(index, shard_name(component_name, document), document, count))
    return shards


def prepare_shard_config_map(
    shard: Shard, namespace: str, labels: Mapping[str, str]
) -> V1ConfigMap:
    """The immutable ConfigMap holding a shard."""
    return V1ConfigMap(
        api_version="v1",
        kind="ConfigMap",
        metadata=V1ObjectMeta(
            name=shard.name,
            namespace=namespace,
            labels={**labels, SHARD_LABEL: SHARD_LABEL_VALUE},
            annotations={
                SHARD_INDEX_ANNOTATION: str(shard.index),
                SHARD_COMPONENTS_ANNOTATION: str(shard.components),
            },
        ),
        data={SHARD_KEY: shard.document},
        immutable=True,
    )


def prepare_shard_volumes(shards: Iterable[Shard]) -> List[V1Volume]:
    return [
        V1Volume(
            name=shard.volume_name,
            config_map=V1ConfigMapVolumeSource(
                name=shard.name,
                items=[V1KeyToPath(key=SHARD_KEY, path=SHARD_KEY)],
            ),
        )
        for shard in shards
    ]


def prepare_shard_volume_mounts(shards: Iterable[Shard], definitions_dir: str) -> List[V1VolumeMount]:
    return [
        V1VolumeMount(
            name=shard.volume_name,
            mount_path=f"{definitions_dir}/{shard.file_name}",
            read_only=True,
            sub_path=SHARD_KEY,
        )
        for shard in shards
    ]


def deployed_mode(stateful_set: V1StatefulSet) -> str:
    """The delivery mode a StatefulSet's pod template uses."""
    volumes = stateful_set.spec.template.spec.volumes or []
    if any((volume.name or "").startswith(VOLUME_PREFIX) for volume in volumes):
        return BUNDLE
    return COMPONENTS


def _container_signature(container) -> Dict:
    return {
        "name": container.name,
        "image": container.image,
        "hashes": sorted(
            (env.name, env.value)
            for env in (container.env or [])
            if env.name.endswith("_HASH") and env.value is not None
        ),
        "mounts": sorted(
            f"{mount.name}:{mount.mount_path}" for mount in (container.volume_mounts or [])
        ),
    }


def template_signature(stateful_set: V1StatefulSet) -> Dict:
    """Pod template fields the operator renders verbatim and the API server never rewrites."""
    spec = stateful_set.spec.template.spec
    return {
        "serviceAccountName": spec.service_account_name,
        "volumes": sorted(volume.name for volume in (spec.volumes or [])),
        "containers": [_container_signature(c) for c in (spec.containers or [])],
        "initContainers": [_container_signature(c) for c in (spec.init_containers or [])],
    }


def template_change_pending(actual: V1StatefulSet, desired: V1StatefulSet) -> bool:
    """Whether applying ``desired`` would change the pod template of ``actual`` anyway.

    Only fields that never differ for any other reason are compared, so a True answer
    always means a rollout; changes elsewhere in the template are not seen.
    """
    return template_signature(actual) != template_signature(desired)


@dataclass(frozen=True)
class Delivery:
    """The delivery mode a reconciliation renders, and why."""

    mode: str
    # The mode of the live pod template; None when there is no StatefulSet yet.
    deployed: Optional[str]
    # "annotation", "default" or "deployed" (kept until the next rollout).
    reason: str
    # The annotation's value, when it names no mode.
    invalid_annotation: Optional[str] = None

    @property
    def changes(self) -> bool:
        return self.deployed is not None and self.deployed != self.mode


def resolve_delivery(
    annotations: Optional[Mapping[str, str]],
    default: str,
    stateful_set: Optional[V1StatefulSet],
    render: Callable[[str], V1StatefulSet],
) -> Delivery:
    """Choose the delivery mode of an app.

    The annotation applies at once. Without it, an app keeps the mode it runs until
    its pod template changes anyway, and then takes the default.

    Args:
        render: Renders the app's StatefulSet in the given mode.
    """
    value = (annotations or {}).get(DELIVERY_ANNOTATION)
    mode = normalize_mode(value)
    invalid = value if value is not None and mode is None else None
    deployed = deployed_mode(stateful_set) if stateful_set is not None else None
    if mode is not None:
        return Delivery(mode, deployed, "annotation")
    if deployed is None or deployed == default:
        return Delivery(default, deployed, "default", invalid)
    try:
        pending = template_change_pending(stateful_set, render(deployed))
    except DefinitionsTooLarge:
        # The definitions outgrew the bundle the pods run: they change anyway.
        pending = True
    if pending:
        return Delivery(default, deployed, "default", invalid)
    return Delivery(deployed, deployed, "deployed", invalid)


def app_delivers_bundles(app: Optional[Mapping]) -> bool:
    """Whether an app, as read from the API, delivers its components in bundles.

    Its annotation decides; without one, the mode its last reconciliation deployed.
    """
    if not app:
        return False
    annotations = (app.get("metadata") or {}).get("annotations") or {}
    mode = normalize_mode(annotations.get(DELIVERY_ANNOTATION))
    if mode is not None:
        return mode == BUNDLE
    definitions = (app.get("status") or {}).get("definitions") or {}
    return definitions.get("delivery") == BUNDLE


def is_shard(config_map: V1ConfigMap, app_name: str) -> bool:
    labels = config_map.metadata.labels or {}
    return labels.get(APP_LABEL) == app_name and labels.get(SHARD_LABEL) == SHARD_LABEL_VALUE


def is_component_config_map(config_map: V1ConfigMap, app_name: str) -> bool:
    """Whether a ConfigMap is one the operator wrote for one of the app's components."""
    metadata = config_map.metadata
    if (metadata.labels or {}).get(APP_LABEL) != app_name:
        return False
    for ref in metadata.owner_references or []:
        suffix = COMPONENT_CONFIG_MAP_SUFFIXES.get(ref.kind)
        if suffix and ref.api_version == COMPONENT_API_VERSION and metadata.name == f"{ref.name}{suffix}":
            return True
    return False


def mounted_config_maps(pod_spec) -> Set[str]:
    """Names of the ConfigMaps a pod spec mounts."""
    names = set()
    for volume in (pod_spec.volumes if pod_spec else None) or []:
        if volume.config_map and volume.config_map.name:
            names.add(volume.config_map.name)
        if volume.projected:
            for source in volume.projected.sources or []:
                if source.config_map and source.config_map.name:
                    names.add(source.config_map.name)
    return names


def rollout_complete(stateful_set: V1StatefulSet) -> bool:
    """Whether every pod of a StatefulSet runs its latest template.

    While a rollout runs, the StatefulSet controller recreates a lost old pod from
    the current revision, so that revision's ConfigMaps must stay.
    """
    status = stateful_set.status
    if status is None:
        return False
    generation = stateful_set.metadata.generation
    if generation is not None and (status.observed_generation or 0) < generation:
        return False
    if status.current_revision != status.update_revision:
        return False
    return (status.updated_replicas or 0) == (status.replicas or 0)


@dataclass
class CleanupPlan:
    """Definitions ConfigMaps an app no longer mounts: those to delete, and those to keep for now."""

    delete: List[V1ConfigMap] = field(default_factory=list)
    waiting: List[V1ConfigMap] = field(default_factory=list)
    # Why the waiting ones are kept.
    reason: Optional[str] = None


def cleanup_candidates(
    app_name: str, mode: str, desired: Set[str], config_maps: Iterable[V1ConfigMap]
) -> List[V1ConfigMap]:
    """Definitions ConfigMaps that an app in the given mode does not use.

    In bundle mode: every shard not desired, and every per-component ConfigMap. In
    components mode: every shard. Nothing else is ever a candidate.
    """
    candidates = []
    for config_map in config_maps:
        if config_map.metadata.name in desired:
            continue
        if is_shard(config_map, app_name):
            candidates.append(config_map)
        elif mode == BUNDLE and is_component_config_map(config_map, app_name):
            candidates.append(config_map)
    return candidates


def cleanup_blocker(desired: Set[str], stateful_set: Optional[V1StatefulSet]) -> Optional[str]:
    """Why no unused definitions ConfigMap of an app may be deleted yet, or None.

    Args:
        desired: The definitions ConfigMaps the app's pod template should mount.
    """
    if stateful_set is None:
        return "the StatefulSet does not exist"
    if not desired <= mounted_config_maps(stateful_set.spec.template.spec):
        return "the pod template does not mount the new definitions yet"
    if not rollout_complete(stateful_set):
        return "a rollout is in progress"
    return None


def plan_cleanup(
    candidates: Sequence[V1ConfigMap],
    desired: Set[str],
    stateful_set: Optional[V1StatefulSet],
    pods: Iterable,
) -> CleanupPlan:
    """Decide which candidates can be deleted without any pod losing its definitions.

    Args:
        pods: The app's pods, terminating ones included.
    """
    if not candidates:
        return CleanupPlan()
    blocker = cleanup_blocker(desired, stateful_set)
    if blocker:
        return CleanupPlan(waiting=list(candidates), reason=blocker)
    in_use = set()
    for pod in pods or ():
        in_use |= mounted_config_maps(pod.spec)
    delete = [c for c in candidates if c.metadata.name not in in_use]
    waiting = [c for c in candidates if c.metadata.name in in_use]
    return CleanupPlan(delete, waiting, "a pod still mounts them" if waiting else None)
