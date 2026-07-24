"""Unit tests for TopicOutSpec schema pass-through support."""

import sys
import types
from pathlib import Path


package_root = Path(__file__).resolve().parents[2] / "kaspr"
if "kaspr" not in sys.modules:
    package = types.ModuleType("kaspr")
    package.__path__ = [str(package_root)]
    sys.modules["kaspr"] = package
if "jsonpickle" not in sys.modules:
    sys.modules["jsonpickle"] = types.ModuleType("jsonpickle")

from kaspr.types.schemas.kasprtask_spec import KasprTaskProcessorTopicSendOperatorSchema
from kaspr.types.schemas.kaspragent_spec import (
    KasprAgentProcessorTopicSendOperatorSchema,
    KasprAgentSpecSchema,
)
from kaspr.types.schemas.kasprwebview_spec import (
    KasprWebViewProcessorTopicSendOperatorSchema,
)
from kaspr.types.schemas.topicout import TopicOutSpecSchema


def test_topicout_schema_loads_pass_through_from_crd_field():
    schema = TopicOutSpecSchema()

    result = schema.load({"name": "materialization-requests", "passThrough": True})

    assert result.name == "materialization-requests"
    assert result.pass_through is True


def test_topicout_schema_loads_declare_and_topic_options_from_crd_fields():
    schema = TopicOutSpecSchema()

    result = schema.load(
        {
            "name": "materialization-requests",
            "declare": True,
            "partitions": 12,
            "retention": 3600,
            "compacting": True,
            "deleting": False,
            "replicas": 3,
            "config": {"cleanup.policy": "compact"},
        }
    )

    assert result.declare is True
    assert result.partitions == 12
    assert result.retention == 3600
    assert result.compacting is True
    assert result.deleting is False
    assert result.replicas == 3
    assert result.config == {"cleanup.policy": "compact"}


def test_webview_topic_send_schema_dumps_pass_through_for_runtime_config():
    schema = KasprWebViewProcessorTopicSendOperatorSchema()
    model = schema.load({"name": "materialization-requests", "passThrough": True})

    result = schema.dump(model)

    assert result["name"] == "materialization-requests"
    assert result["pass_through"] is True


def test_agent_topic_send_schema_dumps_pass_through_for_runtime_config():
    schema = KasprAgentProcessorTopicSendOperatorSchema()
    model = schema.load({"name": "materialization-requests", "passThrough": True})

    result = schema.dump(model)

    assert result["name"] == "materialization-requests"
    assert result["pass_through"] is True


def test_task_topic_send_schema_defaults_pass_through_false():
    schema = KasprTaskProcessorTopicSendOperatorSchema()

    result = schema.load({"name": "materialization-requests"})

    assert result.pass_through is False


def test_agent_spec_schema_accepts_processor_topic_send_operation():
    schema = KasprAgentSpecSchema()

    result = schema.load(
        {
            "name": "schema-proposal-agent",
            "input": {"topic": {"name": "input-topic"}},
            "processors": {
                "pipeline": ["publish-proposal"],
                "operations": [
                    {
                        "name": "publish-proposal",
                        "topicSend": {
                            "name": "schema-proposals",
                            "passThrough": True,
                            "valueSelector": {
                                "python": "def select_value(value):\n    return value['schema_proposal']",
                                "entrypoint": "select_value",
                            },
                        },
                    }
                ],
            },
        }
    )

    assert result.processors.operations[0].topic_send.name == "schema-proposals"
    assert result.processors.operations[0].topic_send.pass_through is True


def test_agent_spec_schema_accepts_output_topic_declaration_options():
    schema = KasprAgentSpecSchema()

    result = schema.load(
        {
            "name": "schema-proposal-agent",
            "input": {"topic": {"name": "input-topic"}},
            "output": {
                "topics": [
                    {
                        "name": "schema-proposals",
                        "declare": True,
                        "partitions": 12,
                        "retention": 3600,
                        "compacting": True,
                        "deleting": False,
                        "replicas": 3,
                        "config": {"cleanup.policy": "compact"},
                    }
                ]
            },
            "processors": {
                "pipeline": ["publish-proposal"],
                "operations": [
                    {
                        "name": "publish-proposal",
                        "map": {
                            "python": "def passthrough(value):\n    return value",
                            "entrypoint": "passthrough",
                        },
                    }
                ],
            },
        }
    )

    topic = result.output.topics[0]
    assert topic.name == "schema-proposals"
    assert topic.declare is True
    assert topic.partitions == 12
    assert topic.retention == 3600
    assert topic.compacting is True
    assert topic.deleting is False
    assert topic.replicas == 3
    assert topic.config == {"cleanup.policy": "compact"}