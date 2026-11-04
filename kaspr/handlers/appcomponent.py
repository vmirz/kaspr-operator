"""Handling shared by the KasprApp components: agents, webviews, tables and tasks."""

import kopf
import logging
from logging import Logger
from kaspr.resources import KasprApp
from kaspr.resources.appcomponent import BaseAppComponent
from kaspr.handlers.kasprapp import APP_FOUND, APP_NOT_FOUND


class ComponentEventLogFilter(logging.Filter):
    def filter(self, record):
        """The component event handlers run on every component event, so their success is noise."""
        return "Handler 'notify_app' succeeded" not in record.getMessage()


logging.getLogger("kopf.objects").addFilter(ComponentEventLogFilter())


async def reconcile_component(
    component: BaseAppComponent,
    *,
    body,
    status,
    patch,
    namespace: str,
    generation: int,
    reason,
    logger: Logger,
):
    """Sync a component's config map and report whether its KasprApp exists.

    The component's KasprApp is reconciled separately when the component changes
    (see kasprapp.notify_component_event), since it mounts the config map. A
    component of an app that delivers bundles has no config map of its own: the app
    writes it into a bundle. Only status fields that changed are patched.

    Returns whether the component's app delivers bundles.
    """
    sensor = getattr(BaseAppComponent, "sensor", None)
    trigger_source = getattr(reason, "value", reason) or "event"
    sensor_state = None
    if sensor:
        sensor_state = sensor.on_reconcile_start(
            component.app_name, component.cluster, namespace, generation, trigger_source
        )
    success = True
    error = None
    try:
        component.validate()
        apps = KasprApp.default()
        app = await apps.fetch(component.app_name, namespace)
        bundled = await apps.delivers_bundles(app, component.app_name, namespace)
        if component.WRITES_CONFIG_MAP and not bundled:
            await component.synchronize()

        current = status or {}
        desired = {
            "app": {
                "name": component.app_name,
                "status": APP_FOUND if app else APP_NOT_FOUND,
            },
            **component.config_map_status(bundled),
            "hash": component.hash,
        }
        patch.status.update(
            {key: value for key, value in desired.items() if current.get(key) != value}
        )

        location = f"`{namespace or 'default'}` namespace"
        if app is None:
            kopf.warn(
                body,
                reason=APP_NOT_FOUND,
                message=f"KasprApp `{component.app_name}` does not exist in {location}.",
            )
        elif current.get("app") != desired["app"]:
            kopf.event(
                body,
                type="Normal",
                reason=APP_FOUND,
                message=f"KasprApp `{component.app_name}` found in {location}.",
            )
    except Exception as e:
        success = False
        error = e
        raise
    finally:
        if sensor:
            sensor.on_reconcile_complete(
                component.app_name, component.cluster, namespace, sensor_state, success, error
            )
    return bundled
