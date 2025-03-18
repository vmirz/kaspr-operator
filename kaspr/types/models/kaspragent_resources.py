class KasprAgentResources:
    """Encapsulates the naming scheme used for the resources which the Kaspr Operator manages 
    for KasprAgent resources."""

    @classmethod
    def component_name(self, cluster_name: str):
        return f"{cluster_name}-agent"

    @classmethod
    def service_account_name(self, cluster_name: str):
        raise NotImplementedError()

    @classmethod
    def service_name(self, cluster_name: str):
        raise NotImplementedError()

    @classmethod
    def qualified_service_name(self, cluster_name: str, namespace: str):
        raise NotImplementedError()

    @classmethod
    def url(self, cluster_name: str, namespace: str, port: int):
        raise NotImplementedError()

    @classmethod
    def config_name(self, cluster_name: str):
        return f"{cluster_name}-agent"
    
    @classmethod
    def settings_secret_name(self, cluster_name: str):
        raise NotImplementedError()
    
    @classmethod
    def volume_mount_name(self, cluster_name: str):
         return f"{cluster_name}-agent"
