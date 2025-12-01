from marshmallow import fields, post_dump
from kaspr.types.base import BaseSchema
from kaspr.types.models.config import KasprAppConfig
from kaspr.utils.helpers import camel_to_snake


class KasprAppConfigSchema(BaseSchema):
    """kaspr app configurations."""

    __model__ = KasprAppConfig

    table_dir: str = fields.Str(data_key="tableDir", dump_default=None)

    # topics
    topic_replication_factor: int = fields.Int(data_key="topicReplicationFactor", dump_default=None)
    topic_partitions: int = fields.Int(data_key="topicPartitions", dump_default=None)
    topic_allow_declare: bool = fields.Bool(data_key="topicAllowDeclare", dump_default=None)

    # kafka message scheduler
    scheduler_enabled: bool = fields.Bool(data_key="schedulerEnabled", dump_default=None)
    scheduler_debug_stats_enabled: bool = fields.Bool(data_key="schedulerDebugStatsEnabled", dump_default=None)
    scheduler_topic_partitions: int = fields.Int(data_key="schedulerTopicPartitions", dump_default=None)
    scheduler_checkpoint_save_interval_seconds: float = fields.Float(data_key="schedulerCheckpointSaveIntervalSeconds", dump_default=None)
    scheduler_dispatcher_default_checkpoint_lookback_days: int = fields.Int(data_key="schedulerDispatcherDefaultCheckpointLookbackDays", dump_default=None)
    scheduler_dispatcher_checkpoint_interval: float = fields.Float(data_key="schedulerDispatcherCheckpointInterval", dump_default=None)
    scheduler_janitor_checkpoint_interval: float = fields.Float(data_key="schedulerJanitorCheckpointInterval", dump_default=None)
    scheduler_janitor_clean_interval_seconds: float = fields.Float(data_key="schedulerJanitorCleanIntervalSeconds", dump_default=None)
    scheduler_janitor_highwater_offset_seconds: float = fields.Float(data_key="schedulerJanitorHighwaterOffsetSeconds", dump_default=None)

    # rocksdb
    store_rocksdb_write_buffer_size: int = fields.Int(data_key="storeRocksdbWriteBufferSize", dump_default=None)
    store_rocksdb_max_write_buffer_number: int = fields.Int(data_key="storeRocksdbMaxWriteBufferNumber", dump_default=None)
    store_rocksdb_target_file_size_base: int = fields.Int(data_key="storeRocksdbTargetFileSizeBase", dump_default=None)
    store_rocksdb_block_cache_size: int = fields.Int(data_key="storeRocksdbBlockCacheSize", dump_default=None)
    store_rocksdb_block_cache_compressed_size: int = fields.Int(data_key="storeRocksdbBlockCacheCompressedSize", dump_default=None)
    store_rocksdb_bloom_filter_size: int = fields.Int(data_key="storeRocksdbBloomFilterSize", dump_default=None)
    store_rocksdb_set_cache_index_and_filter_blocks: bool = fields.Bool(data_key="storeRocksdbSetCacheIndexAndFilterBlocks", dump_default=None)

    # web
    web_base_path: str = fields.Str(data_key="webBasePath", dump_default=None)
    web_port: int = fields.Int(data_key="webPort", dump_default=None)
    web_metrics_base_path: str = fields.Str(data_key="webMetricsBasePath", dump_default=None)

    @post_dump
    def camel_to_snake_dump(self, data, **kwargs):
        """Convert data keys from camelCase to snake_case."""
        return camel_to_snake(data)