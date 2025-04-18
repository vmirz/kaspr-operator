from typing import Dict
from kaspr.types.models import KasprWebViewSpec, KasprWebViewResources
from kaspr.utils.objects import cached_property
from kaspr.resources.appcomponent import BaseAppComponent
from kaspr.types.models import KasprAppComponents


class KasprWebView(BaseAppComponent):
    """Kaspr WebView kubernetes resource."""

    KIND = "KasprWebView"
    COMPONENT_TYPE = "webview"
    PLURAL_NAME = "kasprwebviews"
    kaspr_resource = KasprWebViewResources

    spec: KasprWebViewSpec

    @classmethod
    def from_spec(
        cls,
        name: str,
        kind: str,
        namespace: str,
        spec: KasprWebViewSpec,
        labels: Dict[str, str] = None,
    ) -> "KasprWebView":
        agent = KasprWebView(name, kind, namespace, cls.KIND, labels)
        agent.spec = spec
        agent.spec.name = name
        agent.config_map_name = cls.kaspr_resource.config_name(name)
        agent.volume_mount_name = cls.kaspr_resource.volume_mount_name(name)
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

    @cached_property
    def app_components(self) -> KasprAppComponents:
        """Return the app components."""
        return KasprAppComponents(webviews=[self.spec])
