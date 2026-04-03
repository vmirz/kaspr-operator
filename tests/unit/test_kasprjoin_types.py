"""Unit tests for KasprJoin types (model + schema)."""

import pytest
from marshmallow import ValidationError
from kaspr.types.models.kasprjoin_spec import KasprJoinSpec
from kaspr.types.models.kasprjoin_resources import KasprJoinResources
from kaspr.types.schemas.kasprjoin_spec import KasprJoinSpecSchema
from kaspr.types.schemas.component import KasprAppComponentsSchema


class TestKasprJoinSpecSchema:
    """Tests for KasprJoinSpecSchema load/dump."""

    def setup_method(self):
        self.schema = KasprJoinSpecSchema()
        self.valid_input = {
            "description": "Join orders with products by product_id",
            "leftTable": "orders",
            "rightTable": "products",
            "extractor": {
                "entrypoint": "get_product_id",
                "python": "def get_product_id(value):\n    return value.get('product_id')",
            },
            "type": "inner",
            "outputChannel": "orders-products-joined",
        }

    def test_load_valid_input(self):
        result = self.schema.load(self.valid_input)
        assert isinstance(result, KasprJoinSpec)
        assert result.name is None  # name is derived from metadata.name, not spec
        assert result.description == "Join orders with products by product_id"
        assert result.left_table == "orders"
        assert result.right_table == "products"
        assert result.extractor.entrypoint == "get_product_id"
        assert result.extractor.python.startswith("def get_product_id")
        assert result.join_type == "inner"
        assert result.output_channel == "orders-products-joined"

    def test_load_minimal_input(self):
        minimal = {
            "leftTable": "left",
            "rightTable": "right",
            "extractor": {
                "python": "def extract(v): return v.get('id')",
            },
        }
        result = self.schema.load(minimal)
        assert isinstance(result, KasprJoinSpec)
        assert result.name is None  # name is derived from metadata.name
        assert result.left_table == "left"
        assert result.right_table == "right"
        assert result.description is None
        assert result.join_type == "inner"
        assert result.output_channel is None

    def test_join_type_defaults_to_inner(self):
        data = {
            "leftTable": "a",
            "rightTable": "b",
            "extractor": {"python": "def f(v): return v"},
        }
        result = self.schema.load(data)
        assert result.join_type == "inner"

    def test_output_channel_defaults_to_none(self):
        data = {
            "leftTable": "a",
            "rightTable": "b",
            "extractor": {"python": "def f(v): return v"},
        }
        result = self.schema.load(data)
        assert result.output_channel is None

    def test_load_missing_left_table_raises(self):
        data = {
            "rightTable": "b",
            "extractor": {"python": "def f(v): return v"},
        }
        with pytest.raises(ValidationError) as exc_info:
            self.schema.load(data)
        assert "leftTable" in exc_info.value.messages

    def test_load_missing_right_table_raises(self):
        data = {
            "leftTable": "a",
            "extractor": {"python": "def f(v): return v"},
        }
        with pytest.raises(ValidationError) as exc_info:
            self.schema.load(data)
        assert "rightTable" in exc_info.value.messages

    def test_load_missing_extractor_raises(self):
        data = {
            "leftTable": "a",
            "rightTable": "b",
        }
        with pytest.raises(ValidationError) as exc_info:
            self.schema.load(data)
        assert "extractor" in exc_info.value.messages

    def test_dump_converts_to_camel_case(self):
        model = KasprJoinSpec(
            name="test-join",
            description=None,
            left_table="a",
            right_table="b",
            extractor={"python": "def f(v): return v", "entrypoint": "f"},
            join_type="inner",
            output_channel="test-channel",
        )
        result = self.schema.dump(model)
        # Schema uses data_key mappings: leftTable -> left_table, rightTable -> right_table
        # "type" stays as "type" (no camelCase conversion needed)
        # "outputChannel" -> output_channel
        assert "left_table" in result
        assert "right_table" in result
        assert "type" in result
        assert "output_channel" in result

    def test_load_left_join_type(self):
        data = {
            "leftTable": "a",
            "rightTable": "b",
            "extractor": {"python": "def f(v): return v"},
            "type": "left",
        }
        result = self.schema.load(data)
        assert result.join_type == "left"


class TestKasprJoinResources:
    """Tests for KasprJoinResources naming scheme."""

    def test_component_name(self):
        assert KasprJoinResources.component_name("my-app") == "my-app-join"

    def test_config_name(self):
        assert KasprJoinResources.config_name("my-app") == "my-app-join"

    def test_volume_mount_name(self):
        assert KasprJoinResources.volume_mount_name("my-app") == "my-app-join"

    def test_service_account_name_raises(self):
        with pytest.raises(NotImplementedError):
            KasprJoinResources.service_account_name("my-app")

    def test_service_name_raises(self):
        with pytest.raises(NotImplementedError):
            KasprJoinResources.service_name("my-app")

    def test_qualified_service_name_raises(self):
        with pytest.raises(NotImplementedError):
            KasprJoinResources.qualified_service_name("my-app", "default")

    def test_url_raises(self):
        with pytest.raises(NotImplementedError):
            KasprJoinResources.url("my-app", "default", 8080)

    def test_settings_secret_name_raises(self):
        with pytest.raises(NotImplementedError):
            KasprJoinResources.settings_secret_name("my-app")


class TestKasprAppComponentsWithJoins:
    """Tests for KasprAppComponents with joins field."""

    def test_components_schema_includes_joins(self):
        schema = KasprAppComponentsSchema()
        data = {
            "agents": [],
            "webviews": [],
            "tables": [],
            "tasks": [],
            "joins": [
                {
                    "leftTable": "a",
                    "rightTable": "b",
                    "extractor": {"python": "def f(v): return v"},
                }
            ],
        }
        result = schema.load(data)
        assert hasattr(result, "joins")
        assert len(result.joins) == 1
        assert isinstance(result.joins[0], KasprJoinSpec)
        assert result.joins[0].left_table == "a"

    def test_components_schema_joins_defaults_to_empty(self):
        schema = KasprAppComponentsSchema()
        data = {
            "agents": [],
            "webviews": [],
            "tables": [],
            "tasks": [],
        }
        result = schema.load(data)
        assert result.joins == []

    def test_components_schema_multiple_joins(self):
        schema = KasprAppComponentsSchema()
        data = {
            "joins": [
                {
                    "leftTable": "a",
                    "rightTable": "b",
                    "extractor": {"python": "def f(v): return v.get('id')"},
                },
                {
                    "leftTable": "a",
                    "rightTable": "c",
                    "extractor": {"python": "def g(v): return v.get('key')"},
                    "type": "left",
                    "outputChannel": "custom-channel",
                },
            ],
        }
        result = schema.load(data)
        assert len(result.joins) == 2
        assert result.joins[0].left_table == "a"
        assert result.joins[0].right_table == "b"
        assert result.joins[0].join_type == "inner"
        assert result.joins[1].left_table == "a"
        assert result.joins[1].right_table == "c"
        assert result.joins[1].join_type == "left"
        assert result.joins[1].output_channel == "custom-channel"
