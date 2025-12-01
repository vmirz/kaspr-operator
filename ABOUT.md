# Kaspr Kubernetes Operator - Technical Overview

## Core Purpose
Kaspr is a Kubernetes operator that manages stream processing applications built on the [Kaspr framework](https://github.com/TotalWineLabs/kaspr). It simplifies deployment and management of distributed, stateful stream processing pipelines on Kubernetes using Kafka as the messaging backbone.

---

## Architecture & Components

### 1. Main Custom Resource Definitions (CRDs)

#### **KasprApp** - The core application resource
- Represents a distributed stream processing application cluster
- Manages a StatefulSet of Kaspr pods with Kafka connectivity
- Handles: replicas, authentication, storage (persistent/ephemeral), resource limits, Kafka bootstrap servers
- Status tracking: member health, rebalancing state, rollout progress, linked resources
- Features: automatic rebalancing, hung member detection, HPA scaling policies

#### **KasprAgent** - Stream processor with transformation pipelines
- Subscribes to Kafka topics/channels as input
- Executes Python code pipelines with operations: `map`, `filter`, table lookups
- Publishes processed data to output topics/channels
- Supports complex processing: initialization code, table joins, conditional routing
- Can partition isolation for parallel processing

#### **KasprTable** - Distributed state table backed by Kafka changelog topics
- Key-value storage with changelog topic persistence
- Supports global (replicated to all nodes) or partitioned tables
- Window operations: tumbling/hopping windows for time-based aggregations
- Serialization: raw, json for keys/values
- Used by agents/webviews for state lookups and joins

#### **KasprWebView** - HTTP endpoint handlers
- Exposes REST APIs (`GET`, `POST`, `PUT`, `DELETE`, etc.)
- Request processing pipelines similar to agents
- Response transformation: status codes, headers, body selectors
- Can interact with tables and send messages to topics
- Supports error handling with custom transformations

#### **KasprTask** - Scheduled/periodic jobs
- Cron-based or interval-based execution
- Runs on leader member only (optional) or all members
- Same processor pipeline model as agents
- Can write to topics and access tables

---

### 2. Operator Architecture Patterns

#### **Handler-Resource Split**
- **Handlers** (`kaspr/handlers/`): Kopf event handlers for CRD lifecycle (create, update, delete, field watches, timers, daemons)
- **Resources** (`kaspr/resources/`): Kubernetes resource generation (StatefulSet, Service, ConfigMap, HPA, PVC)
- **Base classes**: All resources inherit from `BaseResource` with common K8s operations

#### **Type System**
- **Models** (`kaspr/types/models/`): Python dataclasses for internal representation
- **Schemas** (`kaspr/types/schemas/`): Marshmallow validation for CRD specs
- Split allows clean validation → internal model conversion

#### **Async Reconciliation Queue**
- Per-resource queues prevent duplicate concurrent reconciliations
- `request_reconciliation()` enqueues work
- `names_in_queue` set prevents duplicates
- Timer handler processes queue with 1.5s interval

---

### 3. Key Operator Features

#### **Subscription-Aware Auto-Rebalancing**
- Tracks linked resources (agents, tables) in `status.linkedResources`
- Detects subscription-affecting changes (topic names, patterns, table changelog topics)
- Sets `status.rebalanceRequired` flag when subscriptions change
- Automatically triggers rebalance when conditions met (no rollout, all members ready)
- Configurable via `kaspr.io/auto-rebalance` annotation or global config

#### **Hung Member Detection & Recovery**
- Monitors members stuck in rebalancing state (3-strike system)
- Tracks `lastTransitionTime` for member state changes
- Configurable threshold (default 300s) via annotation or global config
- Terminates hung pods after 3 consecutive detections
- Limits to 5 concurrent terminations to avoid cluster instability
- Only runs when rollout complete (`Progressing=False`)

#### **Instrumentation & Observability**
- **Sensor pattern** (Faust-inspired): lifecycle hooks for monitoring
- **PrometheusMonitor**: Exposes operator metrics via `/metrics`
  - Reconciliation loop metrics: duration, queue depth, errors
  - Rebalance & member health: rebalance duration, hung members, state transitions
  - Resource sync metrics: K8s operation latency, drift detection
- **SensorDelegate**: Multiplexes events to multiple sensors

#### **Resource Ownership & Label Selectors**
- Child resources (agents, tables, etc.) linked via `kaspr.io/app: <app-name>` label
- Operator watches label selectors to find related resources
- Daemon handlers monitor child resources and trigger parent reconciliation

#### **Volume-Mounted Resource Patterns**
- Agent/table/webview Python code stored in ConfigMaps
- Mounted into KasprApp pods as volumes
- Allows hot-reloading of processing logic without image rebuilds

---

### 4. Configuration & Settings

#### **Environment-Driven Configuration** (`kaspr/types/settings.py`)
- `INITIAL_MAX_REPLICAS`: Starting replica limit for scale-up
- `HPA_SCALE_UP_POLICY_*`: Horizontal pod autoscaler policies
- `CLIENT_STATUS_CHECK_ENABLED`: Web client health checking
- `AUTO_REBALANCE_ENABLED`: Global auto-rebalance toggle
- `HUNG_MEMBER_DETECTION_ENABLED`: Global hung detection toggle
- `HUNG_REBALANCING_THRESHOLD_SECONDS`: Default hung threshold (300s)

#### **Per-App Annotation Overrides**
- `kaspr.io/pause-reconciliation`: Pause reconciliation loop
- `kaspr.io/rebalance`: Manual rebalance trigger
- `kaspr.io/auto-rebalance`: Override global auto-rebalance
- `kaspr.io/hung-member-detection-enabled`: Override global hung detection
- `kaspr.io/hung-rebalancing-threshold-seconds`: Override hung threshold

---

### 5. Reconciliation Lifecycle

1. **Trigger**: Field change, timer (30s), daemon monitoring, or queue request
2. **Queue**: Request enqueued if not already queued
3. **Dequeue**: Timer handler picks up work
4. **Reconcile**: 
   - Synchronize desired state (StatefulSet, Service, ConfigMap, etc.)
   - Patch resources if needed
5. **Status Update**: 
   - Fetch app status from web client
   - Fetch related resources (agents, tables, etc.)
   - Detect subscription changes
   - Detect hung members
   - Update conditions (`Progressing`, `Ready`)
   - Attempt auto-rebalance if required
6. **Cleanup**: Mark work done, allow re-queuing

---

### 6. Web Client Integration

- KasprApp pods expose HTTP API for cluster operations
- Operator uses `kaspr/web/client.py` to interact:
  - `GET /status/`: Fetch member health, rebalancing state, version
  - `POST /signal/rebalance/`: Trigger cluster rebalance
- Status checks configurable via `CLIENT_STATUS_CHECK_ENABLED`
- Timeout configurable via `CLIENT_STATUS_CHECK_TIMEOUT_SECONDS`

---

## Development Context

### **Technology Stack**
- Python 3.x with async/await
- [Kopf](https://kopf.readthedocs.io/) - Kubernetes operator framework
- kubernetes_asyncio - Async Kubernetes client
- Marshmallow - Schema validation
- Prometheus - Metrics exposition
- Kafka - Messaging backbone (via Kaspr framework)

### **Key Files for New CRD Development**
1. `crds/<resource>.crd.yaml` - CRD definition
2. `kaspr/types/models/<resource>_spec.py` - Internal model
3. `kaspr/types/schemas/<resource>_spec.py` - Validation schema
4. `kaspr/handlers/<resource>.py` - Kopf event handlers
5. `kaspr/resources/<resource>.py` - K8s resource generation
6. `kaspr/app.py` - Register handlers on startup

### **Code Organization**
```
kaspr-operator/
├── crds/                           # CRD YAML definitions
├── kaspr/
│   ├── app.py                      # Main entry point, Kopf startup
│   ├── handlers/                   # Kopf event handlers
│   │   ├── kasprapp.py            # Core reconciliation logic
│   │   ├── kaspragent.py
│   │   ├── kasprtable.py
│   │   ├── kasprwebview.py
│   │   └── kasprtask.py
│   ├── resources/                  # K8s resource generation
│   │   ├── base.py                # BaseResource with common operations
│   │   ├── kasprapp.py
│   │   ├── kaspragent.py
│   │   └── ...
│   ├── types/
│   │   ├── settings.py            # Environment config
│   │   ├── models/                # Python dataclasses
│   │   └── schemas/               # Marshmallow validation
│   ├── utils/
│   │   ├── helpers.py             # upsert_condition, etc.
│   │   └── errors.py
│   ├── web/                        # Web client for Kaspr pods
│   │   ├── client.py
│   │   └── session.py
│   └── sensors/                    # Monitoring infrastructure
│       ├── base.py                # OperatorSensor base class
│       ├── prometheus.py          # PrometheusMonitor
│       └── delegate.py            # SensorDelegate multiplexer
├── examples/                       # Example CRD manifests
└── deploy/helm/                    # Helm chart
```

---

## Common Patterns & Best Practices

### **Adding a New CRD**
1. Define CRD YAML in `crds/` with `x-kubernetes-preserve-unknown-fields: true` for flexible schemas
2. Create model in `kaspr/types/models/<resource>_spec.py`
3. Create schema in `kaspr/types/schemas/<resource>_spec.py`
4. Implement handler in `kaspr/handlers/<resource>.py` with Kopf decorators
5. Implement resource class in `kaspr/resources/<resource>.py` inheriting from `BaseResource`
6. Register handlers in `kaspr/app.py` imports
7. Add sensor hooks if monitoring is needed

### **Status Condition Management**
Use `upsert_condition()` from `kaspr/utils/helpers.py` for consistent status updates:
```python
conds = upsert_condition(conds, {
    "type": "Progressing", 
    "status": "True",
    "reason": "Reconciling",
    "message": "Waiting for resources",
    "observedGeneration": gen
})
```

### **Resource Generation Pattern**
1. Spec validation via Marshmallow schemas
2. Kubernetes manifest generation in `render_*()` methods
3. Apply/patch through `kubernetes_asyncio` client with error handling
4. Hash annotations for change detection: `kaspr.io/resource-hash`

### **Instrumentation**
Always instrument critical operations:
```python
sensor = get_sensor()
if sensor:
    state = sensor.on_operation_start(...)
    # ... do work ...
    sensor.on_operation_complete(..., state, success)
```

---

## Current Development

### **Active Branch: hung-detection**
Features implemented:
- Hung member detection (3-strike system)
- Member state tracking with `lastTransitionTime`
- Automatic pod termination for hung members
- Prometheus metrics for hung member monitoring
- Configurable thresholds per-app or globally

### **Recent Enhancements**
- Subscription-aware auto-rebalancing
- Enhanced status tracking for linked resources
- Prometheus metrics for all operator lifecycle events
- Queue-based reconciliation to prevent duplicate work
- Resource drift detection capabilities

---

## Operational Notes

### **Annotation-Driven Operations**
Certain operations can be triggered via annotations on KasprApp resources:
- `kaspr.io/pause-reconciliation: "true"` - Pause reconciliation loop
- `kaspr.io/rebalance: "true"` - Trigger ad-hoc cluster rebalance (auto-removed after attempt)

### **Gotchas**
- Always set `PYTHONPATH` when running locally: `export PYTHONPATH="${PYTHONPATH}:$(pwd)"`
- Child resources require proper labels for ownership (`kaspr.io/app: <app-name>`)
- StatefulSet updates require careful deletion timeout handling (see `STATEFULSET_DELETION_TIMEOUT_SECONDS`)
- Web client operations are async and require proper session management
- The operator expects child resources to have proper labels for ownership

### **Local Development**
```bash
# Install dependencies
pip install -r requirements-dev.txt

# Run operator locally (watches all namespaces)
kopf run kaspr/app.py --verbose --all-namespaces

# Apply test resources
kubectl apply -f examples/app/basic.yaml
kubectl apply -f examples/agent/basic.yaml
```

---

## Related Documentation
- [Kaspr Framework](https://github.com/TotalWineLabs/kaspr)
- [Kopf Documentation](https://kopf.readthedocs.io/)
- See `README.md` for installation and usage
- See `RUNNING.md` for operational guide
- See `.github/copilot-instructions.md` for AI assistant context
