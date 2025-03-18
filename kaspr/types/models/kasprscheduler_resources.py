class KasprSchedulerResources:
    """Encapsulates the naming scheme used for the resources which
    the Kaspr Operator manages for a KasprScheduler cluster."""

    @classmethod
    def component_name(self, cluster_name: str):
        """Returns the name of the KMS deployment for a KMS cluster of the given name."""
        return f"{cluster_name}-kms"

    @classmethod
    def service_account_name(self, cluster_name: str):
        """Returns the name of the KMS `ServiceAccount` for a KMS cluster of the given name."""
        return self.component_name(cluster_name)

    @classmethod
    def service_name(self, cluster_name: str):
        """Returns the name of the HTTP service for a KMS cluster of the given name."""
        return f"{cluster_name}-kms-api"

    @classmethod
    def qualified_service_name(self, cluster_name: str, namespace: str):
        """Returns qualified name of the service which works across different namespaces."""
        return f"{self.service_name(cluster_name)}.{namespace}.svc"

    @classmethod
    def url(self, cluster_name: str, namespace: str, port: int):
        """Returns the URL of the KMS API for a KMS cluster of the given name."""
        return f"http://{self.qualified_service_name(cluster_name, namespace)}:{port}"

    @classmethod
    def settings_config_name(self, cluster_name: str):
        return f"{cluster_name}-kms-config"
    
    @classmethod
    def settings_secret_name(self, cluster_name: str):
        return f"{cluster_name}-kms-secret"
    
    @classmethod
    def persistent_volume_claim_name(self, cluster_name: str):
        return f"{cluster_name}-kms-pv"
    
    @classmethod
    def stateful_set_name(self, cluster_name: str):
        return self.component_name(cluster_name)