# KasprJoin Implementation Plan

> **Design Doc:** [join-crd-design.md](./join-crd-design.md)  
> **Date:** 2025-04-01  
> **Status:** Draft

---

## Overview

This document breaks the `KasprJoin` CRD feature into **6 incremental phases**, each producing a testable, reviewable deliverable. Phases are ordered by dependency — each phase builds on the previous and can be merged independently.

### Repository Map

| Repo | Role | Branch |
|------|------|--------|
| `faust` | Stream processing framework (key join already implemented) | `fk-join` (merged to master) |
| `kaspr-operator` | Kubernetes operator — CRD, types, handlers, resources | `feature/kasprjoin` |
| `kaspr` | Runtime — builder, models, schemas, channel wiring | `feature/kasprjoin` |
| `kaspr-helm` | Helm charts — CRD + resource templates | `feature/kasprjoin` |
| `kaspr-docs` | Documentation — user guide, API reference | `feature/kasprjoin` |

### Phase Dependency Graph

```
Phase 1 (Operator Types)
    │
    ├── Phase 2 (Operator CRD + Resources + Handlers)
    │       │
    │       └── Phase 4 (Helm Charts)
    │
    └── Phase 3 (Kaspr Runtime)
            │
            └── Phase 5 (Integration Testing)
                    │
                    └── Phase 6 (Documentation)
```

---

## Phase 1: Operator Types (Model + Schema)

**Repo:** `kaspr-operator`  
**Goal:** Define the data types that all other operator components depend on. This is the foundation.

### Step 1.1 — Create spec model

Create `kaspr/types/models/kasprjoin_spec.py`:

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

### Step 1.2 — Create resource naming scheme

Create `kaspr/types/models/kasprjoin_resources.py`:

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

### Step 1.3 — Create marshmallow schema

Create `kaspr/types/schemas/kasprjoin_spec.py`:

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

### Step 1.4 — Register in `__init__.py` exports

**Modify** `kaspr/types/models/__init__.py`:
- Import and export `KasprJoinSpec`, `KasprJoinResources`
- Add both to `__all__`

**Modify** `kaspr/types/schemas/__init__.py`:
- Import and export `KasprJoinSpecSchema`
- Add to `__all__`

### Step 1.5 — Add to `KasprAppComponents`

**Modify** `kaspr/types/models/component.py`:
- Import `KasprJoinSpec`
- Add field: `joins: Optional[List[KasprJoinSpec]]`

**Modify** `kaspr/types/schemas/component.py`:
- Import `KasprJoinSpecSchema`
- Add field:
  ```python
  joins = fields.List(
      fields.Nested(KasprJoinSpecSchema()),
      data_key="joins",
      required=False,
      load_default=[],
  )
  ```

### Step 1.6 — Write unit tests

Create `tests/unit/test_kasprjoin_types.py`:
- Test `KasprJoinSpecSchema().load(...)` with valid input
- Test required field validation (`name`, `leftTable`, `rightTable`, `extractor`)
- Test `join_type` defaults to `"inner"`
- Test `output_channel` defaults to `None`
- Test `camel_to_snake` dump conversion
- Test `KasprAppComponents` includes `joins` field

### ✅ Phase 1 Checklist

- [ ] `kaspr/types/models/kasprjoin_spec.py` — created
- [ ] `kaspr/types/models/kasprjoin_resources.py` — created
- [ ] `kaspr/types/schemas/kasprjoin_spec.py` — created
- [ ] `kaspr/types/models/__init__.py` — updated exports
- [ ] `kaspr/types/schemas/__init__.py` — updated exports
- [ ] `kaspr/types/models/component.py` — added `joins` field
- [ ] `kaspr/types/schemas/component.py` — added `joins` field
- [ ] `tests/unit/test_kasprjoin_types.py` — passing
- [ ] All existing tests still pass

---

## Phase 2: Operator CRD + Resource + Handler

**Repo:** `kaspr-operator`  
**Goal:** Make the operator recognize, reconcile, and manage `KasprJoin` custom resources.  
**Depends on:** Phase 1

### Step 2.1 — Create CRD YAML

Create `crds/kasprjoin.crd.yaml`:

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
                description:
                  type: string
                leftTable:
                  type: string
                rightTable:
                  type: string
                extractor:
                  type: object
                  properties:
                    entrypoint:
                      type: string
                    python:
                      type: string
                  required:
                    - python
                type:
                  type: string
                  enum: ["inner", "left"]
                  default: "inner"
                outputChannel:
                  type: string
              required:
                - name
                - leftTable
                - rightTable
                - extractor
            status:
              type: object
              x-kubernetes-preserve-unknown-fields: true
```

### Step 2.2 — Create resource class

Create `kaspr/resources/kasprjoin.py`:

```python
from typing import Dict
from kaspr.types.models import KasprJoinSpec, KasprJoinResources
from kaspr.utils.objects import cached_property
from kaspr.resources.appcomponent import BaseAppComponent
from kaspr.types.models import KasprAppComponents


class KasprJoin(BaseAppComponent):
    """Kaspr Join kubernetes resource."""

    KIND = "KasprJoin"
    COMPONENT_TYPE = "join"
    PLURAL_NAME = "kasprjoins"
    kaspr_resource = KasprJoinResources

    spec: KasprJoinSpec

    @classmethod
    def from_spec(cls, name, kind, namespace, spec, labels=None):
        join_resource = KasprJoin(name, kind, namespace, cls.KIND, labels)
        join_resource.spec = spec
        join_resource.spec.name = name
        join_resource.config_map_name = cls.kaspr_resource.config_name(name)
        join_resource.volume_mount_name = cls.kaspr_resource.volume_mount_name(name)
        return join_resource

    @classmethod
    def default(cls):
        return KasprJoin(
            name="default", kind=cls.KIND,
            namespace=None, component_type=cls.COMPONENT_TYPE,
        )

    @cached_property
    def app_components(self):
        return KasprAppComponents(joins=[self.spec])
```

### Step 2.3 — Register resource export

**Modify** `kaspr/resources/__init__.py`:
- Import `KasprJoin` from `.kasprjoin`
- Add to `__all__`

### Step 2.4 — Create handler

Create `kaspr/handlers/kasprjoin.py` with:
- `@kopf.on.resume/create/update` — reconciliation handler
  - Deserialize spec via `KasprJoinSpecSchema`
  - Create `KasprJoin.from_spec()`
  - Validate app existence
  - Validate left/right table existence
  - Call `join_resource.create()` (creates ConfigMap)
  - Patch status with app/table validation results + configMap + hash
  - Emit warning events for missing app/tables
- `@kopf.timer(interval=1)` — patch_resource queue drainer
- `@kopf.daemon(initial_delay=5.0)` — monitor_join
  - Continuous monitoring loop (10s interval)
  - Checks app + left table + right table existence
  - Updates status when availability changes
  - Emits events on state transitions
- `@kopf.timer(initial_delay=5.0, interval=60.0)` — reconcile (full sync)
  - Periodic full synchronization
  - Integrates with `SensorDelegate` for metrics

(Full handler code is in the design doc.)

### Step 2.5 — Create example manifests

Create `examples/join/basic.yaml`:
- Two `KasprTable` resources (orders, products)
- One `KasprJoin` resource (orders-products-join)
- One `KasprAgent` consuming the join channel

### Step 2.6 — Manual validation

```bash
# Apply CRD
kubectl apply -f crds/kasprjoin.crd.yaml

# Run operator locally
PYTHONPATH="${PYTHONPATH}:$(pwd)" kopf run kaspr/app.py --verbose --all-namespaces

# Apply example resources
kubectl apply -f examples/join/basic.yaml

# Verify
kubectl get kasprjoins
kubectl get kjoin
kubectl describe kjoin orders-products-join
```

### ✅ Phase 2 Checklist

- [ ] `crds/kasprjoin.crd.yaml` — created
- [ ] `kaspr/resources/kasprjoin.py` — created
- [ ] `kaspr/resources/__init__.py` — updated
- [ ] `kaspr/handlers/kasprjoin.py` — created
- [ ] `examples/join/basic.yaml` — created
- [ ] CRD applies cleanly to cluster
- [ ] Operator starts without errors
- [ ] `kubectl get kasprjoins` works
- [ ] Status shows app/table validation results
- [ ] Warning events emitted for missing tables
- [ ] ConfigMap created with serialized spec
- [ ] All existing tests still pass

---

## Phase 3: Kaspr Runtime

**Repo:** `kaspr`  
**Goal:** Make the kaspr runtime understand join definitions, wire up `Table.key_join()`, and register output channels for agents to consume.  
**Depends on:** Phase 1 (types pattern — not code dependency, just pattern alignment)

### Step 3.1 — Create join model

Create `kaspr/types/models/join/` directory:

**`kaspr/types/models/join/__init__.py`:**
```python
from .join import JoinSpec
```

**`kaspr/types/models/join/join.py`:**
```python
from typing import Optional
from kaspr.types.models.base import SpecComponent
from kaspr.types.models.pycode import PyCode
from kaspr.types.app import KasprAppT


class JoinSpec(SpecComponent):
    name: str
    left_table: str
    right_table: str
    extractor: PyCode
    join_type: Optional[str]        # "inner" or "left"
    output_channel: Optional[str]

    app: KasprAppT = None
```

### Step 3.2 — Create join schema

Create `kaspr/types/schemas/join/` directory:

**`kaspr/types/schemas/join/__init__.py`:**
```python
from .join import JoinSpecSchema
```

**`kaspr/types/schemas/join/join.py`:**
- `JoinSpecSchema` with fields for `name`, `left_table`, `right_table`, `extractor` (nested `PyCodeSchema`), `join_type`, `output_channel`
- `camelCase` → `snake_case` mapping via `data_key`

### Step 3.3 — Register in type exports

**Modify** `kaspr/types/models/__init__.py`:
- Import and export `JoinSpec`

**Modify** `kaspr/types/schemas/__init__.py`:
- Import and export `JoinSpecSchema`

### Step 3.4 — Add joins to `AppSpec`

**Modify** `kaspr/types/models/app.py`:
- Import `JoinSpec`
- Add field: `joins_spec: Optional[List[JoinSpec]]`
- Add property:
  ```python
  @property
  def joins(self):
      if self.app:
          if self._joins is None:
              self._joins = self._wire_joins()
          return self._joins
  
  def _wire_joins(self):
      """Wire up key joins between tables."""
      results = []
      for join_spec in (self.joins_spec or []):
          left_table = self.app.tables[join_spec.left_table]
          right_table = self.app.tables[join_spec.right_table]
          extractor = join_spec.extractor.func
          inner = (join_spec.join_type or "inner") == "inner"
          channel = left_table.key_join(
              right_table, extractor=extractor, inner=inner
          )
          channel_name = join_spec.output_channel or f"{join_spec.name}-channel"
          self.app.register_named_channel(channel_name, channel)
          results.append(channel)
      return results
  ```

**Modify** `kaspr/types/schemas/app.py`:
- Import `JoinSpecSchema`
- Add `joins_spec` field to `AppSpecSchema`

### Step 3.5 — Add named channel registry to app

**Modify** `kaspr/core/app.py` (or `kaspr/types/app.py` — wherever `KasprApp` is defined):
- Add `_named_channels: Dict[str, ChannelT] = {}`
- Add method:
  ```python
  def register_named_channel(self, name: str, channel) -> None:
      self._named_channels[name] = channel
  
  def resolve_named_channel(self, name: str):
      return self._named_channels.get(name)
  ```

### Step 3.6 — Update `ChannelSpec.prepare_channel()` for named channels

**Modify** `kaspr/types/models/channel.py`:
- Update `prepare_channel()` to first try resolving from named channels:
  ```python
  def prepare_channel(self) -> KasprChannelT:
      # Try named channel first (e.g., from a KasprJoin output)
      named = self.app.resolve_named_channel(self.name)
      if named is not None:
          return named
      # Fall back to creating a new in-memory channel
      return self.app.channel(self.name)
  ```

### Step 3.7 — Wire joins in builder

**Modify** `kaspr/core/builder.py`:
- Import `JoinSpec`
- Add `_joins` list field
- Add `_prepare_joins()` method
- Add `joins` cached_property
- Update `build()` to call `app.joins` **after** `app.tables`:
  ```python
  def build(self) -> None:
      for app in self.apps:
          app.agents
          app.webviews
          app.tables     # Must come first — creates table instances
          app.joins      # NEW — wires key joins, registers channels
          app.tasks
  ```
  **Important:** `app.joins` must run after `app.tables` (needs table instances) and before `app.agents` are prepared (so channels are registered before agents try to resolve them). Since `app.agents` is listed first but agents lazily resolve channels, the ordering within `build()` should ensure tables and joins are wired before any agent starts consuming.

### ✅ Phase 3 Checklist

- [ ] `kaspr/types/models/join/__init__.py` — created
- [ ] `kaspr/types/models/join/join.py` — created
- [ ] `kaspr/types/schemas/join/__init__.py` — created
- [ ] `kaspr/types/schemas/join/join.py` — created
- [ ] `kaspr/types/models/__init__.py` — updated
- [ ] `kaspr/types/schemas/__init__.py` — updated
- [ ] `kaspr/types/models/app.py` — added `joins_spec`, `joins` property, `_wire_joins()`
- [ ] `kaspr/types/schemas/app.py` — added `joins_spec` field
- [ ] `kaspr/core/app.py` — added `_named_channels`, `register_named_channel()`, `resolve_named_channel()`
- [ ] `kaspr/types/models/channel.py` — updated `prepare_channel()` to check named channels
- [ ] `kaspr/core/builder.py` — added joins to `build()` sequence
- [ ] Unit test: JoinSpec model creation
- [ ] Unit test: JoinSpecSchema load/dump
- [ ] Unit test: named channel registration and resolution
- [ ] Unit test: ChannelSpec resolves named channel

---

## Phase 4: Helm Charts

**Repo:** `kaspr-helm`  
**Goal:** Ship the CRD and add resource template support so users can deploy `KasprJoin` resources via Helm values.  
**Depends on:** Phase 2 (CRD YAML)

### Step 4.1 — Add CRD to operator chart

Copy the finalized `kasprjoin.crd.yaml` to:
```
kaspr-helm/charts/operator/crds/kasprjoin.crd.yaml
```

### Step 4.2 — Create resource template

Create `kaspr-helm/charts/resources/templates/joins.yaml`:

```yaml
{{- if .Values.joins }}
{{- $root := . -}}
{{- range .Values.joins }}
---
apiVersion: kaspr.io/v1alpha1
kind: KasprJoin
metadata:
  name: {{ .name }}
spec:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- end }}
```

### Step 4.3 — Add example to values.yaml

**Modify** `kaspr-helm/charts/resources/values.yaml`:
- Add a `joins:` section with a commented-out example:
  ```yaml
  # A list of joins to deploy.
  joins: []
  # - name: orders-products-join
  #   description: "Join orders with products by product_id"
  #   leftTable: orders
  #   rightTable: products
  #   extractor:
  #     entrypoint: get_product_id
  #     python: |
  #       def get_product_id(value):
  #           return value.get("product_id")
  #   type: inner
  #   outputChannel: orders-products-joined
  ```

### Step 4.4 — Bump chart versions

**Modify** `kaspr-helm/charts/operator/Chart.yaml`:
- Bump `version` (chart version)

**Modify** `kaspr-helm/charts/resources/Chart.yaml`:
- Bump `version` (chart version)

### Step 4.5 — Validate

```bash
# Lint
helm lint charts/operator
helm lint charts/resources

# Template render
helm template test charts/resources -f charts/resources/values.yaml --set 'joins[0].name=test-join,joins[0].leftTable=a,joins[0].rightTable=b,joins[0].extractor.python=def f(v): return v'

# Dry-run install
helm install --dry-run test-operator charts/operator
```

### ✅ Phase 4 Checklist

- [ ] `charts/operator/crds/kasprjoin.crd.yaml` — added
- [ ] `charts/resources/templates/joins.yaml` — created
- [ ] `charts/resources/values.yaml` — added `joins` section
- [ ] `charts/operator/Chart.yaml` — version bumped
- [ ] `charts/resources/Chart.yaml` — version bumped
- [ ] `helm lint` passes for both charts
- [ ] `helm template` renders KasprJoin correctly

---

## Phase 5: Integration Testing

**Repos:** `kaspr-operator` + `kaspr`  
**Goal:** Verify the full flow end-to-end — from CRD creation through operator reconciliation to runtime join wiring and data flow.  
**Depends on:** Phases 2 + 3

### Step 5.1 — Operator integration test

**Create** `tests/unit/test_kasprjoin_resource.py` (in `kaspr-operator`):
- Test `KasprJoin.from_spec()` creates correct resource
- Test `app_components` returns `KasprAppComponents` with `joins`
- Test ConfigMap naming via `KasprJoinResources`
- Test schema round-trip: YAML → schema load → model → schema dump → matches original

### Step 5.2 — Operator handler test

**Create** `tests/unit/test_kasprjoin_handler.py` (in `kaspr-operator`):
- Test reconciliation handler with mocked KasprApp/KasprTable fetches
- Test status patching when app found / not found
- Test status patching when left table found / not found
- Test status patching when right table found / not found
- Test warning events emitted for missing references

### Step 5.3 — Kaspr runtime test

Create tests in `kaspr` repo (or local test scripts):
- Test `JoinSpec` model creation with all fields
- Test `JoinSpecSchema` load from YAML-like dict
- Test named channel registration + resolution
- Test `ChannelSpec.prepare_channel()` prefers named channel
- Test that `app.joins` calls `left_table.key_join()` correctly (mock Faust tables)

### Step 5.4 — End-to-end manual test

Use the example manifests from Phase 2:

```bash
# 1. Deploy operator (with new CRD)
helm upgrade --install kaspr-operator charts/operator

# 2. Deploy test resources
kubectl apply -f examples/join/basic.yaml

# 3. Verify CRD status
kubectl get kjoin -o wide
kubectl describe kjoin orders-products-join

# 4. Verify ConfigMap created
kubectl get configmap orders-products-join -o yaml

# 5. Produce test data to raw-orders and raw-products topics

# 6. Verify enriched-orders topic receives joined output

# 7. Test lifecycle: delete join, verify cleanup
kubectl delete kjoin orders-products-join
```

### Step 5.5 — Edge case testing

- Create `KasprJoin` before its referenced tables exist → verify warning events, then tables created → verify status transitions to `TableFound`
- Create `KasprJoin` referencing a non-existent app → verify `AppNotFound` status
- Delete a referenced table → verify monitor daemon detects and updates status
- Create multiple joins from the same left table → verify both produce independent channels
- Test `type: left` join → verify `JoinedValue` emitted with `right=None` when no match

### ✅ Phase 5 Checklist

- [ ] `tests/unit/test_kasprjoin_resource.py` — passing (operator)
- [ ] `tests/unit/test_kasprjoin_handler.py` — passing (operator)
- [ ] Kaspr runtime join tests — passing
- [ ] End-to-end manual test — successful
- [ ] Edge cases validated
- [ ] No regressions in existing tests

---

## Phase 6: Documentation

**Repo:** `kaspr-docs`  
**Goal:** Provide user-facing documentation for the `KasprJoin` CRD.  
**Depends on:** Phases 2 + 3 (feature complete)

### Step 6.1 — Create user guide page

Create `pages/docs/user-guide/joins.mdx`:
- **What is a KasprJoin?** — Conceptual overview of table-to-table key joins
- **How it works** — Simplified protocol diagram (subscription/response)
- **Creating a join** — Step-by-step YAML walkthrough:
  1. Define two `KasprTable` resources
  2. Define a `KasprJoin` connecting them
  3. Define a `KasprAgent` consuming the join channel
- **Join types** — `inner` vs `left` with examples
- **JoinedValue format** — `{"left": ..., "right": ...}` structure
- **Working with the extractor** — Python function examples
- **Output channel naming** — Default vs explicit `outputChannel`
- **Monitoring joins** — `kubectl get kjoin`, status fields, events
- **Full example** — Complete order enrichment scenario

### Step 6.2 — Update agents page

**Modify** `pages/docs/user-guide/agents.mdx`:
- Add section: "Consuming a Join Channel"
- Show `input.channel.name` referencing a join's `outputChannel`
- Link to the new joins page

### Step 6.3 — Update concepts page

**Modify** `pages/docs/user-guide/concepts.mdx`:
- Add "Joins" to the resource types overview
- Brief description + link to full guide
- Update any architecture diagrams to include joins

### Step 6.4 — Add API reference

**Modify** `pages/docs/api-reference/` (add or update v1alpha1 reference):
- `KasprJoin` spec fields table
- Status fields table
- Short names and plural name

### Step 6.5 — Update navigation

**Modify** `pages/docs/user-guide/_meta.js`:
- Add `joins` entry in the navigation order

### ✅ Phase 6 Checklist

- [ ] `pages/docs/user-guide/joins.mdx` — created
- [ ] `pages/docs/user-guide/agents.mdx` — updated with join channel section
- [ ] `pages/docs/user-guide/concepts.mdx` — updated with joins
- [ ] API reference — `KasprJoin` documented
- [ ] `pages/docs/user-guide/_meta.js` — navigation updated
- [ ] Docs build locally without errors (`pnpm dev`)
- [ ] All links resolve correctly

---

## Release Checklist

After all phases are complete:

- [ ] **Faust**: Confirm `fk-join` branch is merged to master, `Table.key_join()` is in the release
- [ ] **kaspr-operator**: All new files created, exports registered, tests passing
- [ ] **kaspr**: Runtime wiring complete, named channel resolution working, tests passing
- [ ] **kaspr-helm**: CRD shipped in operator chart, resource template in resources chart, versions bumped
- [ ] **kaspr-docs**: User guide, concepts, agents page, and API reference all updated
- [ ] **Version alignment**: Ensure `kaspr` depends on the correct `faust` version (≥ 1.17.10)
- [ ] **CHANGELOG.md**: Updated in kaspr-operator and kaspr repos
- [ ] **Tag releases**: Tag all repos consistently

---

## File Index

Quick reference of all files touched across the stack.

### New Files

| Repo | File |
|------|------|
| `kaspr-operator` | `crds/kasprjoin.crd.yaml` |
| `kaspr-operator` | `kaspr/types/models/kasprjoin_spec.py` |
| `kaspr-operator` | `kaspr/types/models/kasprjoin_resources.py` |
| `kaspr-operator` | `kaspr/types/schemas/kasprjoin_spec.py` |
| `kaspr-operator` | `kaspr/resources/kasprjoin.py` |
| `kaspr-operator` | `kaspr/handlers/kasprjoin.py` |
| `kaspr-operator` | `examples/join/basic.yaml` |
| `kaspr-operator` | `tests/unit/test_kasprjoin_types.py` |
| `kaspr-operator` | `tests/unit/test_kasprjoin_resource.py` |
| `kaspr-operator` | `tests/unit/test_kasprjoin_handler.py` |
| `kaspr` | `kaspr/types/models/join/__init__.py` |
| `kaspr` | `kaspr/types/models/join/join.py` |
| `kaspr` | `kaspr/types/schemas/join/__init__.py` |
| `kaspr` | `kaspr/types/schemas/join/join.py` |
| `kaspr-helm` | `charts/operator/crds/kasprjoin.crd.yaml` |
| `kaspr-helm` | `charts/resources/templates/joins.yaml` |
| `kaspr-docs` | `pages/docs/user-guide/joins.mdx` |

### Modified Files

| Repo | File | Change |
|------|------|--------|
| `kaspr-operator` | `kaspr/types/models/__init__.py` | Add exports |
| `kaspr-operator` | `kaspr/types/schemas/__init__.py` | Add exports |
| `kaspr-operator` | `kaspr/types/models/component.py` | Add `joins` field |
| `kaspr-operator` | `kaspr/types/schemas/component.py` | Add `joins` field |
| `kaspr-operator` | `kaspr/resources/__init__.py` | Add `KasprJoin` export |
| `kaspr` | `kaspr/types/models/__init__.py` | Add `JoinSpec` export |
| `kaspr` | `kaspr/types/schemas/__init__.py` | Add `JoinSpecSchema` export |
| `kaspr` | `kaspr/types/models/app.py` | Add `joins_spec`, `joins` property |
| `kaspr` | `kaspr/types/schemas/app.py` | Add `joins_spec` field |
| `kaspr` | `kaspr/core/app.py` | Add named channel registry |
| `kaspr` | `kaspr/types/models/channel.py` | Resolve named channels |
| `kaspr` | `kaspr/core/builder.py` | Add joins to build sequence |
| `kaspr-helm` | `charts/resources/values.yaml` | Add `joins` section |
| `kaspr-helm` | `charts/operator/Chart.yaml` | Version bump |
| `kaspr-helm` | `charts/resources/Chart.yaml` | Version bump |
| `kaspr-docs` | `pages/docs/user-guide/agents.mdx` | Add join channel section |
| `kaspr-docs` | `pages/docs/user-guide/concepts.mdx` | Add joins overview |
| `kaspr-docs` | `pages/docs/user-guide/_meta.js` | Add navigation entry |
