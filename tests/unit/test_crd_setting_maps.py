"""The CRDs keep every map a resource declares, and the operator passes its values on as strings.

The API server prunes whatever a structural schema does not describe. A field declared only as
`type: object` - no properties, no `additionalProperties`, no `x-kubernetes-preserve-unknown-fields`
- is therefore always stored empty, whatever a manifest sets: a table's `options` and
`extraTopicConfigs` were, and so were an agent's topic `config` and a webview's response `headers`.
"""

from pathlib import Path

import pytest
import yaml
from marshmallow import ValidationError

from kaspr.types.schemas.component import KasprAppComponentsSchema
from kaspr.types.schemas.kaspragent_spec import KasprAgentInputTopicSchema
from kaspr.types.schemas.kasprtable_spec import KasprTableSpecSchema
from kaspr.types.schemas.kasprwebview_spec import KasprWebViewResponseSpecSchema, KasprWebViewSpecSchema
from kaspr.types.schemas.topicout import TopicOutSpecSchema
from kaspr.utils.helpers import VerbatimKeys, camel_to_snake, ordered_dict_to_dict

CRDS = Path(__file__).resolve().parents[2] / "crds"

#: Objects that are meant to be stored empty.
EMPTY_ON_PURPOSE = {
    # `tls: {}` turns TLS on; the operator reads no field of it.
    ("kasprapp", ".spec.tls"),
}

#: The maps of settings, each kept as written.
SETTING_MAPS = {
    ("kasprtable", ".spec.extraTopicConfigs"),
    ("kasprtable", ".spec.options"),
    ("kaspragent", ".spec.input.topic.config"),
    ("kaspragent", ".spec.output.topics[].config"),
    ("kaspragent", ".spec.processors.operations[].topicSend.config"),
    ("kasprwebview", ".spec.response.headers"),
}


def _crd_nodes():
    """Every node of every CRD's schema, with the CRD's kind and the node's path."""
    for path in sorted(CRDS.glob("*.crd.yaml")):
        kind = path.name.split(".")[0]
        for doc in yaml.safe_load_all(path.read_text()):
            if not doc or doc.get("kind") != "CustomResourceDefinition":
                continue
            for version in doc["spec"]["versions"]:
                stack = [(version["schema"]["openAPIV3Schema"], "")]
                while stack:
                    node, at = stack.pop()
                    if not isinstance(node, dict):
                        continue
                    yield kind, at, node
                    for name, child in (node.get("properties") or {}).items():
                        stack.append((child, f"{at}.{name}"))
                    if isinstance(node.get("items"), dict):
                        stack.append((node["items"], f"{at}[]"))
                    if isinstance(node.get("additionalProperties"), dict):
                        stack.append((node["additionalProperties"], f"{at}{{}}"))


def _stored_empty(node) -> bool:
    return (
        node.get("type") == "object"
        and "properties" not in node
        and "additionalProperties" not in node
        and not node.get("x-kubernetes-preserve-unknown-fields")
    )


def test_no_crd_declares_an_object_the_api_server_would_store_empty():
    emptied = {(kind, at) for kind, at, node in _crd_nodes() if _stored_empty(node)}
    assert emptied == EMPTY_ON_PURPOSE


def test_every_map_of_settings_is_kept_as_written():
    kept = {(kind, at) for kind, at, node in _crd_nodes() if node.get("x-kubernetes-preserve-unknown-fields")}
    assert SETTING_MAPS <= kept


def test_a_tables_options_and_topic_configs_reach_the_app_as_strings():
    table = KasprTableSpecSchema().load(
        {
            "name": "state",
            "extraTopicConfigs": {"retention.ms": 86400000, "cleanup.policy": "compact", "min.cleanable.dirty.ratio": 0.5},
            "options": {"write_buffer_size": 4194304, "set_cache_index_and_filter_blocks": True},
        }
    )
    assert table.extra_topic_configs == {"retention.ms": "86400000", "cleanup.policy": "compact", "min.cleanable.dirty.ratio": "0.5"}
    assert table.options == {"write_buffer_size": "4194304", "set_cache_index_and_filter_blocks": "true"}
    # What the operator writes for the app to read (`KasprAppComponent.prepare_yaml_str`).
    components = KasprAppComponentsSchema().dump({"agents": [], "webviews": [], "tables": [table], "tasks": [], "joins": []})
    written = yaml.safe_load(yaml.dump(ordered_dict_to_dict(components), default_flow_style=False))
    assert written["tables"][0]["options"] == {"write_buffer_size": "4194304", "set_cache_index_and_filter_blocks": "true"}
    assert written["tables"][0]["extra_topic_configs"]["retention.ms"] == "86400000"


def test_a_table_without_settings_has_none():
    table = KasprTableSpecSchema().load({"name": "state"})
    assert (table.extra_topic_configs, table.options) == ({}, {})


def test_topic_configs_and_headers_reach_the_app_as_strings():
    assert KasprAgentInputTopicSchema().load({"name": "orders", "config": {"retention.ms": -1}}).config == {"retention.ms": "-1"}
    assert TopicOutSpecSchema().load({"name": "out", "config": {"preallocate": False}}).config == {"preallocate": "false"}
    headers = KasprWebViewResponseSpecSchema().load({"headers": {"Cache-Control": "no-store", "X-Retry-After": 5}}).headers
    assert headers == {"Cache-Control": "no-store", "X-Retry-After": "5"}


def test_header_names_reach_the_app_as_written():
    view = KasprWebViewSpecSchema().load(
        {
            "name": "maps",
            "request": {"method": "GET", "path": "/maps"},
            "response": {"statusCode": 200, "headers": {"Cache-Control": "no-store", "X-Retry-After": 5}},
            "processors": {"pipeline": ["noop"], "operations": [{"name": "noop", "map": {"entrypoint": "noop", "python": "def noop(v):\n    return v"}}]},
        }
    )
    components = KasprAppComponentsSchema().dump({"agents": [], "webviews": [view], "tables": [], "tasks": [], "joins": []})
    written = yaml.safe_load(yaml.dump(ordered_dict_to_dict(components), default_flow_style=False))
    response = written["webviews"][0]["response"]
    # The operator's own keys are converted, the headers' names are not.
    assert response["status_code"] == 200
    assert response["headers"] == {"Cache-Control": "no-store", "X-Retry-After": "5"}


def test_camel_to_snake_leaves_verbatim_names_alone():
    data = {"statusCode": 200, "nested": {"bodySelector": 1}, "headers": VerbatimKeys({"Cache-Control": "no-store"})}
    assert camel_to_snake(data) == {"status_code": 200, "nested": {"body_selector": 1}, "headers": {"Cache-Control": "no-store"}}


@pytest.mark.parametrize("value", [{"nested": 1}, [1, 2], None])
def test_a_setting_that_is_not_a_scalar_is_refused(value):
    with pytest.raises(ValidationError):
        KasprTableSpecSchema().load({"name": "state", "options": {"write_buffer_size": value}})
