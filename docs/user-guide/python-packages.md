# Python Package Management

## Overview

The Kaspr Operator provides built-in support for managing Python package dependencies in your stream processing applications. This feature automatically installs and caches Python packages, eliminating the need to rebuild Docker images for every dependency change.

### Key Features

- **Automatic Installation**: Packages are installed automatically during pod initialization
- **Shared Cache**: All pods share a common package cache via PVC
- **Fast Startup**: After first installation, subsequent pods start in <5 seconds
- **Version Pinning**: Full support for pip version specifiers
- **Failure Handling**: Configurable retry logic and failure modes
- **Status Reporting**: Real-time installation status in CRD status field
- **Metrics**: Prometheus metrics for monitoring installation performance

### How It Works

1. **Spec Configuration**: Define packages in `spec.pythonPackages`
2. **PVC Creation**: Operator creates a shared PVC for package cache
3. **Init Container**: Each pod runs an init container to install packages
4. **Cache Check**: Init container checks for existing installation via marker file
5. **Installation**: If not cached, installs packages with pip and creates marker
6. **Fast Path**: Subsequent pods skip installation if marker exists (<5s startup)
7. **Main Container**: Packages available via PYTHONPATH in main container

## Quick Start

### Basic Example

```yaml
apiVersion: kaspr.io/v1alpha1
kind: KasprApp
metadata:
  name: my-stream-processor
  namespace: default
spec:
  replicas: 3
  bootstrapServers: "kafka:9092"
  
  # Add Python packages
  pythonPackages:
    packages:
      - requests
      - pandas>=2.0.0
      - redis[hiredis]
```

Apply the manifest:

```bash
kubectl apply -f my-stream-processor.yaml
```

Verify installation:

```bash
# Check status
kubectl get kasprapp my-stream-processor -o jsonpath='{.status.pythonPackages.state}'
# Output: Ready

# Test import
kubectl exec my-stream-processor-0 -- python -c "import pandas; print(pandas.__version__)"
# Output: 2.1.0
```

## Configuration Reference

### Complete Configuration Example

```yaml
apiVersion: kaspr.io/v1alpha1
kind: KasprApp
metadata:
  name: advanced-app
spec:
  replicas: 5
  bootstrapServers: "kafka:9092"
  
  pythonPackages:
    # Package list with version specifiers
    packages:
      - requests==2.31.0
      - pandas>=2.0.0,<3.0.0
      - numpy==1.24.0
      - scikit-learn>=1.3.0
      - redis[hiredis]>=5.0.0
    
    # Custom PyPI index (optional)
    indexUrl: "https://pypi.org/simple"
    extraIndexUrls:
      - "https://private-pypi.example.com/simple"
    trustedHosts:
      - "private-pypi.example.com"
    
    # Cache configuration
    cache:
      enabled: true
      size: "1Gi"
      storageClass: "fast-ssd"
      accessMode: ReadWriteMany  # Default (only supported mode)
      deleteClaim: true
    
    # Installation policy
    installPolicy:
      retries: 3
      timeout: 600
      onFailure: block
    
    # Init container resources
    resources:
      requests:
        cpu: "200m"
        memory: "512Mi"
      limits:
        cpu: "1000m"
        memory: "1Gi"
```

### Field Reference

#### `packages` (required)

List of packages to install using pip syntax:

| Format | Example | Description |
|--------|---------|-------------|
| Package name | `requests` | Latest version |
| Exact version | `pandas==2.1.0` | Specific version |
| Minimum version | `numpy>=1.24.0` | At least version |
| Version range | `requests>=2.0.0,<3.0.0` | Within range |
| With extras | `redis[hiredis]` | Include optional deps |

**Examples:**

```yaml
packages:
  - requests                    # Latest
  - pandas==2.1.0              # Exact
  - numpy>=1.24.0              # Minimum
  - scikit-learn>=1.0.0,<2.0.0 # Range
  - redis[hiredis]             # With extras
```

#### `indexUrl` (optional)

Primary package index URL. Defaults to PyPI (`https://pypi.org/simple`).

```yaml
indexUrl: "https://private-pypi.example.com/simple"
```

#### `extraIndexUrls` (optional)

Additional package indexes to search. Useful for mixing public and private packages.

```yaml
extraIndexUrls:
  - "https://private-pypi.example.com/simple"
  - "https://internal-repo.example.com/simple"
```

#### `trustedHosts` (optional)

Hosts to trust for HTTPS connections without certificate verification.

```yaml
trustedHosts:
  - "private-pypi.example.com"
  - "internal-repo.example.com"
```

#### `cache`

Controls the shared package cache PVC.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | boolean | `true` | Enable shared cache |
| `size` | string | `"256Mi"` | PVC storage size |
| `storageClass` | string | cluster default | Storage class name (must support RWX) |
| `accessMode` | string | `"ReadWriteMany"` | PVC access mode (only RWX supported) |
| `deleteClaim` | boolean | `true` | Delete PVC when app deleted |

**Recommendations:**

- **Small packages** (requests, redis): 256Mi-512Mi
- **Data science** (pandas, numpy, sklearn): 1Gi-2Gi  
- **ML/DL** (tensorflow, pytorch, transformers): 5Gi-10Gi
- Use **ReadWriteMany** for multi-replica apps
- Use **ReadWriteOnce** if RWX not available (slower scaling)

#### `installPolicy`

Controls installation behavior.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `retries` | integer | `3` | Number of retry attempts |
| `timeout` | integer | `600` | Timeout per package (seconds) |
| `onFailure` | string | `"block"` | Failure mode: `block` or `warn` |

**Failure Modes:**

- **`block`**: Prevent pod startup if installation fails (recommended for critical deps)
- **`warn`**: Log warning but allow pod to start (for optional packages)

**Example:**

```yaml
installPolicy:
  retries: 5              # Retry 5 times
  timeout: 900            # 15 minute timeout
  onFailure: warn         # Don't block pod startup
```

#### `resources`

Resource limits for the init container.

```yaml
resources:
  requests:
    cpu: "200m"
    memory: "512Mi"
  limits:
    cpu: "1000m"
    memory: "1Gi"
```

**Guidelines:**

- **Lightweight packages**: 256Mi memory
- **Medium packages**: 512Mi-1Gi memory
- **Heavy packages** (ML): 2Gi+ memory
- Increase if seeing OOMKilled in init container

## Status Reporting

The operator reports package installation status using Kubernetes conditions and metadata fields.

### Condition-Based Status

Package installation state is tracked via the `PythonPackagesReady` condition:

```yaml
status:
  conditions:
    - type: PythonPackagesReady
      status: "True"                      # True|False|Unknown
      reason: PackagesInstalled           # CamelCase reason code
      message: "Successfully installed 3 packages in 14s"
      lastTransitionTime: "2025-11-30T10:15:30.123456+00:00"
      observedGeneration: 5
    - type: Ready
      status: "True"
      reason: ApplicationReady
      message: "Kaspr app is ready"
      lastTransitionTime: "2025-11-30T10:16:00.456789+00:00"
      observedGeneration: 5
```

### Installation Metadata

Package installation details are stored in `status.pythonPackages`:

```yaml
status:
  pythonPackages:
    hash: "abc123def456"                  # Package spec hash
    installed:                            # List of installed packages
      - requests==2.31.0
      - pandas==2.1.0
    cacheMode: ReadWriteMany              # Actual PVC access mode
    lastInstallTime: "2025-11-30T10:15:30.123456+00:00"  # ISO 8601 timestamp
    installDuration: "45.2s"              # Installation time
    installedBy: "my-app-0"              # Pod that performed install
    warnings: null                        # Warning messages if any
```

### Condition States

| Condition Status | Reason | Description |
|-----------------|--------|-------------|
| `False` | `Installing` | Init container currently installing packages |
| `False` | `PackagesUpdating` | Updating to new package list |
| `True` | `PackagesInstalled` | Packages installed successfully |
| `False` | `InstallationFailed` | Installation failed (init container in CrashLoopBackOff or terminated with error) |
| `Unknown` | `StatusUnknown` | Unable to determine status |

**Note on Installation Failures**: When a package installation fails (e.g., invalid package name, network issues), the init container will retry based on the `retries` setting. During the retry phase, the condition will show `status: False` with `reason: InstallationFailed`. The condition message will contain error details from the init container, though for detailed pip errors you may need to check the init container logs:

```bash
# Get pod name
POD=$(kubectl get pod -n kaspr -l kaspr.io/app=my-app -o jsonpath='{.items[0].metadata.name}')

# View init container logs
kubectl logs -n kaspr $POD -c install-packages
```

If `onFailure: block` is set, the pod will remain in Init state until the issue is resolved. If `onFailure: warn`, the pod will start with the application container despite the installation failure (not recommended for production).

### Querying Status

```bash
# Check if packages are ready (standard Kubernetes pattern)
kubectl wait kasprapp/my-app --for=condition=PythonPackagesReady=True --timeout=300s

# Get condition status
kubectl get kasprapp my-app -o jsonpath='{.status.conditions[?(@.type=="PythonPackagesReady")].status}'

# Get condition reason and message
kubectl get kasprapp my-app -o jsonpath='{.status.conditions[?(@.type=="PythonPackagesReady")]}{"\n"}' | jq

# Get installed packages
kubectl get kasprapp my-app -o jsonpath='{.status.pythonPackages.installed[*]}'

# Get full metadata
kubectl get kasprapp my-app -o jsonpath='{.status.pythonPackages}' | jq
```

# Check for errors
kubectl get kasprapp my-app -o jsonpath='{.status.pythonPackages.error}'
```

## Package Updates

Changing the package list triggers a rolling update of the StatefulSet.

### Update Process

1. **Modify spec**: Change `pythonPackages.packages` in manifest
2. **Apply manifest**: `kubectl apply -f my-app.yaml`
3. **Hash changes**: Operator detects new package hash
4. **Rolling update**: StatefulSet updated with new PACKAGES_HASH env var
5. **Reinstall**: New pods install updated packages
6. **Status update**: Status shows new installation details

**During Rolling Updates**: The operator intelligently tracks the status of pods with the **latest** package hash (matching the current spec), not pods still running with old packages. This ensures the `PythonPackagesReady` condition accurately reflects the current installation attempt, even when the StatefulSet is updating pods one by one.

### Example Update

```yaml
# Original
packages:
  - requests==2.31.0
  - pandas==2.0.0

# Updated
packages:
  - requests==2.31.0
  - pandas==2.1.0    # Version changed
  - numpy==1.24.0     # Package added
```

```bash
kubectl apply -f my-app.yaml
kubectl rollout status statefulset my-app
```

### Watch Update Progress

```bash
# Watch pods
kubectl get pods -l kaspr.io/app=my-app -w

# Watch status
kubectl get kasprapp my-app -o jsonpath='{.status.pythonPackages.state}' -w

# Check init container logs
kubectl logs my-app-0 -c install-packages -f
```

## Use Cases

### Data Science Workloads

```yaml
pythonPackages:
  packages:
    - pandas>=2.0.0
    - numpy>=1.24.0
    - scikit-learn>=1.3.0
    - matplotlib>=3.7.0
    - seaborn>=0.12.0
    - jupyter>=1.0.0
  cache:
    size: "2Gi"
  resources:
    limits:
      memory: "2Gi"
```

### API Integration

```yaml
pythonPackages:
  packages:
    - requests>=2.31.0
    - httpx>=0.24.0
    - pydantic>=2.0.0
    - python-dotenv>=1.0.0
    - aiohttp>=3.8.0
  cache:
    size: "512Mi"
```

### Database Operations

```yaml
pythonPackages:
  packages:
    - psycopg2-binary>=2.9.0    # PostgreSQL
    - pymongo>=4.0.0             # MongoDB  
    - redis[hiredis]>=5.0.0     # Redis
    - sqlalchemy>=2.0.0          # ORM
    - alembic>=1.12.0            # Migrations
  cache:
    size: "1Gi"
```

### ML/AI Applications

```yaml
pythonPackages:
  packages:
    - torch==2.0.1
    - transformers>=4.30.0
    - datasets>=2.14.0
    - accelerate>=0.20.0
  cache:
    size: "10Gi"
    storageClass: "fast-ssd"
  installPolicy:
    timeout: 1800  # 30 minutes for large packages
  resources:
    limits:
      memory: "4Gi"
```

## Monitoring

### Prometheus Metrics

The operator exposes metrics for package installation:

```promql
# Installation duration histogram
kasprop_package_install_duration_seconds{app_name="my-app", namespace="default"}

# Installation count by result
kasprop_package_install_total{app_name="my-app", namespace="default", result="success"}
kasprop_package_install_total{app_name="my-app", namespace="default", result="failure"}

# Error count by type
kasprop_package_install_errors_total{app_name="my-app", namespace="default", error_type="timeout"}
```

### Viewing Metrics

```bash
# Port forward to operator
kubectl port-forward -n kaspr-operator deployment/kaspr-operator 8080:8080

# Query metrics
curl http://localhost:8080/metrics | grep kasprop_package_install

# Specific metric
curl -s http://localhost:8080/metrics | \
  grep 'kasprop_package_install_duration_seconds{app_name="my-app"}'
```

### Grafana Dashboards

Import the provided dashboard:

```bash
kubectl apply -f grafana-dashboards/kaspr-operator.json
```

Includes panels for:
- Installation duration over time
- Success/failure rates
- Error breakdown by type
- Cache hit rates (inferred from duration)

## Troubleshooting

### Installation Failures

**Symptom**: Status shows `Failed` state

**Diagnosis:**

```bash
# Check status error
kubectl get kasprapp my-app -o jsonpath='{.status.pythonPackages.error}'

# Check init container logs
kubectl logs my-app-0 -c install-packages

# Describe pod for events
kubectl describe pod my-app-0
```

**Common causes:**

1. **Network issues**: Cannot reach PyPI
   - Verify cluster internet access
   - Check network policies
   - Try using `indexUrl` for mirror/proxy

2. **Invalid package name**: Package doesn't exist
   - Verify package name on PyPI
   - Check spelling and case

3. **Timeout**: Installation takes too long
   - Increase `installPolicy.timeout`
   - Increase init container memory
   - Consider splitting into smaller package sets

4. **Out of memory**: Init container OOMKilled
   - Increase `resources.limits.memory`
   - Large packages (ML/DL) need 2Gi+

### Slow Installation

**Symptom**: Init container takes >5 minutes

**Solutions:**

1. **Pin versions**: Avoid resolving latest versions
   ```yaml
   packages:
     - pandas==2.1.0  # Fast
     - pandas          # Slow (resolves latest)
   ```

2. **Increase resources**: More CPU/memory speeds up compilation
   ```yaml
   resources:
     limits:
       cpu: "2000m"
       memory: "2Gi"
   ```

3. **Use binary packages**: Avoid compilation
   ```yaml
   packages:
     - psycopg2-binary  # Pre-compiled
     # vs psycopg2      # Compiles from source
   ```

4. **Use package mirrors**: Closer to cluster
   ```yaml
   indexUrl: "https://pypi-mirror.local/simple"
   ```

### Cache Not Working

**Symptom**: Every pod reinstalls packages

**Diagnosis:**

```bash
# Check PVC exists
kubectl get pvc -l kaspr.io/app=my-app

# Check PVC status
kubectl get pvc my-app-packages -o wide

# Check marker files
kubectl exec my-app-0 -- ls -la /opt/kaspr/packages/.installed-*
```

**Common causes:**

1. **RWX not supported**: Storage class doesn't support ReadWriteMany
   - Check storage class supports RWX: `kubectl describe storageclass <name>`
   - Deploy a storage class that supports RWX (NFS, AWS EFS, Azure Files, GCP Filestore)
   - Or disable shared cache and use emptyDir mode (per-pod installation)

2. **Hash mismatch**: Package spec changed
   - Normal behavior - packages updated
   - Check `status.pythonPackages.hash` vs PACKAGES_HASH env var

3. **PVC deleted**: Cache cleared
   - Check PVC exists: `kubectl get pvc`
   - Verify `deleteClaim: false` if persistence needed

### Status Shows "Unable to read installation details"

**Symptom**: Status shows warning about missing pod/exec permission

**Example:**
```yaml
status:
  pythonPackages:
    hash: 8fdf94a2247dc4a6
    warnings:
      - "Unable to read installation details (missing pod/exec permission)"
```

**Cause:** The operator's service account lacks `pods/exec` permission in the namespace.

**Impact:** 
- ✅ Package installation **still works correctly**
- ✅ Condition status **correctly shows** `PackagesInstalled` 
- ❌ Detailed metadata **not available** (installed packages list, duration, etc.)

**Solution:**

Grant the operator `pods/exec` permission. For cluster-scoped operator:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: kaspr-operator
rules:
  - apiGroups: [""]
    resources: ["pods/exec"]
    verbs: ["create"]
  # ... other rules
```

For namespace-scoped operator:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: kaspr-operator
  namespace: my-namespace
rules:
  - apiGroups: [""]
    resources: ["pods/exec"]
    verbs: ["create"]
  # ... other rules
```

Apply the updated RBAC and restart the operator:

```bash
kubectl apply -f rbac.yaml
kubectl rollout restart -n kaspr-operator deployment/kaspr-operator
```

**Note**: If granting `pods/exec` is not possible in your environment (security policy), the feature will continue to work with this graceful degradation. The operator only reads the marker file (non-intrusive, read-only data).

### Pods Won't Start
   - Or accept RWO and slower scaling

2. **Hash mismatch**: Package spec changed
   - Normal behavior - packages updated
   - Check `status.pythonPackages.hash` vs PACKAGES_HASH env var

3. **PVC deleted**: Cache cleared
   - Check PVC exists: `kubectl get pvc`
   - Verify `deleteClaim: false` if persistence needed

### Pods Won't Start

**Symptom**: Pods stuck in Init:0/1

**Diagnosis:**

```bash
# Check pod status
kubectl get pod my-app-0

# Check init container status
kubectl get pod my-app-0 -o jsonpath='{.status.initContainerStatuses[0]}'

# Check logs
kubectl logs my-app-0 -c install-packages
```

**Solutions:**

1. **Installation failed**: Check logs and fix package issues
2. **Timeout**: Increase `installPolicy.timeout`
3. **onFailure: block**: Change to `warn` for non-critical packages

### Package Not Found at Runtime

**Symptom**: `ImportError: No module named 'package'`

**Diagnosis:**

```bash
# Check PYTHONPATH
kubectl exec my-app-0 -- env | grep PYTHONPATH

# List installed packages
kubectl exec my-app-0 -- ls -la /opt/kaspr/packages/site-packages

# Try importing
kubectl exec my-app-0 -- python -c "import sys; print(sys.path)"
```

**Solutions:**

1. **Verify installation**: Check status shows `Ready`
2. **Check marker file**: Ensure init container completed
3. **Restart pod**: Sometimes cache gets corrupted
   ```bash
   kubectl delete pod my-app-0
   ```

## Best Practices

### 1. Always Pin Versions

✅ **Good:**
```yaml
packages:
  - requests==2.31.0
  - pandas==2.1.0
```

❌ **Bad:**
```yaml
packages:
  - requests
  - pandas
```

**Why:** Reproducible builds, faster resolution, predictable behavior

### 2. Use Appropriate Cache Sizes

Choose size based on total package footprint:

| Package Type | Approximate Size | Recommended Cache |
|--------------|-----------------|-------------------|
| Lightweight (requests, redis) | 10-50 MB | 256Mi-512Mi |
| Medium (pandas, numpy) | 100-300 MB | 1Gi-2Gi |
| Heavy (ML/DL frameworks) | 1-5 GB | 5Gi-10Gi |

### 3. Set Resource Limits

Prevent noisy neighbor issues:

```yaml
resources:
  requests:
    memory: "512Mi"    # Guaranteed
  limits:
    memory: "1Gi"      # Maximum
```

### 4. Monitor Installation Time

Track metrics to identify issues:

- First install should be 1-5 minutes (typical)
- Cached installs should be <5 seconds
- >10 minutes indicates problem

### 5. Use Binary Packages When Available

Faster installation, no compilation:

```yaml
packages:
  - psycopg2-binary  # ✅ Pre-compiled
  - orjson           # ✅ Wheels available
  # vs
  - psycopg2         # ❌ Compiles from source
```

### 6. Group Related Packages

Organize by function for maintainability:

```yaml
pythonPackages:
  packages:
    # Data processing
    - pandas==2.1.0
    - numpy==1.24.0
    
    # API clients
    - requests==2.31.0
    - httpx==0.24.0
    
    # Database
    - psycopg2-binary==2.9.0
    - redis==5.0.0
```

### 7. Test Package Changes

Test in dev before production:

1. Apply to dev cluster
2. Verify successful installation
3. Test application functionality
4. Monitor metrics
5. Promote to production

### 8. Handle Private Packages Securely

Use Kubernetes secrets for credentials:

```yaml
# Store credentials in secret
apiVersion: v1
kind: Secret
metadata:
  name: pypi-credentials
type: Opaque
stringData:
  pip.conf: |
    [global]
    index-url = https://user:pass@private-pypi.com/simple
```

Mount in pod template:

```yaml
spec:
  template:
    kasprContainer:
      volumeMounts:
        - name: pip-config
          mountPath: /root/.pip
    volumes:
      - name: pip-config
        secret:
          secretName: pypi-credentials
```

## Migration Guide

### From Image-based to Package Management

**Before** (packages in Dockerfile):

```dockerfile
FROM kaspr:latest
RUN pip install requests pandas numpy
```

**After** (packages in spec):

```yaml
apiVersion: kaspr.io/v1alpha1
kind: KasprApp
metadata:
  name: my-app
spec:
  image: kaspr:latest  # No packages in image
  pythonPackages:
    packages:
      - requests
      - pandas
      - numpy
```

**Benefits:**
- No image rebuilds for package changes
- Faster iterations (seconds vs minutes)
- Shared cache across replicas
- Centralized package management

## FAQ

### Q: Can I use this with custom Docker images?

**A:** Yes! Packages are installed in addition to image packages. Set PYTHONPATH to prioritize:

```yaml
template:
  kasprContainer:
    env:
      - name: PYTHONPATH
        value: "/opt/kaspr/packages/site-packages:/usr/local/lib/python3.9/site-packages"
```

### Q: What if ReadWriteMany is not available?

**A:** If your cluster does not support ReadWriteMany storage, you have two options:

1. **Disable shared cache** (emptyDir mode): Each pod installs packages independently. Slower startup but no shared storage required.
   ```yaml
   pythonPackages:
     cache:
       enabled: false  # Uses emptyDir, per-pod installation
   ```

2. **Use a storage class that supports RWX**: Deploy an NFS provisioner, AWS EFS CSI driver, Azure Files, or GCP Filestore depending on your platform.

### Q: Can I disable the cache?

**A:** Yes, but not recommended:

```yaml
cache:
  enabled: false
```

Packages will be installed to emptyDir (lost on pod restart).

### Q: How do I use private PyPI repositories?

**A:** Configure `indexUrl` and `trustedHosts`:

```yaml
pythonPackages:
  indexUrl: "https://private-pypi.com/simple"
  trustedHosts:
    - "private-pypi.com"
```

### Q: Can I mix Python 2 and Python 3 packages?

**A:** No, operator uses Python version from Kaspr image. Use Python 3 packages only.

### Q: Why does status show "Unable to read installation details (missing pod/exec permission)"?

**A:** The operator needs `pods/exec` permission to read installation metadata from pods. This is optional - the condition status will still correctly report `PackagesInstalled` based on the init container exit code, but detailed information (installed packages list, install duration, etc.) won't be available.

To grant the permission, update the operator's ClusterRole:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: kaspr-operator
rules:
  - apiGroups: [""]
    resources: ["pods/exec"]
    verbs: ["create"]
```

**Note**: The operator only uses `pods/exec` to read the marker file (non-intrusive, read-only operation). If you cannot grant this permission, the feature will work with limited status metadata.

### Q: What happens if installation fails?

**A:** Depends on `onFailure`:
- `block`: Pod won't start, init container shows error
- `warn`: Pod starts, check logs for warning

### Q: How do I rollback a bad package update?

**A:** Restore previous spec version:

```bash
kubectl apply -f my-app-v1.yaml  # Previous working version
kubectl rollout status statefulset my-app
```

### Q: Can I install from git repositories?

**A:** Yes, use pip git+ syntax:

```yaml
packages:
  - git+https://github.com/user/repo.git@v1.0.0
```

### Q: How much overhead does this add?

**A:**
- First pod: 1-5 minutes (one-time install)
- Subsequent pods: <5 seconds (cache hit)
- Storage: Size of installed packages + ~10% overhead
