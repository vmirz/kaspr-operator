# Design Proposal: Join Support via Dedicated `KasprJoin` CRD

> **Status:** Draft  
> **Date:** 2025-04-01  
> **Faust Feature:** `Table.key_join()` (KIP-213 subscription/response protocol)  
> **Faust Version:** ≥ 1.17.10 (branch: `fk-join`)

---

## Table of Contents

1. [Summary](#summary)
2. [Background: Faust Key Join](#background-faust-key-join)
3. [Design Goals](#design-goals)
4. [Proposed CRD Design: `KasprJoin`](#proposed-crd-design-kasprjoin)
5. [CRD Schema (OpenAPI)](#crd-schema-openapi)
6. [End-to-End Example](#end-to-end-example)
7. [Implementation Plan: Kaspr-Operator](#implementation-plan-kaspr-operator)
8. [Implementation Plan: Kaspr (Runtime)](#implementation-plan-kaspr-runtime)
9. [Implementation Plan: Helm & Docs](#implementation-plan-helm--docs)
10. [Alternatives Considered](#alternatives-considered)
11. [Open Questions](#open-questions)

---

## Summary

Faust recently implemented distributed table-to-table key joins via a subscription/response protocol (inspired by Kafka Streams KIP-213). This allows two differently-keyed, differently-partitioned tables to be joined reactively — whenever either side changes, a `JoinedValue(left, right)` is emitted to a channel that can be consumed by an agent.

This proposal defines a **dedicated `KasprJoin` CRD** to expose this capability to end-users. A key join is a first-class concept with its own lifecycle, validation, status, and monitoring — making a standalone resource the most natural and user-friendly approach. Users declare joins entirely in YAML and deploy them to Kubernetes without writing Python code (beyond the small extractor function).

---

## Background: Faust Key Join

### How It Works (Internal Protocol)

```
Left Table Change                              Right Table Change
     │                                              │
     ▼                                              ▼
Extract FK from left value              Prefix-scan subscription store
     │                                    for all subscribers of this key
     ▼                                              │
Send subscription message ──────┐                   │
  (keyed by FK, contains        │                   │
   left_pk + hash of left val)  │                   │
                                ▼                   ▼
              ┌─────────────────────────────────┐
              │  Subscription-Registration Topic │
              │  (co-partitioned with right table)│
              └──────────────┬──────────────────┘
                             │
                             ▼
              Right-side task stores subscription
              in subscription store (FK, left_pk)
              then looks up current right value
                             │
                             ▼
              ┌─────────────────────────────────┐
              │  Subscription-Response Topic     │
              │  (co-partitioned with left table)│
              └──────────────┬──────────────────┘
                             │
                             ▼
              Left-side task receives response,
              validates hash (discard if stale),
              emits JoinedValue(left, right)
              to output channel
```

### Faust Python API

```python
# Two tables with different keys
orders_table = app.Table('orders', ...)       # keyed by order_id
products_table = app.Table('products', ...)   # keyed by product_id

# Join orders → products by extracting product_id from order values
joined_channel = orders_table.key_join(
    products_table,
    extractor=lambda order: order.get('product_id'),
    inner=True,  # skip if right side is None
)

# Consume joined results
@app.agent(joined_channel)
async def process_joined(joined_values):
    async for joined in joined_values:
        order = joined.left      # the order record
        product = joined.right   # the matching product record
```

### Key Properties

- **No co-partitioning required** — left and right tables can have different keys, different partition counts.
- **Reactive** — changes on either side trigger re-emission of join results.
- **Internal topics are auto-created** — `{app}-{left}-{right}-subscription-registration` and `{app}-{left}-{right}-subscription-response`.
- **Internal stores are auto-created** — subscription store + previous-FK tracker.
- **Hash-based staleness detection** — prevents stale responses after rapid left-side updates.
- **Supports inner join** (`inner=True`, default) and **left join** (`inner=False`) semantics.

---

## Design Goals

1. **Declarative YAML** — Users define key joins entirely in CRD YAML, no Python beyond the `extractor` function.
2. **First-class resource** — A key join is its own CRD with dedicated lifecycle, status, and validation — easy to reason about, create, delete, and monitor independently.
3. **Consistent with existing patterns** — Follow the same CRD conventions as `KasprAgent`, `KasprTable`, `KasprTask` (handler/resource/model/schema architecture).
4. **Table references** — Joins reference existing `KasprTable` resources by name, validated by the operator.
5. **Agent-as-consumer** — The joined channel is consumed by a `KasprAgent` via `input.channel`.

---

## Proposed CRD Design: `KasprJoin`

A `KasprJoin` resource declares a reactive join between two `KasprTable` resources within the same `KasprApp`. It produces a named output channel that `KasprAgent` resources can consume.

### Resource Definition

```yaml
apiVersion: kaspr.io/v1alpha1
kind: KasprJoin
metadata:
  name: orders-products-join
  namespace: demo
  labels:
    kaspr.io/app: order-system
spec:
  name: orders-products-join
  description: "Join orders with products by product_id"

  # The left-side table (the "driving" side of the join)
  leftTable: orders

  # The right-side table (the "lookup" side of the join)
  rightTable: products

  # Python function to extract the join key from left-table values.
  # The returned value is used to look up the corresponding record
  # in the right table.
  extractor:
    entrypoint: get_product_id
    python: |
      def get_product_id(value):
          return value.get("product_id")

  # Join semantics: "inner" (default) or "left"
  #   inner: skip emission when right side is None
  #   left: emit with right=None when no match exists
  type: inner

  # Name of the output channel for joined results.
  # KasprAgents reference this via input.channel.name.
  # Defaults to "{name}-channel" if not specified.
  outputChannel: orders-products-joined
```

### Status Subresource

```yaml
status:
  app:
    name: order-system
    status: AppFound        # or AppNotFound
  leftTable:
    name: orders
    status: TableFound      # or TableNotFound
  rightTable:
    name: products
    status: TableFound      # or TableNotFound
  configMap: orders-products-join
  hash: "abc123..."
```

### Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Dedicated CRD** | A join is a first-class data flow concept — it has its own inputs (two tables), logic (extractor), semantics (inner/left), output (channel), and lifecycle. Users can `kubectl get kasprjoin` to see all joins, inspect their status, and manage them independently. |
| **Both `leftTable` and `rightTable` are explicit** | Unlike embedding on KasprTable where left is implicit, declaring both sides makes the resource self-describing. A user reading the YAML instantly understands the full join topology. |
| **`extractor` uses the standard `CodeSpec` pattern** | Reuses the existing `entrypoint` + `python` pattern from agents, tasks, and operations. No new code execution patterns needed. |
| **`outputChannel` is optional with a sensible default** | Reduces boilerplate for simple cases while allowing override for explicit naming. Default: `{name}-channel`. |
| **`type` field for join semantics** | Maps directly to Faust's `inner` parameter. `"inner"` (default) = skip when right is None; `"left"` = emit with right=None. |

---

## CRD Schema (OpenAPI)

File: `crds/kasprjoin.crd.yaml`

```yaml
apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
metadata:
  name: kasprjoins.kaspr.io
spec:
  scope: Namespaced
  group: kaspr.io
  names:
    kind: KasprJoin
    plural: kasprjoins
    singular: kasprjoin
    shortNames:
      - kjoin
      - kj
  versions:
    - name: v1alpha1
      served: true
      storage: true
      schema:
        openAPIV3Schema:
          type: object
          properties:
            spec:
              type: object
              x-kubernetes-preserve-unknown-fields: true
              properties:
                name:
                  type: string
                  description: The name of the key join.
                description:
                  type: string
                  description: A short description of what this key join does.
                leftTable:
                  type: string
                  description: >
                    Name of the left-side KasprTable resource.
                    This is the "driving" table whose changes trigger FK extraction.
                    Must belong to the same KasprApp (same kaspr.io/app label).
                rightTable:
                  type: string
                  description: >
                    Name of the right-side KasprTable resource (the "lookup" table).
                    Must belong to the same KasprApp (same kaspr.io/app label).
                extractor:
                  type: object
                  description: >
                    Python function that extracts the join key from left-table values.
                    The returned value is used to look up the corresponding record
                    in the right table.
                  properties:
                    entrypoint:
                      type: string
                      description: Name of the function to run.
                    python:
                      type: string
                      description: Python code defining the extractor function.
                  required:
                    - python
                type:
                  type: string
                  description: >
                    Join semantics. "inner" skips emission when right side is None.
                    "left" emits JoinedValue with right=None when no match exists.
                  enum: ["inner", "left"]
                  default: "inner"
                outputChannel:
                  type: string
                  description: >
                    Name of the output channel for joined results.
                    KasprAgents reference this via input.channel.name.
                    Defaults to "{name}-channel" if not specified.
              required:
                - name
                - leftTable
                - rightTable
                - extractor
            status:
              type: object
              x-kubernetes-preserve-unknown-fields: true
```

---

## End-to-End Example

### Scenario: Order Enrichment with Product Data

Four CRD types deployed together — `KasprApp`, `KasprTable` × 2, `KasprJoin`, `KasprAgent` × 3.

#### 1. KasprApp

```yaml
apiVersion: kaspr.io/v1alpha1
kind: KasprApp
metadata:
  name: order-system
  namespace: demo
spec:
  replicas: 3
  bootstrapServers: kafka-bootstrap:9092
  config:
    topicPartitions: 6
    topicReplicationFactor: 3
  storage:
    size: 5Gi
```

#### 2. Products Table

```yaml
apiVersion: kaspr.io/v1alpha1
kind: KasprTable
metadata:
  name: products
  namespace: demo
  labels:
    kaspr.io/app: order-system
spec:
  name: products
  description: "Product catalog keyed by product_id"
  partitions: 6
```

#### 3. Orders Table

```yaml
apiVersion: kaspr.io/v1alpha1
kind: KasprTable
metadata:
  name: orders
  namespace: demo
  labels:
    kaspr.io/app: order-system
spec:
  name: orders
  description: "Orders keyed by order_id"
  partitions: 6
```

#### 4. Key Join (dedicated resource)

```yaml
apiVersion: kaspr.io/v1alpha1
kind: KasprJoin
metadata:
  name: orders-products-join
  namespace: demo
  labels:
    kaspr.io/app: order-system
spec:
  name: orders-products-join
  description: "Join orders with products by product_id"
  leftTable: orders
  rightTable: products
  extractor:
    entrypoint: get_product_id
    python: |
      def get_product_id(order):
          return order.get("product_id")
  type: inner
  outputChannel: orders-products-joined
```

#### 5. Agents — Ingest + Process Joined Stream

```yaml
# Agent that ingests raw orders into the orders table
apiVersion: kaspr.io/v1alpha1
kind: KasprAgent
metadata:
  name: ingest-orders
  namespace: demo
  labels:
    kaspr.io/app: order-system
spec:
  input:
    topic:
      name: raw-orders
  processors:
    pipeline:
      - store-order
    init:
      python: |
        app = context["app"]
    operations:
      - name: store-order
        tables:
          - name: orders
            paramName: orders_table
        map:
          entrypoint: store
          python: |
            def store(value, orders_table):
                order_id = value.get("order_id")
                orders_table[order_id] = value
                return value
---
# Agent that ingests products into the products table
apiVersion: kaspr.io/v1alpha1
kind: KasprAgent
metadata:
  name: ingest-products
  namespace: demo
  labels:
    kaspr.io/app: order-system
spec:
  input:
    topic:
      name: raw-products
  processors:
    pipeline:
      - store-product
    init:
      python: |
        app = context["app"]
    operations:
      - name: store-product
        tables:
          - name: products
            paramName: products_table
        map:
          entrypoint: store
          python: |
            def store(value, products_table):
                product_id = value.get("product_id")
                products_table[product_id] = value
                return value
---
# Agent that processes the joined order+product stream
apiVersion: kaspr.io/v1alpha1
kind: KasprAgent
metadata:
  name: process-enriched-orders
  namespace: demo
  labels:
    kaspr.io/app: order-system
spec:
  description: "Processes joined order+product records from key join"
  input:
    channel:
      name: orders-products-joined
  output:
    topics:
      - name: enriched-orders
        keySelector:
          python: |
            def get_key(value):
                return value.get("order_id")
  processors:
    pipeline:
      - enrich
    init:
      python: |
        from datetime import datetime, timezone
    operations:
      - name: enrich
        map:
          entrypoint: enrich_order
          python: |
            def enrich_order(value):
                """
                value is a JoinedValue dict:
                  {"left": <order>, "right": <product>}
                """
                order = value["left"]
                product = value["right"]
                return {
                    "order_id": order.get("order_id"),
                    "product_id": order.get("product_id"),
                    "quantity": order.get("quantity"),
                    "product_name": product.get("name"),
                    "unit_price": product.get("price"),
                    "total": product.get("price", 0) * order.get("quantity", 0),
                    "enriched_at": datetime.now(timezone.utc).isoformat()
                }
```

### What Happens at Runtime

1. **Operator** reconciles the `KasprJoin` resource `orders-products-join`. It:
   - Validates that `leftTable: orders` and `rightTable: products` exist as `KasprTable` resources with the same `kaspr.io/app: order-system` label.
   - Serializes the key join spec into a ConfigMap (`orders-products-join`).
   - Updates status with table validation results and config map reference.
   - Triggers a reconciliation of the parent `KasprApp` so the app picks up the new join.

2. **Kaspr** `AppBuilder` loads all component definitions. When it encounters the key join spec, it:
   - Resolves `leftTable: orders` → the `orders` Faust table instance.
   - Resolves `rightTable: products` → the `products` Faust table instance.
   - Compiles the `extractor` Python code → a callable.
   - Calls `orders_table.key_join(products_table, extractor=..., inner=True)`.
   - Registers the returned channel under the name `orders-products-joined`.

3. **Kaspr** `AppBuilder` loads agent definitions. The `process-enriched-orders` agent has `input.channel.name: orders-products-joined`, which resolves to the key join's output channel.

4. **Faust** `KeyJoinProcessor` starts as a service:
   - Creates internal topics: `order-system-orders-products-subscription-registration`, `order-system-orders-products-subscription-response`.
   - Creates internal stores: `orders-products-subscriptions`, `orders-products-previous-fk`.
   - Registers callbacks on both tables.

5. When an order is ingested → `_on_left_table_change()` fires → subscription message sent → right side responds → `JoinedValue` emitted to channel → `process-enriched-orders` agent processes it.

6. When a product is updated → `_on_right_table_change()` fires → all subscribers notified → updated `JoinedValue` emitted for each affected order.

---

## Implementation Plan: Kaspr-Operator

The operator changes follow the exact same pattern used for `KasprTask` (the most recently added CRD).

### New Files

| File | Purpose |
|------|---------|
| `crds/kasprjoin.crd.yaml` | OpenAPI CRD definition (see [CRD Schema](#crd-schema-openapi) above) |
| `kaspr/types/models/kasprjoin_spec.py` | Spec model (`KasprJoinSpec`) |
| `kaspr/types/models/kasprjoin_resources.py` | Resource naming scheme (`KasprJoinResources`) |
| `kaspr/types/schemas/kasprjoin_spec.py` | Marshmallow schema (`KasprJoinSpecSchema`) |
| `kaspr/resources/kasprjoin.py` | Resource class (`KasprJoin(BaseAppComponent)`) |
| `kaspr/handlers/kasprjoin.py` | Kopf handlers (reconcile, monitor, full sync) |
| `examples/join/basic.yaml` | Example CRD manifests |

### Files to Modify

| File | Change |
|------|--------|
| `kaspr/types/models/component.py` | Add `joins: Optional[List[KasprJoinSpec]]` to `KasprAppComponents` |
| `kaspr/types/schemas/component.py` | Add `joins` field to `KasprAppComponentsSchema` |
| `kaspr/types/models/__init__.py` | Export new model types |
| `kaspr/types/schemas/__init__.py` | Export new schema types |
| `kaspr/resources/__init__.py` | Export `KasprJoin` |

### Model: `kasprjoin_spec.py`

```python
from typing import Optional
from kaspr.types.base import BaseModel
from kaspr.types.models.code import CodeSpec


class KasprJoinSpec(BaseModel):
    """KasprJoin CRD spec"""

    name: str
    description: Optional[str]
    left_table: str
    right_table: str
    extractor: CodeSpec
    join_type: Optional[str]        # "inner" (default) or "left"
    output_channel: Optional[str]   # Named channel for joined output
```

### Resources: `kasprjoin_resources.py`

```python
class KasprJoinResources:
    """Naming scheme for KasprJoin managed resources."""

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
```

### Schema: `kasprjoin_spec.py`

```python
from marshmallow import fields, post_dump
from kaspr.types.base import BaseSchema
from kaspr.types.models.kasprjoin_spec import KasprJoinSpec
from kaspr.types.schemas.code import CodeSpecSchema
from kaspr.utils.helpers import camel_to_snake


class KasprJoinSpecSchema(BaseSchema):
    __model__ = KasprJoinSpec

    name = fields.String(data_key="name", required=True)
    description = fields.String(
        data_key="description", allow_none=True, load_default=None
    )
    left_table = fields.String(data_key="leftTable", required=True)
    right_table = fields.String(data_key="rightTable", required=True)
    extractor = fields.Nested(
        CodeSpecSchema(), data_key="extractor", required=True
    )
    join_type = fields.String(
        data_key="type", allow_none=True, load_default="inner"
    )
    output_channel = fields.String(
        data_key="outputChannel", allow_none=True, load_default=None
    )

    @post_dump
    def camel_to_snake_dump(self, data, **kwargs):
        return camel_to_snake(data)
```

### Resource: `kasprjoin.py`

```python
from typing import Dict
from kaspr.types.models import KasprJoinSpec, KasprJoinResources
from kaspr.utils.objects import cached_property
from kaspr.resources.appcomponent import BaseAppComponent
from kaspr.types.models import KasprAppComponents


class KasprJoin(BaseAppComponent):
    """Kaspr Key Join kubernetes resource."""

    KIND = "KasprJoin"
    COMPONENT_TYPE = "join"
    PLURAL_NAME = "kasprjoins"
    kaspr_resource = KasprJoinResources

    spec: KasprJoinSpec

    @classmethod
    def from_spec(
        cls,
        name: str,
        kind: str,
        namespace: str,
        spec: KasprJoinSpec,
        labels: Dict[str, str] = None,
    ) -> "KasprJoin":
        join_resource = KasprJoin(name, kind, namespace, cls.KIND, labels)
        join_resource.spec = spec
        join_resource.spec.name = name
        join_resource.config_map_name = cls.kaspr_resource.config_name(name)
        join_resource.volume_mount_name = cls.kaspr_resource.volume_mount_name(name)
        return join_resource

    @classmethod
    def default(cls) -> "KasprJoin":
        return KasprJoin(
            name="default",
            kind=cls.KIND,
            namespace=None,
            component_type=cls.COMPONENT_TYPE,
        )

    @cached_property
    def app_components(self) -> KasprAppComponents:
        return KasprAppComponents(joins=[self.spec])
```

### Handler: `kasprjoin.py`

```python
import asyncio
import kopf
import logging
from collections import defaultdict
from typing import Dict
from benedict import benedict
from kaspr.types.schemas import KasprJoinSpecSchema
from kaspr.types.models import KasprJoinSpec
from kaspr.resources import KasprJoin, KasprApp, KasprTable
from kaspr.sensors import SensorDelegate

KIND = "KasprJoin"
APP_NOT_FOUND = "AppNotFound"
APP_FOUND = "AppFound"
LEFT_TABLE_NOT_FOUND = "LeftTableNotFound"
LEFT_TABLE_FOUND = "LeftTableFound"
RIGHT_TABLE_NOT_FOUND = "RightTableNotFound"
RIGHT_TABLE_FOUND = "RightTableFound"

patch_request_queues: Dict[str, asyncio.Queue] = defaultdict(asyncio.Queue)


def get_sensor() -> SensorDelegate:
    return getattr(KasprJoin, 'sensor', None)


class TimerLogFilter(logging.Filter):
    def filter(self, record):
        return "Timer " not in record.getMessage()


kopf_logger = logging.getLogger("kopf.objects")
kopf_logger.addFilter(TimerLogFilter())


@kopf.on.resume(kind=KIND)
@kopf.on.create(kind=KIND)
@kopf.on.update(kind=KIND)
async def reconciliation(
    body, spec, name, namespace, logger, labels, patch, annotations, **kwargs
):
    """Reconcile KasprJoin resources."""
    spec_model: KasprJoinSpec = KasprJoinSpecSchema().load(spec)
    join_resource = KasprJoin.from_spec(name, KIND, namespace, spec_model, dict(labels))
    app = await KasprApp.default().fetch(join_resource.app_name, namespace)
    await join_resource.create()

    # Validate referenced tables exist
    left_table = await KasprTable.default().fetch(spec_model.left_table, namespace)
    right_table = await KasprTable.default().fetch(spec_model.right_table, namespace)

    patch.status.update({
        "app": {
            "name": join_resource.app_name,
            "status": APP_FOUND if app else APP_NOT_FOUND,
        },
        "leftTable": {
            "name": spec_model.left_table,
            "status": LEFT_TABLE_FOUND if left_table else LEFT_TABLE_NOT_FOUND,
        },
        "rightTable": {
            "name": spec_model.right_table,
            "status": RIGHT_TABLE_FOUND if right_table else RIGHT_TABLE_NOT_FOUND,
        },
        "configMap": join_resource.config_map_name,
        "hash": join_resource.hash,
    })

    if app is None:
        kopf.warn(body, reason=APP_NOT_FOUND,
                  message=f"KasprApp `{join_resource.app_name}` not found in `{namespace or 'default'}` namespace.")
    if left_table is None:
        kopf.warn(body, reason=LEFT_TABLE_NOT_FOUND,
                  message=f"KasprTable `{spec_model.left_table}` not found in `{namespace or 'default'}` namespace.")
    if right_table is None:
        kopf.warn(body, reason=RIGHT_TABLE_NOT_FOUND,
                  message=f"KasprTable `{spec_model.right_table}` not found in `{namespace or 'default'}` namespace.")


@kopf.timer(KIND, interval=1)
async def patch_resource(name, patch, **kwargs):
    queue = patch_request_queues[name]
    def set_patch(request):
        fields = request["field"].split(".")
        _patch = patch
        for field in fields:
            _patch = getattr(_patch, field)
        _patch.update(request["value"])
    while not queue.empty():
        request = queue.get_nowait()
        if isinstance(request, list):
            for req in request:
                set_patch(req)
        else:
            set_patch(request)


@kopf.daemon(kind=KIND, cancellation_backoff=2.0, cancellation_timeout=5.0, initial_delay=5.0)
async def monitor_join(
    stopped, name, body, spec, meta, labels, status, namespace, patch, logger, **kwargs
):
    """Monitor KasprJoin resources for table availability."""
    while not stopped:
        try:
            _status = benedict(status, keyattr_dynamic=True)
            _status_updates = benedict(keyattr_dynamic=True)
            spec_model: KasprJoinSpec = KasprJoinSpecSchema().load(spec)
            join_resource = KasprJoin.from_spec(name, KIND, namespace, spec_model, dict(labels))

            # Check app existence
            app = await KasprApp.default().fetch(join_resource.app_name, namespace)
            if app is None and _status.app.status == APP_FOUND:
                kopf.warn(body, reason=APP_NOT_FOUND,
                          message=f"KasprApp `{join_resource.app_name}` not found.")
                _status_updates.app.status = APP_NOT_FOUND
            elif app and _status.app.status == APP_NOT_FOUND:
                kopf.event(body, type="Normal", reason=APP_FOUND,
                           message=f"KasprApp `{join_resource.app_name}` found.")
                _status_updates.app.status = APP_FOUND

            # Check left table existence
            left_table = await KasprTable.default().fetch(spec_model.left_table, namespace)
            if left_table is None and _status.get("leftTable", {}).get("status") == LEFT_TABLE_FOUND:
                kopf.warn(body, reason=LEFT_TABLE_NOT_FOUND,
                          message=f"KasprTable `{spec_model.left_table}` not found.")
                _status_updates.leftTable.status = LEFT_TABLE_NOT_FOUND
            elif left_table and _status.get("leftTable", {}).get("status") == LEFT_TABLE_NOT_FOUND:
                kopf.event(body, type="Normal", reason=LEFT_TABLE_FOUND,
                           message=f"KasprTable `{spec_model.left_table}` found.")
                _status_updates.leftTable.status = LEFT_TABLE_FOUND

            # Check right table existence
            right_table = await KasprTable.default().fetch(spec_model.right_table, namespace)
            if right_table is None and _status.get("rightTable", {}).get("status") == RIGHT_TABLE_FOUND:
                kopf.warn(body, reason=RIGHT_TABLE_NOT_FOUND,
                          message=f"KasprTable `{spec_model.right_table}` not found.")
                _status_updates.rightTable.status = RIGHT_TABLE_NOT_FOUND
            elif right_table and _status.get("rightTable", {}).get("status") == RIGHT_TABLE_NOT_FOUND:
                kopf.event(body, type="Normal", reason=RIGHT_TABLE_FOUND,
                           message=f"KasprTable `{spec_model.right_table}` found.")
                _status_updates.rightTable.status = RIGHT_TABLE_FOUND

            if _status_updates:
                await patch_request_queues[name].put(
                    [{"field": "status", "value": _status_updates}]
                )
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            logger.info("Monitoring stopped.")
            break
        except Exception as e:
            logger.error(f"Unexpected error during monitoring: {e}")
            logger.exception(e)


@kopf.timer(KIND, initial_delay=5.0, interval=60.0, backoff=10.0)
async def reconcile(name, spec, namespace, labels, logger, **kwargs):
    """Full sync."""
    sensor = get_sensor()
    success = True
    error = None
    try:
        spec_model: KasprJoinSpec = KasprJoinSpecSchema().load(spec)
        join_resource = KasprJoin.from_spec(name, KIND, namespace, spec_model, dict(labels))
        sensor_state = sensor.on_reconcile_start(join_resource.app_name, name, namespace, 0, "timer")
        logger.debug(f"Reconciling {KIND}/{name} in {namespace} namespace.")
        await join_resource.synchronize()
        logger.debug(f"Reconciled {KIND}/{name} in {namespace} namespace.")
    except Exception as e:
        success = False
        error = e
        logger.error(f"Unexpected error during reconciliation: {e}")
        logger.exception(e)
    finally:
        sensor.on_reconcile_complete(join_resource.app_name, name, namespace, sensor_state, success, error)
```

### Component Model Change

```python
# kaspr/types/models/component.py
class KasprAppComponents(BaseModel):
    agents: Optional[List[KasprAgentSpec]]
    webviews: Optional[List[KasprWebViewSpec]]
    tables: Optional[List[KasprTableSpec]]
    tasks: Optional[List[KasprTaskSpec]]
    joins: Optional[List[KasprJoinSpec]]  # NEW
```

### Component Schema Change

```python
# kaspr/types/schemas/component.py
class KasprAppComponentsSchema(BaseSchema):
    __model__ = KasprAppComponents

    # ...existing fields...
    joins = fields.List(
        fields.Nested(KasprJoinSpecSchema()),
        data_key="joins",
        required=False,
        load_default=[],
    )
```

---

## Implementation Plan: Kaspr (Runtime)

The kaspr runtime needs to understand key join definitions and wire them up during app build.

### Files to Change

| File | Change |
|------|--------|
| `kaspr/types/models/join/` | New directory with `JoinSpec` model (mirrors operator's model) |
| `kaspr/types/schemas/join/` | New directory with `JoinSpecSchema` (mirrors operator's schema) |
| `kaspr/core/builder.py` | After building tables, iterate key join specs, call `left_table.key_join()`, register output channels |
| `kaspr/core/app.py` | Add `_named_channels: Dict[str, ChannelT]` registry + `register_named_channel()` + `resolve_channel()` |
| `kaspr/types/models/agent/input.py` | Update `prepare_channel()` to resolve named channels from `app._named_channels` |

### New Model: `JoinSpec`

```python
# kaspr/types/models/join/join.py
class JoinSpec(SpecComponent):
    name: str
    left_table: str
    right_table: str
    extractor: PyCode
    join_type: Optional[str]        # "inner" or "left"
    output_channel: Optional[str]

    app: KasprAppT = None
```

### Builder Changes

```python
# kaspr/core/builder.py (conceptual additions to build())
def build(self):
    for app in self.apps:
        app.agents
        app.webviews
        app.tables    # creates all tables first
        app.tasks

        # NEW: After tables are created, wire up key joins
        for join_spec in app.joins_spec:
            self._wire_key_join(join_spec)

def _wire_key_join(self, join_spec):
    left_table = self.app.tables[join_spec.left_table]
    right_table = self.app.tables[join_spec.right_table]
    extractor = join_spec.extractor.func
    inner = (join_spec.join_type or "inner") == "inner"

    channel = left_table.key_join(right_table, extractor=extractor, inner=inner)

    channel_name = join_spec.output_channel or f"{join_spec.name}-channel"
    self.app.register_named_channel(channel_name, channel)
```

---

## Implementation Plan: Helm & Docs

### Helm

1. **New CRD file:** Copy `kasprjoin.crd.yaml` to `kaspr-helm/charts/operator/crds/kasprjoin.crd.yaml`.
2. **Resources template:** Add `charts/resources/templates/join.yaml` for rendering `KasprJoin` from values.
3. **Values example:** Add key join examples to `charts/resources/values.yaml`.

### Documentation

1. **New page:** `pages/docs/user-guide/key-joins.mdx` — Dedicated guide covering:
   - What key joins are and when to use them
   - The subscription/response protocol (conceptual, with diagram)
   - Full YAML walkthrough with order/product example
   - Inner vs left join semantics
   - How `JoinedValue` is structured (`{"left": ..., "right": ...}`)
   - Connecting a `KasprAgent` to the join's output channel
   - Performance considerations (subscription store size, topic partitioning)
2. **Update:** `pages/docs/user-guide/agents.mdx` — Add section on using channel input from key joins.
3. **Update:** `pages/docs/user-guide/concepts.mdx` — Add key joins to concepts overview with architecture diagram.
4. **New API reference entry:** Add `KasprJoin` to `pages/docs/api-reference/v1alpha1.mdx`.

---

## Alternatives Considered

### Alternative A: `keyJoin` Field on `KasprTable`

Embed the join config as a `keyJoin` field on the left-side `KasprTable` CRD:

```yaml
apiVersion: kaspr.io/v1alpha1
kind: KasprTable
metadata:
  name: orders
spec:
  name: orders
  partitions: 6
  keyJoin:
    rightTable: products
    extractor:
      python: |
        def get_key(value):
            return value.get("product_id")
    type: inner
    outputChannel: orders-products-joined
```

**Pros:** Fewer total CRDs; join is co-located with the left table definition; no new handler/resource/model files needed.

**Cons:**
- **Harder to reason about** — users must inspect each table to discover joins; `kubectl get kasprtables` doesn't show which tables have joins.
- **Overloads the table concept** — a table is a storage abstraction; a join is a data flow concept. Mixing them makes each less clear.
- **Lifecycle coupling** — updating the join config requires modifying the table resource, which may trigger unrelated reconciliation. Deleting a table deletes its joins implicitly.
- **Multiple joins from one table** — requires `joins` array, making the table spec complex. With a dedicated CRD, you simply create additional `KasprJoin` resources.
- **Status complexity** — table status must now include join-specific health (subscription lag, table reference validation), muddying its semantics.

**Verdict:** Not recommended. The dedicated CRD is cleaner for users, operators, and future extensibility.

### Alternative B: `keyJoin` on `KasprAgent` Input

Define the join inline on the agent that consumes it:

```yaml
spec:
  input:
    keyJoin:
      leftTable: orders
      rightTable: products
      extractor: ...
```

**Pros:** Join definition is co-located with the consumer.  
**Cons:** Ties the join lifecycle to the agent; if multiple agents need the same join, the config is duplicated; conceptually the join is between tables, not owned by an agent.

**Verdict:** Not recommended. The join is a table-level relationship, not an agent-level concern.

### Alternative C: Implicit Channel Name

Don't require `outputChannel` — always auto-generate the channel name as `{name}-channel`.

**Pros:** Less config.  
**Cons:** Users must know the naming convention; less explicit.

**Verdict:** Use auto-generated default but allow override via `outputChannel`. This is the recommended approach (already part of the proposal).

---

## Open Questions

1. **Multiple joins from one table** — A table could be the left side of multiple joins (e.g., orders → products AND orders → customers). The dedicated CRD handles this naturally: create one `KasprJoin` per relationship. No schema changes needed.

2. **Key join status/health** — Should the `KasprJoin` status include join health metrics (subscription topic lag, response latency, etc.)? Useful for monitoring but adds complexity. Recommend basic table-reference validation for v1, metrics in v2.

3. **Cross-namespace joins** — Should `leftTable`/`rightTable` support referencing tables in a different namespace? Not currently supported by the operator's label-based ownership model. Recommend keeping same-namespace only.

4. **JoinedValue format** — Faust emits `JoinedValue(left=..., right=...)` as a named tuple. When serialized for the processor pipeline, this becomes `{"left": ..., "right": ...}`. Need to verify the exact serialization format in kaspr's `PyCode` execution context.

5. **Table ordering at build time** — The builder must ensure tables are created before key joins are wired. A two-pass approach (build all tables first, then wire joins) is recommended and matches the current builder pattern.

6. **Short name convention** — Recommended short names for `kubectl`: `kjoin` and `kj` (e.g., `kubectl get kjoin`). Plural name: `kasprjoins`.

7. **Cascading reconciliation** — When a `KasprJoin` is created/updated/deleted, the parent `KasprApp` needs to be reconciled to pick up the change. This follows the same pattern as other child resources (agents, tables, tasks) triggering app reconciliation via label selectors.
