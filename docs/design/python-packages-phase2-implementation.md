# Python Package Management - Phase 2 Implementation Plan

## Overview

This document outlines the step-by-step implementation plan for Phase 2 (Production Hardening) of the Python package management feature. Phase 2 builds on the MVP from Phase 1, adding production-ready features for enterprise use cases.

## Prerequisites

**Phase 1 Completion:**
- ✅ All Phase 1 tasks completed and tested
- ✅ MVP deployed and validated in dev/staging
- ✅ Basic package installation working reliably
- ✅ Hash-based idempotency and flock locking proven stable

## Implementation Approach

- **Incremental**: Each task builds on Phase 1 foundation
- **Production-focused**: Emphasis on security, reliability, observability
- **Enterprise-ready**: Support for private registries and corporate environments
- **Testable**: Comprehensive validation at each step
- **Reviewable**: Small, focused changes for easy review

## Task Breakdown

### Task 1: Add Private Registry Authentication Models ✓

**Objective:** Define data models for PyPI credentials and authentication

**Files to Modify:**
- `kaspr/types/models/python_packages.py`
- `kaspr/types/schemas/python_packages.py`

**What to Implement:**

1. Add `PythonPackagesCredentials` model:
   ```python
   from typing import Optional
   from kaspr.types.base import BaseModel
   
   class PythonPackagesCredentials(BaseModel):
       """PyPI authentication credentials."""
       secret_ref: SecretReference
       username_key: Optional[str]
       password_key: Optional[str]
   ```

2. Add to `PythonPackagesSpec`:
   ```python
   class PythonPackagesSpec(BaseModel):
       # ... existing fields ...
       credentials: Optional[PythonPackagesCredentials]
   ```

3. Update Marshmallow schemas for validation

4. Add default constants in `kaspr/resources/kasprapp.py`:
   ```python
   class KasprApp(BaseResource):
       # ... existing constants ...
       DEFAULT_PYPI_USERNAME_KEY = "username"
       DEFAULT_PYPI_PASSWORD_KEY = "password"
   ```

**Note:** All models inherit from `BaseModel`, NOT `@dataclass`. Do NOT set default values in model classes - defaults are defined as constants in resource classes.

**Validation:**
- [ ] Unit tests for credential model instantiation
- [ ] Schema validation for secretRef structure
- [ ] Validation fails for missing required fields

**Files Changed:**
- Modified: `kaspr/types/models/python_packages.py`
- Modified: `kaspr/types/schemas/python_packages.py`
- Modified: `tests/unit/test_python_packages.py`

---

### Task 2: Add Custom Index URL Models ✓

**Objective:** Support custom PyPI indexes (indexUrl, extraIndexUrls, trustedHosts)

**Files to Modify:**
- `kaspr/types/models/python_packages.py`
- `kaspr/types/schemas/python_packages.py`

**What to Implement:**

1. Add fields to `PythonPackagesSpec`:
   ```python
   from typing import Optional, List
   from kaspr.types.base import BaseModel
   
   class PythonPackagesSpec(BaseModel):
       packages: List[str]
       # NEW fields:
       index_url: Optional[str] = None  # Base PyPI URL
       extra_index_urls: Optional[List[str]] = None  # Additional indexes
       trusted_hosts: Optional[List[str]] = None  # SSL trust
       # ... existing fields ...
   ```
   
   **Note:** Use `Optional[List[str]] = None` instead of `field(default_factory=list)` since we're using `BaseModel`, not `@dataclass`.

2. Add URL validation in schema:
   - Validate URLs are well-formed
   - Check for http/https scheme
   - Validate trusted hosts are hostnames

3. Update hash computation to include these fields:
   ```python
   def compute_packages_hash(packages_spec):
       components = {
           'packages': sorted(packages_spec.get('packages', [])),
           'indexUrl': packages_spec.get('indexUrl'),  # NEW
           'extraIndexUrls': sorted(packages_spec.get('extraIndexUrls', [])),  # NEW
           'trustedHosts': sorted(packages_spec.get('trustedHosts', [])),  # NEW
       }
       # ... existing logic ...
   ```

**Validation:**
- [ ] Unit tests for URL validation (valid/invalid)
- [ ] Hash changes when indexUrl changes
- [ ] Hash changes when extraIndexUrls change
- [ ] Schema rejects malformed URLs

**Files Changed:**
- Modified: `kaspr/types/models/python_packages.py`
- Modified: `kaspr/types/schemas/python_packages.py`
- Modified: `kaspr/utils/python_packages.py` (hash computation)
- Modified: `tests/unit/test_python_packages.py`

---

### Task 3: Update CRD with Phase 2 Fields ✓

**Objective:** Extend KasprApp CRD with authentication and index fields

**Files to Modify:**
- `crds/kasprapp.crd.yaml`

**What to Implement:**

Add to `spec.pythonPackages`:
```yaml
properties:
  pythonPackages:
    properties:
      # ... existing fields (packages, cache, installPolicy, resources) ...
      
      # NEW: Authentication
      credentials:
        type: object
        description: Credentials for private PyPI registry
        properties:
          secretRef:
            type: object
            required: [name]
            properties:
              name:
                type: string
                description: Name of Secret containing credentials
              usernameKey:
                type: string
                default: username
                description: Key in Secret for username
              passwordKey:
                type: string
                default: password
                description: Key in Secret for password
      
      # NEW: Custom indexes
      indexUrl:
        type: string
        description: Base URL of Python Package Index
        pattern: '^https?://.+'
      
      extraIndexUrls:
        type: array
        items:
          type: string
          pattern: '^https?://.+'
        description: Additional package index URLs
      
      trustedHosts:
        type: array
        items:
          type: string
        description: Hosts to trust for SSL verification
```

**Validation:**
- [ ] CRD applies without errors: `kubectl apply -f crds/kasprapp.crd.yaml`
- [ ] Create KasprApp with credentials (validation only)
- [ ] Create KasprApp with custom indexUrl
- [ ] Schema rejects invalid URLs

**Files Changed:**
- Modified: `crds/kasprapp.crd.yaml`

---

### Task 4: Implement Credential Secret Handling ✓

**Objective:** Read credentials from Kubernetes Secrets and inject into init container

**Files to Modify:**
- `kaspr/resources/kasprapp.py`

**What to Implement:**

1. Add method `prepare_python_packages_credentials_env_vars() -> List[V1EnvVar]`:
   ```python
   def prepare_python_packages_credentials_env_vars(self) -> List[V1EnvVar]:
       """Prepare environment variables for PyPI authentication."""
       env_vars = []
       
       if not self.python_packages or not self.python_packages.credentials:
           return env_vars
       
       creds = self.python_packages.credentials
       secret_name = creds.secret_ref.name
       
       # PIP_INDEX_URL with embedded credentials
       # Format: https://username:password@pypi.company.com/simple
       env_vars.append(V1EnvVar(
           name="PYPI_USERNAME",
           value_from=V1EnvVarSource(
               secret_key_ref=V1SecretKeySelector(
                   name=secret_name,
                   key=creds.username_key
               )
           )
       ))
       
       env_vars.append(V1EnvVar(
           name="PYPI_PASSWORD",
           value_from=V1EnvVarSource(
               secret_key_ref=V1SecretKeySelector(
                   name=secret_name,
                   key=creds.password_key
               )
           )
       ))
       
       return env_vars
   ```

2. Update `prepare_python_packages_env_vars()` to include credential env vars

3. Update `generate_install_script()` in utilities to use credentials:
   ```bash
   # In install script:
   if [ -n "$PYPI_USERNAME" ] && [ -n "$PYPI_PASSWORD" ]; then
     # Build authenticated index URL
     INDEX_URL_WITH_AUTH=$(echo "$INDEX_URL" | sed "s|://|://${PYPI_USERNAME}:${PYPI_PASSWORD}@|")
     pip install --index-url "$INDEX_URL_WITH_AUTH" ...
   fi
   ```

**Security Considerations:**
- Credentials never logged or exposed in status
- Use Secret references, not inline values
- Validate Secret exists before pod creation

**Validation:**
- [ ] Init container receives PYPI_USERNAME and PYPI_PASSWORD env vars
- [ ] pip uses authenticated URL correctly
- [ ] Installation succeeds with valid credentials
- [ ] Installation fails gracefully with invalid credentials
- [ ] Credentials not exposed in logs or status

**Files Changed:**
- Modified: `kaspr/resources/kasprapp.py`
- Modified: `kaspr/utils/python_packages.py`
- Modified: `tests/unit/test_python_packages.py`

---

### Task 5: Implement Custom Index URL Support ✓

**Objective:** Support custom PyPI indexes in install script

**Files to Modify:**
- `kaspr/utils/python_packages.py`

**What to Implement:**

Update `generate_install_script()` to include index URL options:

```python
def generate_install_script(spec: dict, hash: str) -> str:
    """Generate init container install script with custom indexes."""
    packages = spec.get('packages', [])
    index_url = spec.get('indexUrl')
    extra_index_urls = spec.get('extraIndexUrls', [])
    trusted_hosts = spec.get('trustedHosts', [])
    
    # Build pip install command
    pip_cmd_parts = ['pip install', '--target=/packages', '--no-cache-dir']
    
    if index_url:
        pip_cmd_parts.append(f'--index-url "$INDEX_URL"')
    
    for extra_url in extra_index_urls:
        pip_cmd_parts.append(f'--extra-index-url "{extra_url}"')
    
    for host in trusted_hosts:
        pip_cmd_parts.append(f'--trusted-host "{host}"')
    
    pip_cmd_parts.extend(packages)
    pip_cmd = ' '.join(pip_cmd_parts)
    
    # ... rest of script generation ...
```

Update env vars passed to init container:
```python
def prepare_python_packages_env_vars(self) -> List[V1EnvVar]:
    env_vars = []
    
    if self.python_packages.index_url:
        env_vars.append(V1EnvVar(
            name="INDEX_URL",
            value=self.python_packages.index_url
        ))
    
    # ... credentials, extra URLs, trusted hosts ...
    
    return env_vars
```

**Validation:**
- [ ] Script includes --index-url when specified
- [ ] Script includes --extra-index-url for each extra URL
- [ ] Script includes --trusted-host for each host
- [ ] Installation works with custom PyPI mirror
- [ ] Installation fails gracefully with unreachable index

**Files Changed:**
- Modified: `kaspr/utils/python_packages.py`
- Modified: `kaspr/resources/kasprapp.py`
- Modified: `tests/unit/test_python_packages.py`

---

### Task 6: Add Install Policy Models and Implementation ✓

**Objective:** Support configurable retries, timeout, and failure behavior

**Files to Modify:**
- `kaspr/types/models/python_packages.py`
- `kaspr/types/schemas/python_packages.py`
- `kaspr/utils/python_packages.py`

**What to Implement:**

1. Add `PythonPackagesInstallPolicy` model (if not already in Phase 1):
   ```python
   from typing import Optional
   from kaspr.types.base import BaseModel
   
   class PythonPackagesInstallPolicy(BaseModel):
       """Installation policy configuration."""
       retries: Optional[int]
       timeout: Optional[int]  # seconds
       on_failure: Optional[str]  # block | allow
   ```
   
   **Note:** Use `BaseModel`, not `@dataclass`. Do NOT set default values in model classes.

2. Add default constants in `kaspr/resources/kasprapp.py`:
   ```python
   class KasprApp(BaseResource):
       # ... existing constants ...
       DEFAULT_INSTALL_RETRIES = 3
       DEFAULT_INSTALL_TIMEOUT = 600  # seconds
       DEFAULT_INSTALL_ON_FAILURE = "block"  # block | allow
   ```

3. Update `generate_install_script()` to use policy:
   ```python
   def generate_install_script(spec: dict, hash: str) -> str:
       policy = spec.get('installPolicy', {})
       max_retries = policy.get('retries', 3)
       timeout = policy.get('timeout', 600)
       
       script = f'''
       MAX_RETRIES={max_retries}
       INSTALL_TIMEOUT={timeout}
       
       # Retry loop
       retry=0
       while [ $retry -lt $MAX_RETRIES ]; do
         if timeout $INSTALL_TIMEOUT pip install ...; then
           break
         fi
         retry=$((retry + 1))
         sleep 5
       done
       '''
       # ... rest of script ...
   ```

4. Handle `onFailure` policy:
   - `block` (default: `self.DEFAULT_INSTALL_ON_FAILURE`): Init container fails → pod doesn't start
   - `allow`: Init container succeeds even if install fails → pod starts with warning in status

**Validation:**
- [ ] Retries configuration affects script correctly
- [ ] Timeout enforced during pip install
- [ ] onFailure=block prevents pod startup on error
- [ ] onFailure=allow allows pod startup with warning

**Files Changed:**
- Modified: `kaspr/types/models/python_packages.py`
- Modified: `kaspr/types/schemas/python_packages.py`
- Modified: `kaspr/utils/python_packages.py`
- Modified: `tests/unit/test_python_packages.py`

---

### Task 7: Add PVC Usage Monitoring ✓

**Objective:** Monitor PVC disk usage and warn when approaching capacity

**Files to Modify:**
- `kaspr/handlers/kasprapp.py`
- `kaspr/sensors/prometheus.py`

**What to Implement:**

1. Add helper function to check PVC usage:
   ```python
   async def get_pvc_usage(app: KasprApp, namespace: str) -> dict:
       """Query PVC disk usage from any pod."""
       pods = await list_pods(app.component_name, namespace)
       if not pods:
           return None
       
       # Exec into first available pod
       pod = pods[0]
       cmd = ['df', '-B1', '/packages']  # Get bytes
       result = await exec_in_pod(pod.metadata.name, namespace, cmd)
       
       # Parse df output
       # Example: /dev/sda1  5368709120  2684354560  2684354560  50% /packages
       lines = result.strip().split('\n')
       if len(lines) < 2:
           return None
       
       parts = lines[1].split()
       return {
           'total_bytes': int(parts[1]),
           'used_bytes': int(parts[2]),
           'available_bytes': int(parts[3]),
           'usage_percent': float(parts[4].rstrip('%'))
       }
   ```

2. Add to status reporting in `fetch_python_packages_status()`:
   ```python
   async def fetch_python_packages_status(app: KasprApp) -> dict:
       # ... existing status logic ...
       
       # Check PVC usage
       usage = await get_pvc_usage(app, app.namespace)
       if usage:
           status['cache_usage'] = usage
           
           # Add warning if >80% full
           if usage['usage_percent'] > 80:
               status['warnings'].append(
                   f"Package cache {usage['usage_percent']:.1f}% full "
                   f"({usage['used_bytes'] / 1024**3:.2f}GB / "
                   f"{usage['total_bytes'] / 1024**3:.2f}GB)"
               )
   ```

3. Add Prometheus metric:
   ```python
   package_cache_usage_bytes = Gauge(
       'kasprop_package_cache_usage_bytes',
       'Disk usage of Python package cache',
       ['app_name', 'namespace', 'type']  # type: total|used|available
   )
   ```

**Validation:**
- [ ] PVC usage queried successfully
- [ ] Status shows cache usage stats
- [ ] Warning added when >80% full
- [ ] Metric exposed correctly
- [ ] Works when pods not yet ready (graceful degradation)

**Files Changed:**
- Modified: `kaspr/handlers/kasprapp.py`
- Modified: `kaspr/sensors/prometheus.py`
- Modified: `tests/unit/test_python_packages.py`

---

### Task 8: Add Enhanced Status Fields ✓

**Objective:** Populate installDuration and installedBy fields in status

**Files to Modify:**
- `kaspr/handlers/kasprapp.py`

**What to Implement:**

1. Update `fetch_python_packages_status()` to read marker file metadata:
   ```python
   async def fetch_python_packages_status(app: KasprApp) -> dict:
       # ... existing logic to find pod and read marker ...
       
       # Parse marker file (from Phase 1):
       # packages: requests==2.31.0 pandas>=2.0.0
       # hash: abc123def456
       # installed_by: my-app-0
       # installed_at: 2025-11-26T10:30:00Z
       # duration: 45s
       
       marker_data = parse_marker_file(marker_content)
       
       return {
           'state': 'Ready',
           'hash': marker_data['hash'],
           'installed': marker_data['packages'].split(),
           'lastInstallTime': marker_data['installed_at'],
           'installDuration': marker_data['duration'],  # NEW
           'installedBy': marker_data['installed_by'],  # NEW
           'cacheMode': 'shared-pvc',
           'warnings': []
       }
   ```

2. Ensure marker file creation includes all metadata (already in Phase 1 script)

**Validation:**
- [ ] Status shows installDuration correctly
- [ ] Status shows installedBy pod name
- [ ] Duration is human-readable (e.g., "45s", "2m30s")
- [ ] Fields populated after successful install
- [ ] Fields absent or null when install hasn't run

**Files Changed:**
- Modified: `kaspr/handlers/kasprapp.py`
- Modified: `tests/unit/test_python_packages.py`

---

### Task 9: Add Stale Lock Detection and Cleanup ✓

**Objective:** Detect and clean up stale locks from crashed pods

**Files to Modify:**
- `kaspr/utils/python_packages.py`

**What to Implement:**

Update `generate_install_script()` to include stale lock detection:

```bash
# In init container script
check_stale_lock() {
  if [ -f "$LOCK_FILE" ]; then
    # Check lock file age (modified time)
    local lock_age=$(($(date +%s) - $(stat -f %m "$LOCK_FILE" 2>/dev/null || echo 0)))
    
    # If lock is older than INSTALL_TIMEOUT + buffer, consider stale
    local stale_threshold=$((INSTALL_TIMEOUT + 300))  # 5min buffer
    
    if [ $lock_age -gt $stale_threshold ]; then
      echo "⚠ Stale lock detected (${lock_age}s old), removing..."
      rm -f "$LOCK_FILE"
      return 0
    fi
  fi
  return 0
}

# Call before attempting lock
check_stale_lock

# Attempt to acquire lock
if ! acquire_lock; then
  echo "✗ Could not acquire lock"
  exit 1
fi
```

**Why needed:**
- Pod crashes during installation → lock file remains
- Subsequent pods block indefinitely
- Stale lock cleanup allows recovery

**Validation:**
- [ ] Stale locks detected correctly (age-based)
- [ ] Stale locks removed automatically
- [ ] Fresh locks not removed (age check works)
- [ ] Manual test: kill pod during install, verify next pod recovers

**Files Changed:**
- Modified: `kaspr/utils/python_packages.py`
- Modified: `tests/unit/test_python_packages.py`

---

### Task 10: Handle Image Field Compatibility ✓

**Objective:** Define behavior when both `image` and `pythonPackages` are specified

**Files to Modify:**
- `kaspr/resources/kasprapp.py`
- `kaspr/handlers/kasprapp.py`

**What to Implement:**

**Decision:** Warn and allow both (merge approach)
- Custom image specified → use it
- pythonPackages specified → install additional packages

**Rationale:**
- Maximum flexibility for users
- Allows gradual migration
- Custom image may have base packages, pythonPackages adds more

**Implementation:**

1. Add validation warning in handler:
   ```python
   @kopf.on.create(kind=APP_KIND)
   async def on_create(spec, name, namespace, logger, **kwargs):
       # Check for both image and pythonPackages
       if spec.get('image') and spec.get('pythonPackages'):
           logger.warning(
               f"KasprApp {name} specifies both 'image' and 'pythonPackages'. "
               f"Packages will be installed in addition to custom image. "
               f"Consider using 'pythonPackages' alone for easier maintenance."
           )
           # Add warning to status
           await add_status_warning(
               name, namespace,
               "Both image and pythonPackages specified - packages will be added to custom image"
           )
   ```

2. No code changes needed in resource generation - already works
   - Init container installs to `/packages`
   - Main container adds `/packages` to PYTHONPATH
   - Custom image packages still in default site-packages

**Validation:**
- [ ] Warning logged when both fields present
- [ ] Status includes warning
- [ ] Packages install correctly with custom image
- [ ] Both custom image packages and pythonPackages accessible

**Files Changed:**
- Modified: `kaspr/handlers/kasprapp.py`
- Modified: `tests/unit/test_python_packages.py`

---

### Task 11: Add Comprehensive Error Messages ✓

**Objective:** Improve error messages for common failure scenarios

**Files to Modify:**
- `kaspr/utils/python_packages.py`
- `kaspr/handlers/kasprapp.py`

**What to Implement:**

1. Enhance install script error handling:
   ```bash
   # In pip install error handling
   if ! timeout $INSTALL_TIMEOUT pip install ...; then
     echo "✗ Installation failed"
     
     # Try to determine error type
     if ! curl -s --head "$INDEX_URL" > /dev/null; then
       echo "ERROR_TYPE: network"
       echo "ERROR_MSG: Cannot reach package index: $INDEX_URL"
     elif grep -q "No matching distribution" /tmp/pip-error.log 2>/dev/null; then
       echo "ERROR_TYPE: package_not_found"
       echo "ERROR_MSG: One or more packages not found in index"
     elif grep -q "THESE PACKAGES DO NOT MATCH THE HASHES" /tmp/pip-error.log 2>/dev/null; then
       echo "ERROR_TYPE: hash_mismatch"
       echo "ERROR_MSG: Package hash verification failed"
     else
       echo "ERROR_TYPE: unknown"
       echo "ERROR_MSG: See pod logs for details"
     fi
     
     exit 1
   fi
   ```

2. Parse error from init container logs in status:
   ```python
   async def fetch_python_packages_status(app: KasprApp) -> dict:
       # ... existing logic ...
       
       # If init container failed
       if init_status == 'Failed':
           logs = await get_init_container_logs(pod_name, namespace)
           error_type, error_msg = parse_error_from_logs(logs)
           
           return {
               'state': 'Failed',
               'error': error_msg,
               'error_type': error_type,
               # ... other fields ...
           }
   ```

3. Add user-friendly error messages:
   ```python
   ERROR_MESSAGES = {
       'network': "Cannot reach package index. Check network connectivity and firewall rules.",
       'package_not_found': "Package not found in index. Verify package name and version.",
       'hash_mismatch': "Package integrity check failed. Package may be corrupted.",
       'authentication': "Authentication failed. Check credentials in referenced Secret.",
       'timeout': "Installation timed out. Consider increasing installPolicy.timeout.",
   }
   ```

**Validation:**
- [ ] Network errors identified correctly
- [ ] Package not found errors identified
- [ ] Error messages actionable and clear
- [ ] Status.error field populated with helpful message

**Files Changed:**
- Modified: `kaspr/utils/python_packages.py`
- Modified: `kaspr/handlers/kasprapp.py`
- Modified: `tests/unit/test_python_packages.py`

---

### Task 12: Add Metrics for Advanced Features ✓

**Objective:** Add metrics for Phase 2 features (auth, custom indexes, cache usage)

**Files to Modify:**
- `kaspr/sensors/prometheus.py`

**What to Implement:**

Add new metrics:

```python
# Authentication metrics
package_auth_enabled = Gauge(
    'kasprop_package_auth_enabled',
    'Whether PyPI authentication is configured',
    ['app_name', 'namespace']
)

# Custom index metrics
package_custom_index_enabled = Gauge(
    'kasprop_package_custom_index_enabled',
    'Whether custom PyPI index is configured',
    ['app_name', 'namespace']
)

# Cache metrics (from Task 7)
package_cache_usage_bytes = Gauge(
    'kasprop_package_cache_usage_bytes',
    'Python package cache disk usage',
    ['app_name', 'namespace', 'type']  # type: total|used|available
)

package_cache_usage_percent = Gauge(
    'kasprop_package_cache_usage_percent',
    'Python package cache disk usage percentage',
    ['app_name', 'namespace']
)

# Install policy metrics
package_install_retries_total = Counter(
    'kasprop_package_install_retries_total',
    'Total number of installation retries',
    ['app_name', 'namespace']
)

package_install_timeouts_total = Counter(
    'kasprop_package_install_timeouts_total',
    'Total number of installation timeouts',
    ['app_name', 'namespace']
)
```

Update sensor hooks:

```python
def on_package_install_complete(
    self,
    app_name: str,
    namespace: str,
    state: dict,
    success: bool,
    error_type: str = None,
    retries: int = 0  # NEW
):
    # ... existing metrics ...
    
    # Record retries
    if retries > 0:
        self.prometheus.package_install_retries_total.labels(
            app_name=app_name,
            namespace=namespace
        ).inc(retries)
    
    # Record timeout
    if error_type == 'timeout':
        self.prometheus.package_install_timeouts_total.labels(
            app_name=app_name,
            namespace=namespace
        ).inc()
```

**Validation:**
- [ ] Metrics exposed on /metrics endpoint
- [ ] Auth metrics set correctly
- [ ] Cache usage metrics update periodically
- [ ] Retry and timeout counters increment

**Files Changed:**
- Modified: `kaspr/sensors/prometheus.py`
- Modified: `kaspr/handlers/kasprapp.py`

---

### Task 13: Create Manual Testing Guide for Phase 2 ✓

**Objective:** Document manual test scenarios for Phase 2 features

**Files to Create:**
- `docs/testing/python-packages-phase2-manual-tests.md`

**What to Document:**

**Test Scenarios:**

1. **Private Registry Authentication**
   - Create Secret with PyPI credentials
   - Create KasprApp with credentials.secretRef
   - Verify packages install from private registry
   - Test with invalid credentials (should fail)
   - Verify credentials not exposed in logs/status

2. **Custom Index URLs**
   - Create KasprApp with custom indexUrl
   - Verify packages install from custom index
   - Test with extraIndexUrls (multiple indexes)
   - Test with trustedHosts for self-signed certs
   - Verify unreachable index fails gracefully

3. **Install Policy Configuration**
   - Test retries: Set retries=2, trigger failure, verify 2 attempts
   - Test timeout: Set timeout=30s with slow index, verify timeout
   - Test onFailure=allow: Bad package doesn't block pod startup
   - Test onFailure=block: Bad package blocks pod startup

4. **PVC Usage Monitoring**
   - Install large packages (tensorflow, torch)
   - Check status.pythonPackages.cacheUsage fields
   - Verify warning when >80% full
   - Check Prometheus metrics for cache usage

5. **Enhanced Status Reporting**
   - Verify installDuration populated
   - Verify installedBy shows correct pod name
   - Check lastInstallTime format
   - Verify cache usage stats in status

6. **Stale Lock Handling**
   - Simulate: Kill pod during installation
   - Start new pod, verify stale lock detected and removed
   - Verify installation proceeds successfully
   - Time stale lock threshold (should be ~15min)

7. **Image + pythonPackages Compatibility**
   - Create KasprApp with custom image AND pythonPackages
   - Verify warning in logs
   - Verify warning in status
   - Verify both image packages and pythonPackages available
   - Test import from both sources

8. **Error Message Quality**
   - Test with unreachable index → check error message
   - Test with nonexistent package → check error message
   - Test with invalid credentials → check error message
   - Verify error messages are actionable

9. **Metrics Validation**
   - Access operator /metrics endpoint
   - Verify auth_enabled metric set correctly
   - Verify custom_index_enabled metric
   - Check cache_usage_bytes and cache_usage_percent
   - Verify retry and timeout counters

10. **End-to-End Enterprise Scenario**
    - Private registry + custom packages + auth
    - Multiple indexes with different packages
    - Large package install with retries
    - Monitor cache usage growth
    - Verify all metrics and status fields

**Testing Checklist Format:**

Each scenario includes:
- Prerequisites (Secrets, custom registry, etc.)
- Step-by-step commands
- Expected results at each step
- Validation commands
- Success criteria
- Cleanup procedures

**Validation:**
- [ ] All 10 scenarios documented with commands
- [ ] Scenarios tested in local/dev cluster
- [ ] Screenshots/logs for reference
- [ ] Troubleshooting tips included
- [ ] Known limitations documented

**Files Changed:**
- New: `docs/testing/python-packages-phase2-manual-tests.md`

---

### Task 14: Add Phase 2 Examples ✓

**Objective:** Create example manifests for Phase 2 features

**Files to Create:**
- `examples/python-packages/private-registry.yaml`
- `examples/python-packages/custom-indexes.yaml`
- `examples/python-packages/install-policy.yaml`
- `examples/python-packages/enterprise-complete.yaml`
- `examples/python-packages/secrets/pypi-credentials.yaml`

**What to Create:**

**1. Private Registry Example:**
```yaml
# examples/python-packages/private-registry.yaml
apiVersion: kaspr.io/v1alpha1
kind: KasprApp
metadata:
  name: app-with-private-registry
  namespace: default
spec:
  replicas: 3
  bootstrapServers: kafka:9092
  authentication: { ... }
  
  pythonPackages:
    packages:
      - my-company-lib==1.2.3
      - internal-utils>=2.0.0
    
    indexUrl: https://pypi.company.com/simple
    
    credentials:
      secretRef:
        name: pypi-credentials
        usernameKey: username
        passwordKey: password
---
# examples/python-packages/secrets/pypi-credentials.yaml
apiVersion: v1
kind: Secret
metadata:
  name: pypi-credentials
  namespace: default
type: Opaque
stringData:
  username: "my-username"
  password: "my-password"
```

**2. Custom Indexes Example:**
```yaml
# examples/python-packages/custom-indexes.yaml
apiVersion: kaspr.io/v1alpha1
kind: KasprApp
metadata:
  name: app-with-custom-indexes
spec:
  pythonPackages:
    packages:
      - requests==2.31.0  # From public PyPI
      - company-lib==1.0.0  # From private index
    
    # Primary index (public PyPI)
    indexUrl: https://pypi.org/simple
    
    # Fallback to private index
    extraIndexUrls:
      - https://pypi.company.com/simple
    
    # Trust self-signed cert
    trustedHosts:
      - pypi.company.com
```

**3. Install Policy Example:**
```yaml
# examples/python-packages/install-policy.yaml
apiVersion: kaspr.io/v1alpha1
kind: KasprApp
metadata:
  name: app-with-install-policy
spec:
  pythonPackages:
    packages:
      - tensorflow==2.13.0  # Large package
    
    # Aggressive retry policy
    installPolicy:
      retries: 5  # Try up to 5 times
      timeout: 1200  # 20 minutes (large packages)
      onFailure: block  # Don't start pods if install fails
    
    # More resources for large installs
    resources:
      requests:
        memory: 1Gi
        cpu: 500m
      limits:
        memory: 4Gi
        cpu: 2000m
    
    # Larger cache
    cache:
      size: 10Gi
```

**4. Complete Enterprise Example:**
```yaml
# examples/python-packages/enterprise-complete.yaml
apiVersion: kaspr.io/v1alpha1
kind: KasprApp
metadata:
  name: enterprise-app
  namespace: production
spec:
  replicas: 5
  bootstrapServers: kafka-prod:9092
  
  pythonPackages:
    # Mix of public and private packages
    packages:
      - requests==2.31.0
      - pandas==2.1.0
      - company-analytics-lib==3.2.1
      - internal-ml-toolkit>=1.5.0,<2.0.0
    
    # Primary: private registry
    indexUrl: https://artifacts.company.com/pypi/simple
    
    # Fallback: public PyPI
    extraIndexUrls:
      - https://pypi.org/simple
    
    # Trust internal registry
    trustedHosts:
      - artifacts.company.com
    
    # Authentication
    credentials:
      secretRef:
        name: production-pypi-creds
    
    # Production-grade policy
    installPolicy:
      retries: 3
      timeout: 900  # 15 minutes
      onFailure: block
    
    # Generous resources
    resources:
      requests:
        memory: 1Gi
        cpu: 500m
      limits:
        memory: 4Gi
        cpu: 2000m
    
    # Fast NFS storage
    cache:
      enabled: true
      storageClass: fast-nfs
      size: 20Gi
      accessMode: ReadWriteMany
      deleteClaim: false  # Retain for troubleshooting
```

**5. README:**
```markdown
# examples/python-packages/README.md

# Python Packages Examples

This directory contains example KasprApp manifests demonstrating Python package management features.

## Examples

### Basic (Phase 1)
- `basic.yaml` - Simple package list
- `with-cache-config.yaml` - Custom cache configuration

### Advanced (Phase 2)
- `private-registry.yaml` - Private PyPI registry with authentication
- `custom-indexes.yaml` - Multiple package indexes
- `install-policy.yaml` - Retry/timeout configuration
- `enterprise-complete.yaml` - Production-ready configuration

## Prerequisites

### For Private Registry Examples
Create Secret with credentials:
```bash
kubectl create secret generic pypi-credentials \
  --from-literal=username=your-username \
  --from-literal=password=your-password
```

### For Custom Storage Class
Ensure storage class exists:
```bash
kubectl get storageclass fast-nfs
```

## Usage

Apply an example:
```bash
kubectl apply -f basic.yaml
```

Check status:
```bash
kubectl get kasprapp -o yaml | grep -A 20 pythonPackages
```

View init container logs:
```bash
kubectl logs <pod-name> -c install-packages
```

## Troubleshooting

See [Python Packages User Guide](../../docs/user-guide/python-packages.md)
```

**Validation:**
- [ ] All examples apply without errors
- [ ] Examples result in working deployments
- [ ] README clear and accurate
- [ ] Secret example included
- [ ] Examples cover all Phase 2 features

**Files Changed:**
- New: `examples/python-packages/private-registry.yaml`
- New: `examples/python-packages/custom-indexes.yaml`
- New: `examples/python-packages/install-policy.yaml`
- New: `examples/python-packages/enterprise-complete.yaml`
- New: `examples/python-packages/secrets/pypi-credentials.yaml`
- Modified: `examples/python-packages/README.md`

---

### Task 15: Update User Documentation ✓

**Objective:** Document Phase 2 features in user guide

**Files to Modify:**
- `docs/user-guide/python-packages.md`

**What to Add:**

Add sections to existing user guide:

**1. Private Registry Authentication**
```markdown
## Private Registry Authentication

To use packages from a private PyPI registry:

1. Create a Secret with credentials:
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: pypi-credentials
type: Opaque
stringData:
  username: "your-username"
  password: "your-password"
```

2. Reference in KasprApp:
```yaml
spec:
  pythonPackages:
    packages:
      - my-private-package==1.0.0
    credentials:
      secretRef:
        name: pypi-credentials
```

**Security Note:** Credentials are injected as environment variables and never logged or exposed in status.
```

**2. Custom Package Indexes**
```markdown
## Custom Package Indexes

Use custom or multiple PyPI indexes:

```yaml
spec:
  pythonPackages:
    # Primary index
    indexUrl: https://pypi.company.com/simple
    
    # Additional indexes
    extraIndexUrls:
      - https://pypi.org/simple
    
    # Trust self-signed certificates
    trustedHosts:
      - pypi.company.com
```

Packages are searched in order: `indexUrl` first, then `extraIndexUrls`.
```

**3. Installation Policy**
```markdown
## Installation Policy

Configure retry behavior and timeouts:

```yaml
spec:
  pythonPackages:
    installPolicy:
      retries: 3  # Number of retry attempts
      timeout: 600  # Timeout in seconds (default: 10 minutes)
      onFailure: block  # block | allow
```

- `retries`: Number of times to retry failed installations (default: 3)
- `timeout`: Maximum time for pip install (default: 600s)
- `onFailure`:
  - `block` (default): Pod won't start if install fails
  - `allow`: Pod starts with warning, packages unavailable
```

**4. Monitoring Cache Usage**
```markdown
## Monitoring Cache Usage

Check cache usage in status:

```bash
kubectl get kasprapp my-app -o yaml | grep -A 10 "pythonPackages:"
```

Example output:
```yaml
status:
  pythonPackages:
    state: Ready
    cacheUsage:
      totalBytes: 5368709120
      usedBytes: 2684354560
      availableBytes: 2684354560
      usagePercent: 50.0
    warnings:
      - "Package cache 85.2% full (4.25GB / 5GB)"
```

Increase cache size if needed:
```yaml
spec:
  pythonPackages:
    cache:
      size: 10Gi
```
```

**5. Troubleshooting**
```markdown
## Troubleshooting

### Authentication Failures

If installation fails with authentication errors:

1. Verify Secret exists:
   ```bash
   kubectl get secret pypi-credentials
   ```

2. Check Secret has correct keys:
   ```bash
   kubectl get secret pypi-credentials -o yaml
   ```

3. Test credentials manually:
   ```bash
   curl -u username:password https://pypi.company.com/simple/
   ```

### Network Issues

If packages can't be downloaded:

1. Check init container logs:
   ```bash
   kubectl logs <pod-name> -c install-packages
   ```

2. Verify index URL reachable:
   ```bash
   kubectl run -it --rm curl --image=curlimages/curl -- \
     curl -I https://pypi.org/simple/
   ```

3. Check NetworkPolicy restrictions

### Timeout Issues

For large packages (ML libraries), increase timeout:

```yaml
spec:
  pythonPackages:
    installPolicy:
      timeout: 1800  # 30 minutes for very large packages
```

### Cache Full Warnings

When cache approaches capacity:

1. Increase PVC size (triggers rollout):
   ```yaml
   spec:
     pythonPackages:
       cache:
         size: 20Gi
   ```

2. Or clean up (requires manual intervention):
   ```bash
   kubectl exec <pod-name> -- rm -rf /packages/*
   # Restart pods to trigger reinstall
   kubectl delete pod -l kaspr.io/app=my-app
   ```
```

**Validation:**
- [ ] Documentation clear and comprehensive
- [ ] All Phase 2 features documented
- [ ] Examples included in each section
- [ ] Troubleshooting section helpful
- [ ] Links to examples directory

**Files Changed:**
- Modified: `docs/user-guide/python-packages.md`

---

## Task Dependencies

```
Task 1 (Auth Models)
  ↓
Task 2 (Index Models) ← Can be parallel with Task 1
  ↓
Task 3 (CRD Updates)
  ↓
Task 4 (Credential Handling)
  ↓
Task 5 (Index URL Support)
  ↓
Task 6 (Install Policy)
  ↓
Task 7 (PVC Monitoring)
Task 8 (Enhanced Status) ← Can be parallel with Task 7
Task 9 (Stale Lock) ← Can be parallel with Task 7-8
Task 10 (Compatibility) ← Can be parallel with Task 7-9
Task 11 (Error Messages) ← Can be parallel with Task 7-10
  ↓
Task 12 (Metrics)
  ↓
Task 13 (Manual Testing)
  ↓
Task 14 (Examples)
Task 15 (Documentation) ← Can be parallel with Task 14
```

## Testing Strategy Per Task

### Unit Testing
- After each task that adds logic (Tasks 1-6, 9, 11)
- Run: `pytest tests/unit/test_python_packages.py -v`
- Focus on new functions and validation

### Manual Testing
- After Task 6 (install policy complete)
- Test private registry scenarios
- Test custom indexes
- Test retry/timeout behavior

### Integration Testing
- Task 13 (manual testing guide)
- Follow documented scenarios
- Validate in dev cluster with real private registry

### Smoke Testing
- After Task 14 (examples)
- Apply all examples
- Verify they work end-to-end

## Rollout Plan

### Local Development
1. Implement tasks 1-15 on feature branch (continue from Phase 1 branch)
2. Test each task independently
3. Run unit tests after tasks 1-6, 11
4. Manual testing following Task 13 guide
5. Apply examples from Task 14

### Dev Cluster Testing
1. Deploy operator to dev cluster
2. Set up test private PyPI registry (JFrog Artifactory or devpi)
3. Test with real authentication
4. Monitor metrics and logs
5. Stress test with large packages

### Staging Deployment
1. Deploy to staging with real workloads
2. Test enterprise scenarios
3. Validate metrics and alerting
4. Soak test (48h+ stability)

### Production Rollout
1. Phase 2 features enabled (builds on Phase 1 MVP)
2. Documentation updated
3. Beta announcement for Phase 2 features
4. Gather feedback from enterprise users
5. GA release after validation period

## Success Criteria

After completing all Phase 2 tasks, we should have:

- [ ] Private registry authentication working
- [ ] Custom PyPI indexes supported
- [ ] Configurable install policy (retries, timeout, onFailure)
- [ ] PVC usage monitoring and warnings
- [ ] Enhanced status reporting (duration, installedBy, cache stats)
- [ ] Stale lock detection and cleanup
- [ ] Image + pythonPackages compatibility handled
- [ ] Comprehensive error messages
- [ ] Phase 2 metrics exposed
- [ ] Manual testing guide complete
- [ ] Phase 2 examples working
- [ ] Documentation updated

## Risk Mitigation

### Risk: Credential Exposure
**Mitigation:** 
- Use Secret references only
- Never log credentials
- Validate Secret exists before pod creation
- Document security best practices

### Risk: Private Registry Availability
**Mitigation:**
- Support multiple indexes (fallback)
- Configurable timeout and retries
- Clear error messages for network issues

### Risk: Large Package Installs
**Mitigation:**
- Generous default timeout (10 minutes)
- Configurable timeout per app
- Resource limits on init container
- PVC size warnings

### Risk: Cache Exhaustion
**Mitigation:**
- Monitor PVC usage
- Warn at 80% full
- Document cleanup procedures
- Support PVC resize (triggers rollout)

## Review Checkpoints

After completing each task:
1. Self-review code changes
2. Run relevant unit tests
3. Commit with descriptive message
4. Request review before next task

Key review points:
- After Task 3: CRD updated with Phase 2 fields
- After Task 6: Core Phase 2 functionality implemented
- After Task 12: Metrics and observability complete
- After Task 13: Testing guide complete
- After Task 15: Ready for beta release

---

**Document Status:** Ready for Implementation  
**Last Updated:** 2025-11-28  
**Prerequisites:** Phase 1 complete
