from marshmallow import fields, post_dump
from kaspr.types.base import BaseSchema
from kaspr.types.models.config import KasprAppConfig
from kaspr.utils.helpers import camel_to_snake


class KasprAppConfigSchema(BaseSchema):
    """kaspr app configurations."""

    __model__ = KasprAppConfig

    table_dir: str = fields.Str(data_key="tableDir", default=None)

    # topics
    topic_replication_factor: int = fields.Int(data_key="topicReplicationFactor", default=None)
    topic_partitions: int = fields.Int(data_key="topicPartitions", default=None)
    topic_allow_declare: bool = fields.Bool(data_key="topicAllowDeclare", default=None)

    # kafka message scheduler
    scheduler_enabled: bool = fields.Bool(data_key="schedulerEnabled", default=None)
    scheduler_debug_stats_enabled: bool = fields.Bool(data_key="schedulerDebugStatsEnabled", default=None)
    scheduler_topic_partitions: int = fields.Int(data_key="schedulerTopicPartitions", default=None)
    scheduler_checkpoint_save_interval_seconds: float = fields.Float(data_key="schedulerCheckpointSaveIntervalSeconds", default=None)
    scheduler_dispatcher_default_checkpoint_lookback_days: int = fields.Int(data_key="schedulerDispatcherDefaultCheckpointLookbackDays", default=None)
    scheduler_dispatcher_checkpoint_interval: float = fields.Float(data_key="schedulerDispatcherCheckpointInterval", default=None)
    scheduler_janitor_checkpoint_interval: float = fields.Float(data_key="schedulerJanitorCheckpointInterval", default=None)
    scheduler_janitor_clean_interval_seconds: float = fields.Float(data_key="schedulerJanitorCleanIntervalSeconds", default=None)
    scheduler_janitor_highwater_offset_seconds: float = fields.Float(data_key="schedulerJanitorHighwaterOffsetSeconds", default=None)

    # rocksdb
    store_rocksdb_write_buffer_size: int = fields.Int(data_key="storeRocksdbWriteBufferSize", default=None)
    store_rocksdb_max_write_buffer_number: int = fields.Int(data_key="storeRocksdbMaxWriteBufferNumber", default=None)
    store_rocksdb_target_file_size_base: int = fields.Int(data_key="storeRocksdbTargetFileSizeBase", default=None)
    store_rocksdb_block_cache_size: int = fields.Int(data_key="storeRocksdbBlockCacheSize", default=None)
    store_rocksdb_block_cache_compressed_size: int = fields.Int(data_key="storeRocksdbBlockCacheCompressedSize", default=None)
    store_rocksdb_bloom_filter_size: int = fields.Int(data_key="storeRocksdbBloomFilterSize", default=None)
    store_rocksdb_set_cache_index_and_filter_blocks: bool = fields.Bool(data_key="storeRocksdbSetCacheIndexAndFilterBlocks", default=None)

    # web
    web_base_path: str = fields.Str(data_key="webBasePath", default=None)
    web_port: int = fields.Int(data_key="webPort", default=None)
    web_metrics_base_path: str = fields.Str(data_key="webMetricsBasePath", default=None)

    @post_dump
    def camel_to_snake_dump(self, data, **kwargs):
        """Convert data keys from camelCase to snake_case."""
        return camel_to_snake(data)