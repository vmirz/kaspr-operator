# Kaspr Operator - AI Assistant Instructions

## Architecture Overview
This is a Kubernetes operator built with [Kopf](https://kopf.readthedocs.io/) that manages [Kaspr](https://github.com/TotalWineLabs/kaspr) stream processing applications. The operator manages four main custom resources:
- `KasprApp` - Main application instances with Kafka connectivity and storage
- `KasprAgent` - Stream processors with Python code pipelines  
- `KasprWebView` - Web-based data visualization components
- `KasprTable` - Data table resources

## Code Organization Patterns

### Handler-Resource Architecture
- **Handlers** (`kaspr/handlers/`) contain Kopf event handlers for CRD lifecycle management
- **Resources** (`kaspr/resources/`) contain Kubernetes resource generation logic (StatefulSets, Services, etc.)
- **Types** (`kaspr/types/`) split into `models/` (data classes) and `schemas/` (Marshmallow validation)

### Key Files for Understanding Flow
- `kaspr/app.py` - Main entry point with Kopf startup configuration
- `kaspr/handlers/kasprapp.py` - Core reconciliation logic with async queuing system
- `kaspr/resources/base.py` - Base class for all K8s resource management
- `kaspr/types/settings.py` - Environment-driven configuration with scaling policies

### Custom Resource Relationships
KasprApps own child resources (Agents, WebViews, Tables) via label selectors:
```yaml
labels:
  kaspr.io/app: my-app  # Links child to parent KasprApp
```

## Development Workflows

### Local Development
```bash
# Install dependencies
pip install -r requirements-dev.txt

# Run operator locally (watches all namespaces)
kopf run kaspr/app.py --verbose --all-namespaces

# Apply test resources
kubectl apply -f examples/app/basic.yaml
kubectl apply -f examples/agent/basic.yaml
```

### Environment Configuration
Critical settings in `kaspr/types/settings.py` control scaling behavior:
- `INITIAL_MAX_REPLICAS` - Starting replica limit
- `HPA_SCALE_UP_POLICY_*` - Horizontal Pod Autoscaler policies  
- `CLIENT_STATUS_CHECK_ENABLED` - Web client health checking

### CRD Management
CRDs in `crds/` use `x-kubernetes-preserve-unknown-fields: true` for flexible schemas. When modifying:
1. Update CRD YAML files
2. Update corresponding schema in `kaspr/types/schemas/`
3. Update model in `kaspr/types/models/`

## Project-Specific Patterns

### Async Reconciliation Queue
The operator uses a custom queuing system in `kaspr/handlers/kasprapp.py` to prevent duplicate processing:
- `reconciliation_queue` - Per-resource async queues
- `names_in_queue` - Set tracking to prevent duplicates
- Always use `request_reconciliation(name)` to enqueue work

### Status Condition Management
Use `upsert_condition()` from `kaspr/utils/helpers.py` for consistent status updates:
```python
conds = upsert_condition(conds, {
    "type": "Progressing", 
    "status": "True",
    "reason": "Reconciling"
})
```

### Web Client Integration
The operator includes a web client (`kaspr/web/`) for triggering Kaspr cluster operations:
- Rebalancing: `POST /signal/rebalance/`
- Status checks: `GET /status/`
- Configured per KasprApp instance

### Resource Generation
Resources inherit from `BaseResource` and follow this pattern:
1. Spec validation via Marshmallow schemas
2. Kubernetes manifest generation in `render_*()` methods
3. Apply/patch through `kubernetes` client with error handling

## Common Gotchas
- Always set `PYTHONPATH` when running locally: `export PYTHONPATH="${PYTHONPATH}:$(pwd)"`
- The operator expects child resources to have proper labels for ownership
- StatefulSet updates require careful deletion timeout handling (see `STATEFULSET_DELETION_TIMEOUT_SECONDS`)
- Web client operations are async and require proper session management