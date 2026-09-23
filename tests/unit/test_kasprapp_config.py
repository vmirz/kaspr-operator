from kaspr.types.schemas.config import KasprAppConfigSchema


def test_broker_settings_render_as_environment_variables():
    config = KasprAppConfigSchema().load(
        {
            "brokerRequestTimeout": 181,
            "brokerCommitEvery": 10_001,
            "brokerCommitInterval": 3,
            "brokerHeartbeatInterval": 4,
            "brokerSessionTimeout": 121,
            "brokerRebalanceTimeout": 61,
            "brokerMaxPollRecords": 101,
            "brokerMaxPollInterval": 1_001,
        }
    )

    assert config.as_envs() == {
        "K_BROKER_REQUEST_TIMEOUT": "181",
        "K_BROKER_COMMIT_EVERY": "10001",
        "K_BROKER_COMMIT_INTERVAL": "3",
        "K_BROKER_HEARTBEAT_INTERVAL": "4",
        "K_BROKER_SESSION_TIMEOUT": "121",
        "K_BROKER_REBALANCE_TIMEOUT": "61",
        "K_BROKER_MAX_POLL_RECORDS": "101",
        "K_BROKER_MAX_POLL_INTERVAL": "1001",
    }