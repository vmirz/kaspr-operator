"""Renderings of KasprApps whose components are delivered as one ConfigMap each.

An app that does not use definitions bundles must render exactly as it did before
bundles existed: the same StatefulSet and the same component ConfigMaps, byte for
byte, or upgrading the operator would roll it. The goldens in
``fixtures/legacy_rendering`` were rendered by the release before bundles, from the
apps in ``examples/`` plus one app holding every example component.

Regenerate them only with that release's code, from a checkout of it:

    PYTHONPATH=<checkout of the release> python tests/unit/legacy_rendering.py

This module only uses what that release has, so it runs against both.
"""

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES_DIR = ROOT / "examples"
GOLDEN_DIR = Path(__file__).resolve().parent / "fixtures" / "legacy_rendering"
NAMESPACE = "legacy-rendering"
IMAGE = "kasprio/kaspr:0.11.31"
COMBINED_APP = "every-component"

COMPONENT_KINDS = ("KasprAgent", "KasprWebView", "KasprTable", "KasprTask", "KasprJoin")


def _documents(path: Path):
    with path.open() as fh:
        return [doc for doc in yaml.safe_load_all(fh) if doc]


def load_cases():
    """(case name, KasprApp, components) for every example app, and the combined app."""
    cases = []
    combined = []
    for directory in sorted(p for p in EXAMPLES_DIR.iterdir() if p.is_dir()):
        docs = [doc for path in sorted(directory.rglob("*.yaml")) for doc in _documents(path)]
        apps = [d for d in docs if d.get("kind") == "KasprApp"]
        components = [d for d in docs if d.get("kind") in COMPONENT_KINDS]
        combined.extend(components)
        for app in apps:
            name = app["metadata"]["name"]
            own = [
                c for c in components
                if (c["metadata"].get("labels") or {}).get("kaspr.io/app") == name
            ]
            cases.append((f"{directory.name}__{name}", app, own))
    every = {
        "apiVersion": "kaspr.io/v1alpha1",
        "kind": "KasprApp",
        "metadata": {"name": COMBINED_APP, "annotations": {}},
        "spec": {
            "replicas": 3,
            "bootstrapServers": "kafka:9092",
            "authentication": {
                "type": "plain",
                "username": "user",
                "passwordSecret": {"secretName": "kafka-credentials", "passwordKey": "password"},
            },
            "storage": {"type": "persistent-claim", "class": "standard", "size": "1Gi"},
        },
    }
    # The examples have no task.
    combined.append(
        {
            "apiVersion": "kaspr.io/v1alpha1",
            "kind": "KasprTask",
            "metadata": {"name": "heartbeat"},
            "spec": {
                "name": "heartbeat",
                "description": "Sends a heartbeat every minute",
                "onLeader": True,
                "schedule": {"interval": "60s"},
                "processors": {
                    "pipeline": ["beat"],
                    "operations": [
                        {
                            "name": "beat",
                            "map": {
                                "entrypoint": "beat",
                                "python": "def beat():\n    return {'alive': True}\n",
                            },
                        }
                    ],
                },
            },
        }
    )
    renamed = []
    for component in combined:
        component = json.loads(json.dumps(component))
        metadata = component["metadata"]
        metadata["name"] = f'{metadata["name"]}-{component["kind"].lower()}'
        metadata.setdefault("labels", {})["kaspr.io/app"] = COMBINED_APP
        renamed.append(component)
    cases.append((COMBINED_APP, every, renamed))
    return cases


class _operator_settings:
    """Give KasprApp the operator's default settings while rendering, and take them back after."""

    def __enter__(self):
        from kaspr.resources.kasprapp import KasprApp
        from kaspr.types.settings import Settings

        self.had, self.previous = "conf" in vars(KasprApp), vars(KasprApp).get("conf")
        KasprApp.conf = Settings()

    def __exit__(self, *exc):
        from kaspr.resources.kasprapp import KasprApp

        if self.had:
            KasprApp.conf = self.previous
        else:
            del KasprApp.conf


def build_app(app_doc, components):
    """The KasprApp of a case with its components attached, as a reconciliation builds it."""
    from kaspr.resources import KasprAgent, KasprWebView, KasprTable, KasprTask
    from kaspr.resources.kasprapp import KasprApp
    from kaspr.types.schemas import (
        KasprAgentSpecSchema,
        KasprWebViewSpecSchema,
        KasprTableSpecSchema,
        KasprTaskSpecSchema,
    )
    from kaspr.types.schemas.kasprapp_spec import KasprAppSpecSchema

    spec_doc = dict(app_doc.get("spec") or {})
    # Some examples show only what they are about; fill in what the schema requires.
    spec_doc.setdefault("bootstrapServers", "kafka:9092")
    spec_doc.setdefault(
        "authentication",
        {
            "type": "plain",
            "username": "user",
            "passwordSecret": {"secretName": "kafka-credentials", "passwordKey": "password"},
        },
    )
    storage = dict(spec_doc.get("storage") or {})
    storage.setdefault("type", "persistent-claim")
    storage.setdefault("class", "standard")
    storage.setdefault("size", "1Gi")
    spec_doc["storage"] = storage
    spec_doc["image"] = IMAGE
    spec_doc.pop("version", None)
    name = app_doc["metadata"]["name"]
    app = KasprApp.from_spec(
        name,
        "KasprApp",
        NAMESPACE,
        KasprAppSpecSchema().load(spec_doc),
        dict(app_doc["metadata"].get("annotations") or {}),
    )

    def build(resource_cls, schema_cls, kind):
        return [
            resource_cls.from_spec(
                c["metadata"]["name"],
                kind,
                NAMESPACE,
                schema_cls().load(c["spec"]),
                dict(c["metadata"].get("labels") or {}),
            )
            for c in sorted(components, key=lambda c: c["metadata"]["name"])
            if c["kind"] == kind
        ]

    app.with_agents(build(KasprAgent, KasprAgentSpecSchema, "KasprAgent"))
    app.with_webviews(build(KasprWebView, KasprWebViewSpecSchema, "KasprWebView"))
    app.with_tables(build(KasprTable, KasprTableSpecSchema, "KasprTable"))
    app.with_tasks(build(KasprTask, KasprTaskSpecSchema, "KasprTask"))
    if hasattr(app, "with_joins"):
        from kaspr.resources import KasprJoin
        from kaspr.types.schemas import KasprJoinSpecSchema

        app.with_joins(build(KasprJoin, KasprJoinSpecSchema, "KasprJoin"))
    return app


def serialize(objects):
    """Kubernetes models as the API client sends them."""
    import asyncio
    from kubernetes_asyncio.client.api_client import ApiClient

    async def run():
        async with ApiClient() as client:
            return client.sanitize_for_serialization(objects)

    return asyncio.run(run())


def render(app_doc, components):
    """What the operator writes for a case: its StatefulSet and component ConfigMaps."""
    with _operator_settings():
        app = build_app(app_doc, components)
        stateful_set = app.stateful_set
        config_maps = [
            component.config_map
            for component in [*app.agents, *app.webviews, *app.tables, *app.tasks]
        ]
    return {
        "statefulSet": serialize(stateful_set),
        "configMaps": sorted(serialize(config_maps), key=lambda cm: cm["metadata"]["name"]),
    }


def main():
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    for case, app_doc, components in load_cases():
        path = GOLDEN_DIR / f"{case}.json"
        path.write_text(json.dumps(render(app_doc, components), indent=1, sort_keys=True) + "\n")
        print(f"wrote {path.relative_to(ROOT)}", file=sys.stderr)


if __name__ == "__main__":
    main()
