"""Components and StatefulSets for the definitions bundle tests."""

import copy

import yaml
from kubernetes_asyncio.client import (
    V1ConfigMap,
    V1ConfigMapVolumeSource,
    V1ObjectMeta,
    V1OwnerReference,
    V1Pod,
    V1PodSpec,
    V1StatefulSetStatus,
    V1Volume,
)

from kaspr.resources import KasprWebView
from kaspr.types.schemas import KasprWebViewSpecSchema
from legacy_rendering import COMBINED_APP, NAMESPACE, _operator_settings, build_app, load_cases

APP = COMBINED_APP


def every_component_case():
    """The KasprApp holding every example component, and those components."""
    case, app_doc, components = next(c for c in load_cases() if c[0] == COMBINED_APP)
    return app_doc, components


def webview_doc(name: str, code_bytes: int = 200):
    return {
        "apiVersion": "kaspr.io/v1alpha1",
        "kind": "KasprWebView",
        "metadata": {"name": name, "labels": {"kaspr.io/app": APP}},
        "spec": {
            "name": name,
            "request": {"method": "GET", "path": f"/{name}"},
            "processors": {
                "pipeline": ["answer"],
                "operations": [
                    {
                        "name": "answer",
                        "map": {
                            "entrypoint": "answer",
                            "python": "def answer(request):\n    return "
                            + repr("x" * code_bytes)
                            + "\n",
                        },
                    }
                ],
            },
        },
    }


def webview(name: str, code_bytes: int = 200) -> KasprWebView:
    doc = webview_doc(name, code_bytes)
    return KasprWebView.from_spec(
        name,
        "KasprWebView",
        NAMESPACE,
        KasprWebViewSpecSchema().load(doc["spec"]),
        dict(doc["metadata"]["labels"]),
    )


def app_with(components=None, annotations=None, extra=()):
    """The combined example app, optionally with other components and annotations."""
    app_doc, docs = every_component_case()
    app_doc = copy.deepcopy(app_doc)
    if annotations:
        app_doc["metadata"]["annotations"] = dict(annotations)
    return build_app(app_doc, list(components if components is not None else docs) + list(extra))


def per_component_items(app):
    """Each component's spec as its own ConfigMap holds it, by kind."""
    items = {}
    for component in [*app.agents, *app.webviews, *app.tables, *app.tasks, *(app.joins or [])]:
        for kind, specs in yaml.safe_load(component.yaml_str).items():
            items.setdefault(kind, []).extend(specs)
    return items


def config_map(name, labels=None, owner_kind=None, owner_name=None, uid=None):
    owners = None
    if owner_kind:
        owners = [
            V1OwnerReference(
                api_version="kaspr.io/v1alpha1", kind=owner_kind, name=owner_name, uid=f"uid-{owner_name}"
            )
        ]
    return V1ConfigMap(
        metadata=V1ObjectMeta(name=name, labels=labels or {}, owner_references=owners, uid=uid or f"uid-{name}")
    )


def shard_config_map(name, app=APP):
    return config_map(name, labels={"kaspr.io/app": app, "kaspr.io/component": "definitions"})


def component_config_map(owner_name, kind="KasprWebView", suffix="-webview", app=APP):
    return config_map(
        f"{owner_name}{suffix}", labels={"kaspr.io/app": app}, owner_kind=kind, owner_name=owner_name
    )


def with_status(stateful_set, generation=2, observed=2, current="rev-2", update="rev-2", replicas=1, updated=1):
    stateful_set = copy.deepcopy(stateful_set)
    stateful_set.metadata.generation = generation
    stateful_set.status = V1StatefulSetStatus(
        observed_generation=observed,
        current_revision=current,
        update_revision=update,
        replicas=replicas,
        updated_replicas=updated,
    )
    return stateful_set


def pod_mounting(*config_maps):
    return V1Pod(
        spec=V1PodSpec(
            containers=[],
            volumes=[
                V1Volume(name=f"v{i}", config_map=V1ConfigMapVolumeSource(name=name))
                for i, name in enumerate(config_maps)
            ],
        )
    )


__all__ = [
    "APP",
    "NAMESPACE",
    "_operator_settings",
    "app_with",
    "component_config_map",
    "config_map",
    "every_component_case",
    "per_component_items",
    "pod_mounting",
    "shard_config_map",
    "webview",
    "webview_doc",
    "with_status",
]
