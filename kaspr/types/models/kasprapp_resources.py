class KasprAppResources:
    """Encapsulates the naming scheme used for the resources which the Kaspr Operator manages 
    for a KasprApp cluster."""

    @classmethod
    def component_name(self, cluster_name: str):
        """Returns the name of the KasprApp deployment for a cluster of the given name."""
        return f"{cluster_name}-app"

    @classmethod
    def service_account_name(self, cluster_name: str):
        """Returns the name of the KasrpApp `ServiceAccount` for a cluster of the given name."""
        return self.component_name(cluster_name)

    @classmethod
    def service_name(self, cluster_name: str):
        """Returns the name of the HTTP service for a cluster of the given name."""
        return f"{cluster_name}-app-api"

    @classmethod
    def qualified_service_name(self, cluster_name: str, namespace: str):
        """Returns qualified name of the service which works across different namespaces."""
        return f"{self.service_name(cluster_name)}.{namespace}.svc"

    @classmethod
    def url(self, cluster_name: str, namespace: str, port: int):
        """Returns the URL of the KasprApp API for a KasprApp cluster of the given name."""
        return f"http://{self.qualified_service_name(cluster_name, namespace)}:{port}"

    @classmethod
    def settings_config_name(self, cluster_name: str):
        return f"{cluster_name}-app-config"
    
    @classmethod
    def settings_secret_name(self, cluster_name: str):
        return f"{cluster_name}-app-secret"
    
    @classmethod
    def persistent_volume_claim_name(self, cluster_name: str):
        return f"{cluster_name}-app-pv"
    
    @classmethod
    def stateful_set_name(self, cluster_name: str):
        return self.component_name(cluster_name)
    
    @classmethod
    def hpa_name(self, cluster_name: str):
        return f"{cluster_name}-app-hpa"