from typing import Dict
from kaspr.types.models import KasprWebViewSpec, KasprWebViewResources
from kaspr.resources.appcomponent import BaseAppComponent


class KasprWebView(BaseAppComponent):
    """Kaspr WebView kubernetes resource."""

    KIND = "KasprWebView"
    COMPONENT_TYPE = "webview"
    PLURAL_NAME = "kasprwebviews"
    spec: KasprWebViewSpec

    @classmethod
    def from_spec(
        self,
        name: str,
        kind: str,
        namespace: str,
        spec: KasprWebViewSpec,
        labels: Dict[str, str] = None,
    ) -> "KasprWebView":
        agent = KasprWebView(name, kind, namespace, self.KIND, labels)
        agent.spec = spec
        agent.spec.name = name
        agent.config_map_name = KasprWebViewResources.config_name(name)
        agent.volume_mount_name = KasprWebViewResources.volume_mount_name(name)
        return agent

    @classmethod
    def default(self) -> "KasprWebView":
        """Create a default KasprWebView resource."""
        return KasprWebView(
            name="default",
            kind=self.KIND,
            namespace=None,
            component_type=self.COMPONENT_TYPE,
        )
