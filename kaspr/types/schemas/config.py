from marshmallow import fields
from kaspr.types.base import BaseSchema
from kaspr.types.models.config import KasprAppConfig


class KasprAppConfigSchema(BaseSchema):
    """kaspr app configurations."""

    __model__ = KasprAppConfig

    # kafka_boostrap_servers: str
    # kafka_security_protocol: str
    # kafka_sasl_mechanism: str
    # kafka_auth_username: str
    # kafka_auth_password: str
    # kafka_auth_cafile: str
    # kafka_auth_capath: str
    # kafka_auth_cadata: str

    table_dir: str = fields.Str(default=None)

    # topics
    topic_prefix: str = fields.Str(default=None)
    topic_replication_factor: int = fields.Int(default=None)
    topic_partitions: int = fields.Int(default=None)
    topic_allow_declare: bool = fields.Bool(default=None)

    # kafka message scheduler
    kms_enabled: bool = fields.Bool(default=None)
    kms_debug_stats_enabled: bool = fields.Bool(default=None)
    kms_topic_partitions: int = fields.Int(default=None)
    kms_checkpoint_save_interval_seconds: float = fields.Float(default=None)
    kms_dispatcher_default_checkpoint_lookback_days: int = fields.Int(default=None)
    kms_dispatcher_checkpoint_interval: float = fields.Float(default=None)
    kms_janitor_checkpoint_interval: float = fields.Float(default=None)
    kms_janitor_clean_interval_seconds: float = fields.Float(default=None)
    kms_janitor_highwater_offset_seconds: float = fields.Float(default=None)

    # rocksdb
    store_rocksdb_write_buffer_size: int = fields.Int(default=None)
    store_rocksdb_max_write_buffer_number: int = fields.Int(default=None)
    store_rocksdb_target_file_size_base: int = fields.Int(default=None)
    store_rocksdb_block_cache_size: int = fields.Int(default=None)
    store_rocksdb_block_cache_compressed_size: int = fields.Int(default=None)
    store_rocksdb_bloom_filter_size: int = fields.Int(default=None)
    store_rocksdb_set_cache_index_and_filter_blocks: bool = fields.Bool(default=None)

    # web
    web_base_path: str = fields.Str(default=None)
    web_port: int = fields.Int(default=None)
    web_metrics_base_path: str = fields.Str(default=None)
