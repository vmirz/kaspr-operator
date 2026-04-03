class KasprJoinResources:
    """Encapsulates the naming scheme used for the resources which the Kaspr Operator manages
    for KasprJoin resources."""

    @classmethod
    def component_name(cls, cluster_name: str):
        return f"{cluster_name}-join"

    @classmethod
    def config_name(cls, cluster_name: str):
        return f"{cluster_name}-join"

    @classmethod
    def volume_mount_name(cls, cluster_name: str):
        return f"{cluster_name}-join"

    @classmethod
    def service_account_name(cls, cluster_name: str):
        raise NotImplementedError()

    @classmethod
    def service_name(cls, cluster_name: str):
        raise NotImplementedError()

    @classmethod
    def qualified_service_name(cls, cluster_name: str, namespace: str):
        raise NotImplementedError()

    @classmethod
    def url(cls, cluster_name: str, namespace: str, port: int):
        raise NotImplementedError()

    @classmethod
    def settings_secret_name(cls, cluster_name: str):
        raise NotImplementedError()
