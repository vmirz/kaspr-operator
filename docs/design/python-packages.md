# Python Package Management Design

## Overview

This document describes the design for declarative Python package management in Kaspr applications, eliminating the need for users to build and maintain custom Docker images just to include additional Python dependencies.

## Problem Statement

### Current State

Users who need custom Python packages (e.g., `requests`, `pandas`, `sqlalchemy`) in their Kaspr agents/webviews/tasks must:

1. Create a custom Dockerfile based on Kaspr base image
2. Add pip install commands for required packages
3. Build and push the image to a container registry
4. Configure KasprApp with the custom image
5. Repeat steps 1-4 whenever Kaspr releases a new version

### Pain Points

- **Complexity**: Requires Docker knowledge, registry access, CI/CD setup
- **Registry friction**: External registries require authentication, cost, network access
- **Version coupling**: Custom images tightly coupled to Kaspr versions - every upgrade requires rebuild
- **No drift protection**: Users may run mismatched Kaspr/package versions
- **Operational overhead**: Simple "add a Python package" becomes multi-step DevOps workflow

### Goals

1. **Declarative UX**: Specify packages in KasprApp spec, operator handles the rest
2. **Version-agnostic**: Works with any Kaspr version without custom images
3. **Fast startups**: Avoid repetitive downloads on restarts or unrelated rollouts
4. **Reliable**: Handle race conditions, failures, and edge cases gracefully
5. **Observable**: Clear status reporting and metrics

## Solution Design

### Architecture: Init Container + Shared PVC

The solution uses a combination of:
- **Shared ReadWriteMany PVC**: Persistent storage for installed packages
- **Init container**: Installs packages with flock-based locking
- **Hash-based idempotency**: Avoids redundant installations
- **Main container**: Reads packages via PYTHONPATH

### Component Overview

```
┌─────────────────────────────────────────────────────────────┐
│                        KasprApp Spec                         │
│  pythonPackages:                                            │
│    packages:                                                │
│      - requests==2.31.0                                     │
│      - pandas>=2.0.0                                        │
├─────────────────────────────────────────────────────────────┤
│                    Operator Actions                          │
│  1. Compute hash of package spec                           │
│  2. Create/manage shared PVC (RWX)                          │
│  3. Generate init container with install script             │
│  4. Inject hash into init container env                     │
│  5. Update StatefulSet                                      │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                      StatefulSet                             │
│                                                              │
│  volumes:                                                    │
│    - name: python-packages                                  │
│      persistentVolumeClaim:                                 │
│        claimName: <app>-python-packages                     │
│                                                              │
│  initContainers:                                            │
│    - name: install-packages                                 │
│      volumeMounts:                                          │
│        - name: python-packages                              │
│          mountPath: /packages                               │
│      command: ["/bin/sh", "-c"]                            │
│      args:                                                  │
│        - |                                                  │
│          # Check hash marker                               │
│          # If exists: skip (instant startup)               │
│          # If missing: acquire flock, install, mark        │
│                                                              │
│  containers:                                                │
│    - name: kaspr                                            │
│      env:                                                   │
│        - name: PYTHONPATH                                   │
│          value: "/packages"                                 │
│      volumeMounts:                                          │
│        - name: python-packages                              │
│          mountPath: /packages                               │
│          readOnly: true                                     │
└─────────────────────────────────────────────────────────────┘
```

### Hash-Based Idempotency

**Package hash computation:**
```python
def compute_packages_hash(packages_spec):
    """Compute deterministic hash of package requirements."""
    components = {
        'packages': sorted(packages_spec.get('packages', [])),
        'indexUrl': packages_spec.get('indexUrl'),
        'extraIndexUrls': sorted(packages_spec.get('extraIndexUrls', [])),
    }
    canonical = json.dumps(components, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]
```

**Marker file pattern:**
- Packages installed: `/packages/.installed-{hash}`
- Hash changes only when packages change
- Init container checks for marker → skip if exists

### Race Condition Handling: flock-based Locking

**Problem:** Multiple pods starting simultaneously with empty PVC

**Solution:** File-based advisory lock using flock

```bash
# Init container script (simplified)
REQUIRED_HASH="abc123def456"
INSTALL_MARKER="/packages/.installed-${REQUIRED_HASH}"
LOCK_FILE="/packages/.install.lock"

# Fast path: already installed
if [ -f "$INSTALL_MARKER" ]; then
  echo "Packages already installed"
  exit 0
fi

# Acquire lock (blocks until available)
exec 200>"$LOCK_FILE"
flock 200

# Double-check inside lock (another pod may have installed)
if [ -f "$INSTALL_MARKER" ]; then
  echo "Installed by another pod while waiting"
  flock -u 200
  exit 0
fi

# Install packages
pip install --target=/packages --no-cache-dir \
  requests==2.31.0 pandas>=2.0.0 sqlalchemy

# Create marker atomically
echo "installed" > "$INSTALL_MARKER"

# Release lock
flock -u 200
rm -f "$LOCK_FILE"
```

**Race scenario resolution:**
```
Time    Pod-0                    Pod-1                    Pod-2
───────────────────────────────────────────────────────────────
T0      Check marker: MISSING    Check marker: MISSING    Check marker: MISSING
T1      Acquire lock: SUCCESS ✅ Acquire lock: WAIT       Acquire lock: WAIT
T2-45   pip install...           (waiting)                (waiting)
T46     Create marker            (waiting)                (waiting)
T47     Release lock             Check marker: FOUND ✅   (waiting)
T48     Start main container     Skip install             Check marker: FOUND ✅
T49                              Start main container     Skip install
T50                                                       Start main container
```

### Lifecycle Scenarios

#### Scenario 1: First Deployment (3 replicas)
```
Pod-0: pip install (30-60s) → marker created
Pod-1: marker found → skip (< 1s)
Pod-2: marker found → skip (< 1s)

Total: ~30-60s (only first pod installs)
```

#### Scenario 2: Pod Restart (Crash/Eviction)
```
Pod-X restart: marker found → skip (< 1s)

Total: < 1s (no install needed)
```

#### Scenario 3: Scale Up (3 → 6 replicas)
```
Pod-3,4,5: marker found → skip (< 1s each)

Total: < 1s per pod (no installs)
```

#### Scenario 4: Unrelated Rollout (Image/Config Change)
```
All pods restart (rolling):
Each pod: marker found → skip (< 1s)

Total: < 1s per pod (no installs)
```

#### Scenario 5: Package Change
```
User updates packages → operator computes new hash → StatefulSet updated

Pod-0: new hash, marker missing → pip install (30-60s) → new marker
Pod-1,2: new marker found → skip (< 1s)

Total: ~30-60s (only first pod installs new packages)
```

## API Design

### KasprApp Spec

```yaml
apiVersion: kaspr.io/v1alpha1
kind: KasprApp
metadata:
  name: my-app
  namespace: default
spec:
  replicas: 3
  bootstrapServers: kafka:9092
  authentication: { ... }
  
  # Python package management (NEW)
  pythonPackages:
    # Simple list of packages (pip install format)
    packages:
      - requests==2.31.0
      - pandas>=2.0.0,<3.0.0
      - sqlalchemy
      - psycopg2-binary
    
    # Optional: Custom PyPI index
    indexUrl: https://pypi.org/simple
    
    # Optional: Additional indexes (private PyPI, etc.)
    extraIndexUrls:
      - https://my-pypi.company.com/simple
    
    # Optional: Trusted hosts for SSL
    trustedHosts:
      - my-pypi.company.com
    
    # Optional: Authentication for private indexes
    credentials:
      secretRef:
        name: pypi-credentials
        usernameKey: username
        passwordKey: password
    
    # Optional: Cache configuration
    cache:
      enabled: true  # Default: true
      storageClass: fast-nfs  # Default: default storage class
      size: 5Gi  # Default: 5Gi
      accessMode: ReadWriteMany  # Default: ReadWriteMany (only supported mode)
      deleteClaim: true  # Default: true (delete PVC with KasprApp)
    
    # Optional: Installation policy
    installPolicy:
      retries: 3  # Default: 3
      timeout: 600  # Default: 600 (10 minutes)
      onFailure: block  # block | allow (Default: block)
    
    # Optional: Init container resource limits
    resources:
      requests:
        memory: 512Mi
        cpu: 250m
      limits:
        memory: 2Gi
        cpu: 1000m
```

### KasprApp Status

```yaml
status:
  # ... existing status fields ...
  
  pythonPackages:
    # Current state
    state: Ready  # Installing | Ready | Failed
    
    # Hash of current package spec
    hash: abc123def456
    
    # Installed packages (resolved versions)
    installed:
      - requests==2.31.0
      - pandas==2.1.0
      - sqlalchemy==2.0.23
      - psycopg2-binary==2.9.9
    
    # Cache mode
    cacheMode: ReadWriteMany  # ReadWriteMany | emptyDir
    
    # Installation metadata
    lastInstallTime: "2025-11-26T10:30:00Z"
    installDuration: 45s
    installedBy: my-app-0  # Which pod performed the install
    
    # Error information (if failed)
    error: "Failed to install pandas: network timeout"
    
    # Warnings
    warnings:
      - "Package 'requests' not pinned to specific version (security risk)"
```

### CRD Schema Updates

```yaml
# In crds/kasprapp.crd.yaml
spec:
  properties:
    pythonPackages:
      type: object
      description: Python package management configuration
      properties:
        packages:
          type: array
          items:
            type: string
            description: Package specification in pip format (e.g., requests==2.31.0)
          description: List of Python packages to install
        indexUrl:
          type: string
          description: Base URL of Python Package Index
        extraIndexUrls:
          type: array
          items:
            type: string
          description: Extra URLs of package indexes
        trustedHosts:
          type: array
          items:
            type: string
          description: Hosts to trust for SSL
        credentials:
          type: object
          properties:
            secretRef:
              type: object
              properties:
                name:
                  type: string
                usernameKey:
                  type: string
                passwordKey:
                  type: string
        cache:
          type: object
          properties:
            enabled:
              type: boolean
              default: true
            storageClass:
              type: string
            size:
              type: string
              default: 5Gi
            accessMode:
              type: string
              default: ReadWriteMany
              enum: [ReadWriteMany]
              description: Only ReadWriteMany is currently supported
            deleteClaim:
              type: boolean
              default: true
        installPolicy:
          type: object
          properties:
            retries:
              type: integer
              default: 3
              minimum: 1
            timeout:
              type: integer
              default: 600
              minimum: 60
            onFailure:
              type: string
              default: block
              enum: [block, allow]
        resources:
          type: object
          properties:
            requests:
              type: object
            limits:
              type: object
```

## Implementation Plan

### Phase 1: MVP (Core Functionality)

**Scope:**
1. ✅ Basic package installation (packages list only)
2. ✅ Hash-based change detection
3. ✅ Shared PVC creation and lifecycle
4. ✅ Init container generation with flock-based locking
5. ✅ Basic status reporting (state, installed packages, errors)
6. ✅ Prometheus metrics (install duration, success/failure)
7. ✅ Validation (package format, non-empty lists)
8. ✅ Init container resource limits (reasonable defaults)

**Files to Create/Modify:**

**CRD Update:**
- `crds/kasprapp.crd.yaml` - Add pythonPackages spec and status fields

**Models & Schemas:**
- `kaspr/types/models/python_packages.py` - New model classes
- `kaspr/types/schemas/python_packages.py` - Marshmallow validation

**Resource Generation:**
- `kaspr/resources/kasprapp.py` - Modify to:
  - Generate PVC for packages
  - Generate init container with install script
  - Update StatefulSet with volume mounts and PYTHONPATH

**Handler Updates:**
- `kaspr/handlers/kasprapp.py` - Add:
  - Field watcher for `spec.pythonPackages`
  - Status update logic for pythonPackages
  - Hash computation and change detection

**Utilities:**
- `kaspr/utils/python_packages.py` - Helper functions:
  - `compute_packages_hash()`
  - `generate_install_script()`
  - `validate_package_spec()`

**Metrics:**
- `kaspr/sensors/prometheus.py` - Add metrics:
  - `kasprop_package_install_duration_seconds`
  - `kasprop_package_install_total`
  - `kasprop_package_install_errors_total`

**Tests:**
- `tests/unit/test_python_packages.py` - Unit tests
- `tests/integration/test_python_packages.py` - Integration tests

### Phase 2: Post-MVP (Production Hardening)

**Scope:**
1. Private registry authentication (credentials.secretRef)
2. Custom PyPI indexes (indexUrl, extraIndexUrls)
3. Configurable install policy (retries, timeout, onFailure)
4. PVC usage monitoring and warnings
5. Compatibility handling with existing `image` field
6. Enhanced status reporting (installDuration, installedBy)
7. Stale lock detection and cleanup

**Estimated Timeline:** 2-3 weeks after MVP

### Phase 3: Future Enhancements

**Scope:**
1. Package hash verification for supply chain security
2. Air-gapped environment support (pre-cached packages)

**Estimated Timeline:** 3-6 months after MVP

## Testing Strategy

### Unit Tests

```python
# test_python_packages.py

def test_compute_packages_hash():
    """Test hash computation is deterministic."""
    spec1 = {'packages': ['requests==2.31.0', 'pandas>=2.0.0']}
    spec2 = {'packages': ['pandas>=2.0.0', 'requests==2.31.0']}  # Different order
    
    hash1 = compute_packages_hash(spec1)
    hash2 = compute_packages_hash(spec2)
    
    assert hash1 == hash2  # Order-independent

def test_validate_package_spec():
    """Test package spec validation."""
    # Valid
    assert validate_package_spec(['requests==2.31.0'])
    
    # Invalid format
    with pytest.raises(ValidationError):
        validate_package_spec(['invalid package name!'])

def test_generate_install_script():
    """Test install script generation."""
    spec = {
        'packages': ['requests==2.31.0'],
        'indexUrl': 'https://pypi.org/simple'
    }
    script = generate_install_script(spec, hash='abc123')
    
    assert 'pip install' in script
    assert 'requests==2.31.0' in script
    assert 'flock' in script
```

### Integration Tests

```python
# test_python_packages_integration.py

@pytest.mark.integration
async def test_package_installation_lifecycle():
    """Test full package installation lifecycle."""
    # 1. Create KasprApp with packages
    app = await create_kasprapp_with_packages([
        'requests==2.31.0'
    ])
    
    # 2. Wait for PVC creation
    pvc = await wait_for_pvc(app.name)
    assert pvc is not None
    
    # 3. Wait for pods ready
    pods = await wait_for_pods_ready(app.name, replicas=3)
    
    # 4. Verify packages installed
    for pod in pods:
        result = await exec_in_pod(pod, 'python -c "import requests; print(requests.__version__)"')
        assert '2.31.0' in result
    
    # 5. Update packages
    await update_packages(app.name, ['requests==2.32.0'])
    
    # 6. Wait for rollout
    await wait_for_rollout_complete(app.name)
    
    # 7. Verify new version
    pods = await get_pods(app.name)
    for pod in pods:
        result = await exec_in_pod(pod, 'python -c "import requests; print(requests.__version__)"')
        assert '2.32.0' in result

@pytest.mark.integration
async def test_race_condition_handling():
    """Test multiple pods starting simultaneously."""
    # 1. Create KasprApp with 10 replicas (stress test)
    app = await create_kasprapp_with_packages(
        packages=['pandas>=2.0.0'],
        replicas=10
    )
    
    # 2. Wait for all pods ready
    pods = await wait_for_pods_ready(app.name, replicas=10, timeout=300)
    
    # 3. Verify only one pod performed install (check logs)
    install_logs = []
    for pod in pods:
        logs = await get_init_container_logs(pod)
        if 'Installing packages' in logs:
            install_logs.append(pod)
    
    # Should be exactly 1 (or very few if race happened)
    assert len(install_logs) <= 2, f"Expected 1-2 installers, got {len(install_logs)}"
    
    # 4. Verify all pods have packages
    for pod in pods:
        result = await exec_in_pod(pod, 'python -c "import pandas"')
        assert result.returncode == 0
```

### Manual Testing Checklist

- [ ] Package installation on fresh deployment
- [ ] Package updates trigger rollout
- [ ] Pod restarts skip installation
- [ ] Scale up reuses packages
- [ ] Race condition handling (10+ replicas)
- [ ] Failed installation blocks pod startup
- [ ] PVC deleted when KasprApp deleted
- [ ] Status accurately reflects installation state
- [ ] Metrics exposed correctly
- [ ] Works with/without RWX storage
- [ ] Works with private PyPI (auth)

## Rollout Strategy

### Development
1. Feature branch: `feature/python-packages`
2. Unit tests passing
3. Integration tests in dev cluster
4. Manual testing with examples

### Staging
1. Deploy to staging cluster
2. Test with real workloads
3. Performance testing (large packages, many pods)
4. Soak test (24h+ stability)

### Production
1. Feature flag: `PYTHON_PACKAGES_ENABLED=true` (default: false)
2. Beta release with documentation
3. Gather user feedback
4. GA release (default: true)

## Monitoring & Observability

### Prometheus Metrics

```python
# Install metrics
kasprop_package_install_duration_seconds{app_name, namespace, result}
kasprop_package_install_total{app_name, namespace, result}
kasprop_package_install_errors_total{app_name, namespace, error_type}

# Cache metrics
kasprop_package_cache_hits_total{app_name, namespace}
kasprop_package_cache_misses_total{app_name, namespace}
kasprop_package_cache_size_bytes{app_name, namespace}

# Lifecycle metrics
kasprop_package_pvc_created_total{app_name, namespace}
kasprop_package_pvc_deleted_total{app_name, namespace}
```

### Grafana Dashboard

**Panels:**
1. Package installation duration (p50, p95, p99)
2. Installation success rate
3. Cache hit rate
4. PVC usage
5. Error rate by type
6. Recent installations (table)

### Logging

```python
# Structured logging in operator
logger.info(
    "Installing Python packages",
    extra={
        'app_name': app.name,
        'namespace': app.namespace,
        'packages': packages,
        'hash': pkg_hash,
        'action': 'package_install'
    }
)
```

## Security Considerations

### Supply Chain Security

**Current (MVP):**
- Packages downloaded from public PyPI by default
- No integrity verification
- Risk: Compromised packages

**Future Enhancements:**
1. **Hash verification**: Support `--require-hashes` in pip
   ```yaml
   packages:
     - name: requests
       version: "2.31.0"
       hash: "sha256:942c5a758f98..."
   ```

2. **Signature verification**: Validate package signatures

3. **Private mirrors**: Encourage private PyPI mirrors for production

### Network Security

**Considerations:**
- Init container needs internet access (or private PyPI)
- Consider NetworkPolicy restrictions
- Document firewall requirements

### RBAC

**Operator needs permissions:**
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: kaspr-operator
rules:
  # ... existing rules ...
  - apiGroups: [""]
    resources: ["persistentvolumeclaims"]
    verbs: ["create", "get", "list", "update", "delete"]
  - apiGroups: [""]
    resources: ["secrets"]
    verbs: ["get"]  # For PyPI credentials
```

## Documentation Requirements

### User Guide

**Topics:**
1. Getting started with pythonPackages
2. Pinning package versions (best practices)
3. Using private PyPI registries
4. Troubleshooting installation failures
5. Migration from custom images
6. Performance tuning (cache configuration)

### Examples

```yaml
# examples/python-packages/basic.yaml
# examples/python-packages/private-registry.yaml
# examples/python-packages/large-packages.yaml
```

### API Reference

- pythonPackages field documentation
- Status fields documentation
- Annotation references

## Migration Guide

### From Custom Images to pythonPackages

**Before:**
```yaml
spec:
  image: myregistry.io/my-kaspr:v1.2.3-custom
```

**After:**
```yaml
spec:
  # Remove image field (or leave it blank to use default)
  pythonPackages:
    packages:
      - requests==2.31.0
      - pandas>=2.0.0
```

**Migration Steps:**
1. Identify packages in your custom Dockerfile
2. Add pythonPackages section to KasprApp spec
3. Remove custom image field
4. Apply changes (triggers rollout)
5. Verify packages installed correctly
6. Decommission custom image pipeline

## Open Questions & Future Considerations

### 1. Compatibility with `image` Field

**Question:** What if user specifies both `image` and `pythonPackages`?

**Options:**
- **A**: Error (mutually exclusive)
- **B**: Warning - image takes precedence, ignore pythonPackages
- **C**: Merge - use custom image AND install additional packages

**Recommendation:** Option B (warning) for backward compatibility

### 2. Package Size Limits

**Question:** Should we enforce maximum package size or PVC size?

**Consideration:**
- Large ML packages (tensorflow, torch) can be 500MB-1GB+
- Default 5Gi PVC should handle most cases
- Add warnings in status if PVC >80% full

### 3. Python Version Compatibility

**Question:** How to handle packages that require different Python versions?

**Current:** Assume packages compatible with Kaspr base image Python version

**Future:** Add validation warning if package metadata indicates incompatibility

### 4. Offline/Air-Gapped Environments

**Question:** How to support environments without PyPI access?

**Options:**
- Pre-populated PVC (manual)
- Bundle packages in custom image (defeats purpose)
- Private PyPI mirror (recommended)

**Future:** Support pre-cached package bundles

### 5. Package Conflicts

**Question:** How to handle conflicting package dependencies?

**Current:** pip resolver handles it (may fail)

**Future:** 
- Pre-validation with pip-tools or poetry
- Suggest compatible versions in error messages

## Success Criteria

### MVP Success Metrics

- [ ] 90%+ of custom image use cases eliminated
- [ ] <5s pod startup time (with cache hit)
- [ ] <60s first pod startup (cache miss, typical packages)
- [ ] Zero race condition incidents in testing
- [ ] 100% test coverage for core logic
- [ ] Positive user feedback from beta testing

### Long-Term Success Metrics

- [ ] 50%+ reduction in support tickets related to custom images
- [ ] 80%+ of KasprApps use pythonPackages instead of custom images
- [ ] <1% installation failure rate
- [ ] Sublinear scaling of support burden as adoption grows

## Appendix

### A. Complete Init Container Script

```bash
#!/bin/sh
set -e

# Configuration
REQUIRED_HASH="${PACKAGE_HASH}"
PACKAGES_DIR="/packages"
INSTALL_MARKER="${PACKAGES_DIR}/.installed-${REQUIRED_HASH}"
LOCK_FILE="${PACKAGES_DIR}/.install.lock"
MAX_LOCK_WAIT=300  # 5 minutes
INSTALL_TIMEOUT=600  # 10 minutes
MAX_RETRIES=3

echo "=== Python Package Installer ==="
echo "Hash: ${REQUIRED_HASH}"
echo "Packages: ${PACKAGES}"

# Fast path: packages already installed
if [ -f "$INSTALL_MARKER" ]; then
  echo "✓ Packages already installed (hash: ${REQUIRED_HASH})"
  cat "$INSTALL_MARKER"
  exit 0
fi

echo "× Packages not found, installation required"

# Function to acquire lock with timeout
acquire_lock() {
  echo "→ Attempting to acquire installation lock..."
  local elapsed=0
  local interval=2
  
  # Open lock file for flock
  exec 200>"$LOCK_FILE"
  
  while [ $elapsed -lt $MAX_LOCK_WAIT ]; do
    if flock -n 200; then
      echo "✓ Lock acquired by $(hostname)"
      return 0
    fi
    
    echo "  Waiting for lock... (${elapsed}s elapsed)"
    sleep $interval
    elapsed=$((elapsed + interval))
  done
  
  echo "✗ Failed to acquire lock after ${MAX_LOCK_WAIT}s"
  return 1
}

# Function to check for stale locks
check_stale_lock() {
  if [ -f "$LOCK_FILE" ]; then
    local lock_age=$(($(date +%s) - $(stat -f %m "$LOCK_FILE" 2>/dev/null || echo 0)))
    if [ $lock_age -gt 600 ]; then
      echo "⚠ Stale lock detected (${lock_age}s old), removing..."
      rm -f "$LOCK_FILE"
    fi
  fi
}

# Function to install packages with retry
install_packages() {
  local retry=0
  
  while [ $retry -lt $MAX_RETRIES ]; do
    echo "→ Installing packages (attempt $((retry + 1))/${MAX_RETRIES})..."
    
    if timeout $INSTALL_TIMEOUT pip install \
         --target="${PACKAGES_DIR}" \
         --no-cache-dir \
         ${INDEX_URL:+--index-url "$INDEX_URL"} \
         ${EXTRA_INDEX_URLS:+--extra-index-url "$EXTRA_INDEX_URLS"} \
         ${TRUSTED_HOSTS:+--trusted-host "$TRUSTED_HOSTS"} \
         $PACKAGES; then
      echo "✓ Installation successful"
      return 0
    fi
    
    echo "✗ Installation failed (attempt $((retry + 1))/${MAX_RETRIES})"
    retry=$((retry + 1))
    [ $retry -lt $MAX_RETRIES ] && sleep 5
  done
  
  echo "✗ Installation failed after ${MAX_RETRIES} attempts"
  return 1
}

# Main installation logic
check_stale_lock

if ! acquire_lock; then
  echo "✗ Could not acquire lock"
  exit 1
fi

# Double-check inside lock (another pod may have installed)
if [ -f "$INSTALL_MARKER" ]; then
  echo "✓ Packages were installed by another pod while waiting"
  flock -u 200
  exit 0
fi

# Clean up any partial installs
if [ -d "$PACKAGES_DIR" ] && [ ! -f "$INSTALL_MARKER" ]; then
  echo "⚠ Partial install detected, cleaning up..."
  find "$PACKAGES_DIR" -type f \( -name "*.py" -o -name "*.pyc" -o -name "*.so" \) -delete
fi

# Install packages
START_TIME=$(date +%s)
if ! install_packages; then
  flock -u 200
  rm -f "$LOCK_FILE"
  exit 1
fi
END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

# Create marker file
cat > "$INSTALL_MARKER" <<EOF
packages: $PACKAGES
hash: $REQUIRED_HASH
installed_by: $(hostname)
installed_at: $(date -u +"%Y-%m-%dT%H:%M:%SZ")
duration: ${DURATION}s
EOF

echo "✓ Marker file created"

# Cleanup old markers
OLD_MARKERS=$(find "$PACKAGES_DIR" -name ".installed-*" -not -name ".installed-${REQUIRED_HASH}")
if [ -n "$OLD_MARKERS" ]; then
  echo "→ Cleaning up old package installations..."
  echo "$OLD_MARKERS" | xargs rm -f
fi

# Release lock
flock -u 200
rm -f "$LOCK_FILE"

echo "=== Installation Complete (${DURATION}s) ==="
cat "$INSTALL_MARKER"
exit 0
```

### B. Storage Class Requirements

**Required Features:**
- Access Mode: ReadWriteMany (RWX) - **MANDATORY**
- Provisioner: Dynamic or static

**Note:** ReadWriteMany is the only supported access mode. The shared package cache requires multiple pods across potentially different nodes to read from the same volume simultaneously. If RWX storage is not available in your cluster, see the user guide for alternative approaches (emptyDir mode).

**Recommended Storage Classes by Platform:**

| Platform | Storage Class | Provisioner |
|----------|---------------|-------------|
| AWS EKS | efs-sc | efs.csi.aws.com |
| GCP GKE | filestore-sc | filestore.csi.storage.gke.io |
| Azure AKS | azurefile-csi | file.csi.azure.com |
| On-Prem | nfs-client | nfs-client-provisioner |
| Minikube | standard | hostpath (dev only) |

**Example Storage Class (AWS EFS):**
```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: efs-sc
provisioner: efs.csi.aws.com
parameters:
  provisioningMode: efs-ap
  fileSystemId: fs-12345678
  directoryPerms: "700"
```

### C. Example Use Cases

**Use Case 1: Data Processing with Pandas**
```yaml
pythonPackages:
  packages:
    - pandas==2.1.0
    - numpy==1.24.0
    - pyarrow==13.0.0
```

**Use Case 2: HTTP Client for External APIs**
```yaml
pythonPackages:
  packages:
    - requests==2.31.0
    - httpx==0.24.1
```

**Use Case 3: Database Connectivity**
```yaml
pythonPackages:
  packages:
    - psycopg2-binary==2.9.9
    - sqlalchemy==2.0.23
```

**Use Case 4: Cloud Provider SDKs**
```yaml
pythonPackages:
  packages:
    - boto3==1.28.0
    - google-cloud-storage==2.10.0
    - azure-storage-blob==12.18.0
```

**Use Case 5: ML/AI Libraries**
```yaml
pythonPackages:
  packages:
    - scikit-learn==1.3.0
    - transformers==4.30.0
  cache:
    size: 10Gi  # ML packages are large
```

---

**Document Version:** 1.0  
**Last Updated:** 2025-11-26  
**Authors:** Viktor Mirzoyan
**Status:** Design Review
