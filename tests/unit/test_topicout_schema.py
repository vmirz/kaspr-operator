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
from kaspr.types.schemas.kasprwebview_spec import (
    KasprWebViewProcessorTopicSendOperatorSchema,
)
from kaspr.types.schemas.topicout import TopicOutSpecSchema


def test_topicout_schema_loads_pass_through_from_crd_field():
    schema = TopicOutSpecSchema()

    result = schema.load({"name": "materialization-requests", "passThrough": True})

    assert result.name == "materialization-requests"
    assert result.pass_through is True


def test_webview_topic_send_schema_dumps_pass_through_for_runtime_config():
    schema = KasprWebViewProcessorTopicSendOperatorSchema()
    model = schema.load({"name": "materialization-requests", "passThrough": True})

    result = schema.dump(model)

    assert result["name"] == "materialization-requests"
    assert result["pass_through"] is True


def test_task_topic_send_schema_defaults_pass_through_false():
    schema = KasprTaskProcessorTopicSendOperatorSchema()

    result = schema.load({"name": "materialization-requests"})

    assert result.pass_through is False