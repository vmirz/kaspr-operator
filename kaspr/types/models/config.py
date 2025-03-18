from typing import Any, Mapping, Sequence
from kaspr.types.base import BaseModel


class KasprAppConfig(BaseModel):
    """kaspr app configurations."""

    table_dir: str

    # topics
    topic_prefix: str
    topic_replication_factor: int
    topic_partitions: int
    topic_allow_declare: bool

    # kafka message scheduler
    scheduler_enabled: bool
    scheduler_debug_stats_enabled: bool
    scheduler_topic_partitions: int
    scheduler_checkpoint_save_interval_seconds: float
    scheduler_dispatcher_default_checkpoint_lookback_days: int
    scheduler_dispatcher_checkpoint_interval: float
    scheduler_janitor_checkpoint_interval: float
    scheduler_janitor_clean_interval_seconds: float
    scheduler_janitor_highwater_offset_seconds: float

    # rocksdb
    store_rocksdb_write_buffer_size: int
    store_rocksdb_max_write_buffer_number: int
    store_rocksdb_target_file_size_base: int
    store_rocksdb_block_cache_size: int
    store_rocksdb_block_cache_compressed_size: int
    store_rocksdb_bloom_filter_size: int
    store_rocksdb_set_cache_index_and_filter_blocks: bool

    # web
    web_base_path: str
    web_port: int
    web_metrics_base_path: str

    def env_for(self, config_name: str) -> str:
        """Return the environment variable equivalent name for configuration name."""
        return f"K_{config_name.upper()}"

    def as_envs(self, exclude_none=True):
        return {
            self.env_for(k): str(v)
            for k, v in vars(self).items()
            if exclude_none and v is not None
        }
