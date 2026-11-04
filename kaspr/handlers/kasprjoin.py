"""Handling of KasprJoins.

A join is handled like the other components, except that it has no ConfigMap of its
own: it reaches its app's pods only in the app's definitions bundle, where it is built
after the tables it joins and before the agents reading its channel.
"""

import kopf
from kaspr.types.schemas import KasprJoinSpecSchema
from kaspr.types.models import KasprJoinSpec
from kaspr.resources import KasprJoin, KasprTable
from kaspr.resources.definitions import APP_LABEL, DELIVERY_ANNOTATION
from kaspr.resources.kasprjoin import (
    NOT_DELIVERED,
    LEFT_TABLE_FOUND,
    RIGHT_TABLE_FOUND,
)
from kaspr.handlers.appcomponent import reconcile_component
from kaspr.handlers.kasprapp import notify_component_event

KIND = "KasprJoin"
NOT_DELIVERED_REASON = "NotDelivered"


@kopf.on.resume(kind=KIND)
@kopf.on.create(kind=KIND)
@kopf.on.update(kind=KIND)
async def reconciliation(
    body, spec, name, namespace, logger, labels, patch, meta=None, status=None, reason=None, **kwargs
):
    """Reconcile KasprJoin resources."""
    spec_model: KasprJoinSpec = KasprJoinSpecSchema().load(spec)
    join = KasprJoin.from_spec(name, KIND, namespace, spec_model, dict(labels))
    bundled = await reconcile_component(
        join,
        body=body,
        status=status,
        patch=patch,
        namespace=namespace,
        generation=(meta or {}).get("generation", 0),
        reason=reason,
        logger=logger,
    )
    current = status or {}
    if not bundled and current.get("delivery") != NOT_DELIVERED:
        kopf.warn(
            body,
            reason=NOT_DELIVERED_REASON,
            message=(
                f"Not delivered to the pods of KasprApp `{join.app_name}`: KasprJoins need "
                f"definitions bundle delivery (annotate the KasprApp "
                f"`{DELIVERY_ANNOTATION}: bundle`)."
            ),
        )

    # A join's tables must belong to its app.
    app_tables = set()
    for table_name in {spec_model.left_table, spec_model.right_table}:
        table = await KasprTable.default().fetch(table_name, namespace)
        table_labels = ((table or {}).get("metadata") or {}).get("labels") or {}
        if table and table_labels.get(APP_LABEL) == join.app_name:
            app_tables.add(table_name)
    location = f"`{namespace or 'default'}` namespace"
    for field, desired in join.tables_status(app_tables).items():
        if current.get(field) == desired:
            continue
        patch.status[field] = desired
        found = desired["status"] in (LEFT_TABLE_FOUND, RIGHT_TABLE_FOUND)
        message = (
            f"KasprTable `{desired['name']}` of KasprApp `{join.app_name}` "
            f"{'found' if found else 'not found'} in {location}."
        )
        if found:
            kopf.event(body, type="Normal", reason=desired["status"], message=message)
        else:
            kopf.warn(body, reason=desired["status"], message=message)


@kopf.on.event(kind=KIND)
async def notify_app(event, body, logger, **kwargs):
    """Reconcile the join's KasprApp when the join is added, changed or deleted."""
    await notify_component_event(event.get("type"), body, logger)
