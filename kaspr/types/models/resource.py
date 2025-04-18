class KasprResourceT:

    @classmethod
    def component_name(self, cluster_name: str):
        ...

    @classmethod
    def service_account_name(self, cluster_name: str):
        ...

    @classmethod
    def service_name(self, cluster_name: str):
        ...

    @classmethod
    def qualified_service_name(self, cluster_name: str, namespace: str):
        ...

    @classmethod
    def url(self, cluster_name: str, namespace: str, port: int):
        ...

    @classmethod
    def config_name(self, cluster_name: str):
        ...
    
    @classmethod
    def settings_secret_name(self, cluster_name: str):
        ...
    
    @classmethod
    def volume_mount_name(self, cluster_name: str):
        ...
