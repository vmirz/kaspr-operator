# Python Package Management - Phase 1 Implementation Plan

## Overview

This document outlines the step-by-step implementation plan for Phase 1 (MVP) of the Python package management feature. Each task is designed to be independently implementable and reviewable.

## Implementation Approach

- **Incremental**: Each task builds on the previous one
- **Testable**: Each task includes validation steps
- **Reviewable**: Small, focused changes for easy review
- **Safe**: No breaking changes to existing functionality

## Task Breakdown

### Task 1: Create Data Models and Schemas ✓

**Objective:** Define Python data structures for pythonPackages configuration

**Files to Create:**
- `kaspr/types/models/python_packages.py` - Dataclass models
- `kaspr/types/schemas/python_packages.py` - Marshmallow validation schemas

**What to Implement:**
1. `PythonPackagesCache` model for cache configuration
2. `PythonPackagesInstallPolicy` model for installation policy
3. `PythonPackagesResources` model for init container resources
4. `PythonPackagesSpec` model for complete spec
5. `PythonPackagesStatus` model for status reporting
6. Corresponding Marshmallow schemas for validation

**Model Pattern:**
All models must inherit from `BaseModel` (from `kaspr.types.base`), following the established pattern in `kaspr/types/models/kasprapp_spec.py`. 

**Important:**
- Do NOT use `@dataclass`
- Do NOT set default values in model classes
- Default values should be defined as constants in resource classes (e.g., `kaspr/resources/kasprapp.py`)

Example:
```python
from typing import Optional, List
from kaspr.types.base import BaseModel

class PythonPackagesCache(BaseModel):
    """Python packages cache configuration."""
    enabled: Optional[bool]
    storage_class: Optional[str]
    size: Optional[str]
    access_mode: Optional[str]
    delete_claim: Optional[bool]

class PythonPackagesSpec(BaseModel):
    """Python packages specification."""
    packages: List[str]
    cache: Optional[PythonPackagesCache]
    # ... other fields
```

Then in `kaspr/resources/kasprapp.py`, add class constants:
```python
class KasprApp(BaseResource):
    # ... existing constants ...
    
    # Python packages defaults
    DEFAULT_PACKAGES_PVC_SIZE = "256Mi"
    DEFAULT_PACKAGES_CACHE_ENABLED = True
    DEFAULT_PACKAGES_ACCESS_MODE = "ReadWriteMany"
    DEFAULT_PACKAGES_DELETE_CLAIM = True
```

**Validation:**
- [ ] Unit tests for model instantiation
- [ ] Unit tests for schema validation (valid/invalid inputs)
- [ ] Schema correctly serializes/deserializes

**Files Changed:**
- New: `kaspr/types/models/python_packages.py`
- New: `kaspr/types/schemas/python_packages.py`
- Modified: `kaspr/types/models/__init__.py` (add exports)
- Modified: `kaspr/types/schemas/__init__.py` (add exports)

---

### Task 2: Add Utility Functions for Package Management ✓

**Objective:** Create helper functions for hash computation, script generation, and validation

**Files to Create:**
- `kaspr/utils/python_packages.py` - Utility functions

**What to Implement:**
1. `compute_packages_hash(packages_spec: dict) -> str` - Deterministic hash computation
2. `validate_package_name(package: str) -> bool` - Validate pip package format
3. `validate_packages_spec(spec: dict) -> tuple[bool, list[str]]` - Validate entire spec
4. `generate_install_script(spec: dict, hash: str) -> str` - Generate init container script
5. `parse_package_string(package: str) -> dict` - Parse package with version/operators

**Validation:**
- [ ] Unit tests for hash computation (order-independent, deterministic)
- [ ] Unit tests for package name validation (valid/invalid formats)
- [ ] Unit tests for install script generation
- [ ] Test script includes flock logic, marker files, error handling

**Files Changed:**
- New: `kaspr/utils/python_packages.py`
- New: `tests/unit/test_python_packages.py`

---

### Task 3: Update CRD with pythonPackages Spec and Status ✓

**Objective:** Extend KasprApp CRD with new fields

**Files to Modify:**
- `crds/kasprapp.crd.yaml`

**What to Implement:**
1. Add `spec.pythonPackages` with properties:
   - `packages` (array of strings)
   - `indexUrl` (string, optional)
   - `extraIndexUrls` (array, optional)
   - `trustedHosts` (array, optional)
   - `cache` (object with enabled, storageClass, size, accessMode, deleteClaim)
   - `installPolicy` (object with retries, timeout, onFailure)
   - `resources` (object with requests/limits)

2. Add `status.pythonPackages` with properties:
   - `state` (string: Installing|Ready|Failed)
   - `hash` (string)
   - `installed` (array of strings)
   - `cacheMode` (string)
   - `lastInstallTime` (string, date-time)
   - `installDuration` (string)
   - `installedBy` (string)
   - `error` (string)
   - `warnings` (array of strings)

**Validation:**
- [ ] CRD applies without errors: `kubectl apply -f crds/kasprapp.crd.yaml`
- [ ] Create test KasprApp with pythonPackages field (validation only)
- [ ] Schema validation works (invalid values rejected)

**Files Changed:**
- Modified: `crds/kasprapp.crd.yaml`

---

### Task 4: Integrate Models into KasprApp Spec and Status ✓

**Objective:** Update KasprAppSpec and KasprAppStatus models to include pythonPackages

**Files to Modify:**
- `kaspr/types/models/kasprapp_spec.py`
- `kaspr/types/schemas/kasprapp_spec.py`
- `kaspr/types/models/kasprapp_resources.py` (if status is here)
- `kaspr/resources/kasprapp.py` (to include in from_spec method)

**What to Implement:**
1. Add `python_packages: Optional[PythonPackagesSpec]` to `KasprAppSpec` dataclass
2. Add `python_packages: Optional[PythonPackagesStatus]` to `KasprAppStatus` (or resources)
3. Update schema to include new fields with proper nesting
4. Ensure backward compatibility (all new fields optional)
5. Update `KasprApp.from_spec()` in `kaspr/resources/kasprapp.py`:
   ```python
   app.python_packages = spec.python_packages
   ```

**Validation:**
- [ ] Existing KasprApp specs still load correctly
- [ ] New pythonPackages field parses correctly
- [ ] Schema validation works end-to-end
- [ ] from_spec() method properly assigns python_packages attribute

**Files Changed:**
- Modified: `kaspr/types/models/kasprapp_spec.py`
- Modified: `kaspr/types/schemas/kasprapp_spec.py`
- Modified: `kaspr/types/models/kasprapp_resources.py` (or appropriate status file)
- Modified: `kaspr/resources/kasprapp.py`

---

### Task 5: Add PVC Generation Logic to KasprApp Resource ✓

**Objective:** Generate and manage PersistentVolumeClaim for package storage

**Note:** Unlike the main storage PVC (which uses StatefulSet's `volume_claim_templates`), the python packages PVC is a **standalone shared PVC** created separately and mounted by all pods. This allows all pods to share the same package cache.

**Files to Modify:**
- `kaspr/resources/kasprapp.py`

**What to Implement:**

Following the established pattern of `prepare_*` methods and `@cached_property` accessors:

1. Add private attributes:
   - `_python_packages_pvc: V1PersistentVolumeClaim = None`
   - `_python_packages_pvc_name: str = None`

2. Add property for PVC name:
   ```python
   @cached_property
   def python_packages_pvc_name(self) -> str:
       if self._python_packages_pvc_name is None:
           self._python_packages_pvc_name = f"{self.component_name}-python-packages"
       return self._python_packages_pvc_name
   ```

3. Add method `prepare_python_packages_pvc() -> V1PersistentVolumeClaim`
   - Name: Use `self.python_packages_pvc_name`
   - Labels: Standard app labels + `kaspr.io/component: python-packages`
   - Access mode: ReadWriteMany (primary), fallback to ReadWriteOnce
   - Storage class: From spec.pythonPackages.cache.storageClass or default (None)
   - Size: From spec.pythonPackages.cache.size or `self.DEFAULT_PACKAGES_PVC_SIZE` (256Mi)
   - Include hash annotation via `prepare_hash_annotation()`

4. Add `@cached_property` accessor:
   ```python
   @cached_property
   def python_packages_pvc(self) -> V1PersistentVolumeClaim:
       if self._python_packages_pvc is None:
           self._python_packages_pvc = self.prepare_python_packages_pvc()
       return self._python_packages_pvc
   ```

5. Add helper `prepare_python_packages_pvc_hash(pvc: V1PersistentVolumeClaim) -> str`

6. Add method `should_create_packages_pvc() -> bool`
   - Return True if spec.python_packages exists and cache.enabled is True (default)

7. Update `synchronize()` to call `await self.sync_python_packages_pvc()`

8. Add `sync_python_packages_pvc()` method following the pattern of `sync_service()`, `sync_settings_config_map()`:
   - Check if PVC exists
   - If PVC exists and `should_create_packages_pvc()` is False: Delete PVC (feature disabled)
   - If PVC missing and `should_create_packages_pvc()` is True: Create PVC
   - If PVC exists and `should_create_packages_pvc()` is True: Patch if hash differs (size changes, storage class changes, etc.)
   - Include sensor instrumentation for all operations (create/patch/delete)

**Validation:**
- [ ] Standalone PVC created (not in volume_claim_templates)
- [ ] PVC created when pythonPackages specified with cache enabled
- [ ] PVC has correct access mode (RWX), size, storage class
- [ ] PVC not created when cache.enabled is false
- [ ] PVC labels allow querying by app
- [ ] Hash annotation present for drift detection
- [ ] All pods mount the same shared PVC

**Files Changed:**
- Modified: `kaspr/resources/kasprapp.py`

---

### Task 6: Add Init Container Generation Logic ✓

**Objective:** Generate init container spec for package installation

**Files to Modify:**
- `kaspr/resources/kasprapp.py`

**What to Implement:**

Following the established pattern of `prepare_*` methods and `@cached_property` accessors:

1. Add private attributes:
   - `_python_packages_init_container: V1Container = None`
   - `_python_packages_hash: str = None`

2. Add method `prepare_python_packages_init_container() -> V1Container`
   - Name: `install-packages`
   - Image: Same as main kaspr container (use `self.image`)
   - Command: `/bin/sh -c`
   - Args: Install script (from `generate_install_script()` utility)
   - Env vars: From `prepare_python_packages_env_vars()`
   - Volume mount: packages PVC at `/packages`
   - Resources: From spec or defaults

3. Add `@cached_property` accessor:
   ```python
   @cached_property
   def python_packages_init_container(self) -> V1Container:
       if self._python_packages_init_container is None:
           self._python_packages_init_container = self.prepare_python_packages_init_container()
       return self._python_packages_init_container
   ```

4. Add method `prepare_python_packages_env_vars() -> List[V1EnvVar]`
   - Return env vars for init container (hash, packages, urls, etc.)

5. Add method `prepare_python_packages_hash() -> str`
   - Compute deterministic hash using `compute_packages_hash()` utility
   - Cache result

6. Add `@cached_property` accessor for hash:
   ```python
   @cached_property
   def python_packages_hash(self) -> str:
       if self._python_packages_hash is None:
           self._python_packages_hash = self.prepare_python_packages_hash()
       return self._python_packages_hash
   ```

**Validation:**
- [ ] Init container spec generated correctly
- [ ] Script includes flock logic, marker files
- [ ] Env vars populated from spec
- [ ] Volume mount configured

**Files Changed:**
- Modified: `kaspr/resources/kasprapp.py`

---

### Task 7: Integrate Init Container and Volume into StatefulSet ✓

**Objective:** Modify StatefulSet rendering to include packages init container and volume

**Files to Modify:**
- `kaspr/resources/kasprapp.py`

**What to Implement:**

Following the established pattern:

1. Add method `prepare_python_packages_volume() -> V1Volume` 
   - Create volume backed by packages PVC
   - Return None if pythonPackages not configured

2. Add method `prepare_python_packages_volume_mount() -> V1VolumeMount`
   - Mount at `/packages` (readOnly for main container)
   - Return None if pythonPackages not configured

3. Update `prepare_volumes()` method:
   - Conditionally include python packages volume if configured
   ```python
   volumes.extend(self.prepare_agent_volumes())
   volumes.extend(self.prepare_webview_volumes())
   volumes.extend(self.prepare_table_volumes())
   volumes.extend(self.prepare_task_volumes())
   if self.should_mount_python_packages():
       volumes.append(self.prepare_python_packages_volume())
   volumes.extend(self.prepare_pod_template_volumes())
   ```

4. Update `prepare_volume_mounts()` method:
   - Conditionally include packages mount
   ```python
   volume_mounts.extend([
       V1VolumeMount(name=self.persistent_volume_claim_name, ...),
       *self.prepare_agent_volume_mounts(),
       ...
   ])
   if self.should_mount_python_packages():
       volume_mounts.append(self.prepare_python_packages_volume_mount())
   ```

5. Add helper `should_mount_python_packages() -> bool`
   - Check if spec.python_packages is configured

6. Update `prepare_env_vars()` method:
   - Add PYTHONPATH env var when packages configured
   ```python
   if self.should_mount_python_packages():
       # Prepend custom packages path to PYTHONPATH
       # Python will still automatically search default site-packages locations
       # (e.g., /usr/local/lib/python3.9/site-packages) where pip installed packages reside
       env_vars.append(V1EnvVar(
           name="PYTHONPATH",
           value="/packages/site-packages"
       ))
   ```
   
   **Note:** Setting `PYTHONPATH` adds to Python's search path without removing default locations. Packages installed via `pip install -r requirements.txt` in the Kaspr app image will still be found in their standard site-packages directory.

7. Update `prepare_pod_spec()` method:
   - Add init_containers conditionally
   ```python
   init_containers = []
   if self.should_mount_python_packages():
       init_containers.append(self.python_packages_init_container)
   
   return V1PodSpec(
       ...
       init_containers=init_containers if init_containers else None,
       containers=[self.kaspr_container],
       ...
   )
   ```

**Validation:**
- [ ] StatefulSet includes init container when packages specified
- [ ] StatefulSet includes volume and volume mounts
- [ ] Main container has PYTHONPATH set correctly
- [ ] Existing KasprApps without packages unaffected (backwards compatible)

**Files Changed:**
- Modified: `kaspr/resources/kasprapp.py`

---

### Task 8: Add Handler for pythonPackages Field Changes ✓

**Objective:** Detect and react to pythonPackages spec changes

**Files to Modify:**
- `kaspr/handlers/kasprapp.py`

**What to Implement:**
1. Add field watcher: `@kopf.on.update(kind=APP_KIND, field="spec.pythonPackages")`
2. Handler: `on_python_packages_update()`
   - Log the change
   - Compute new hash
   - Trigger reconciliation
   - Update status (state: Installing)

3. Helper function: `packages_changed(old, new) -> bool`
   - Deep comparison of package specs

**Validation:**
- [ ] Handler triggered when pythonPackages added
- [ ] Handler triggered when packages list changed
- [ ] Handler triggered when cache config changed
- [ ] Reconciliation requested

**Files Changed:**
- Modified: `kaspr/handlers/kasprapp.py`

---

### Task 9: Add Status Reporting for pythonPackages ✓

**Objective:** Update KasprApp status with package installation state

**Files to Modify:**
- `kaspr/handlers/kasprapp.py`

**What to Implement:**
1. Update `update_status()` function:
   - Add section for pythonPackages status
   - Detect init container completion status
   - Parse marker file to get installed packages
   - Set state: Installing|Ready|Failed
   - Populate error field if failed

2. Add helper: `fetch_python_packages_status(app) -> dict`
   - **Query strategy:** Check any one available pod (first ready pod is sufficient)
   - **Why this works:** All pods share the same PVC and see the same marker file
   - **Implementation:**
     - List pods for the app
     - Select first available/ready pod
     - Check init container `install-packages` status (Completed/Failed/Running)
     - If init succeeded, exec into pod and read marker file at `/packages/.installed-{hash}`
     - Parse marker file JSON for: installed packages list, install time, duration, pod name
   - **Return:** Dict with state, hash, installed packages, metadata
   - **Handle edge cases:**
     - No pods ready yet: Return state "Installing"
     - Init container failed: Return state "Failed" with error from container logs
     - Marker file missing (shouldn't happen): Return state "Failed"
     - Multiple pods: Only need to check one - they all see the same shared storage

3. Add helper: `detect_rwx_support() -> bool`
   - Check if cluster supports RWX PVCs
   - Set cacheMode in status

**Validation:**
- [ ] Status shows "Installing" during first pod startup
- [ ] Status shows "Ready" after successful install
- [ ] Status shows "Failed" if pip install fails
- [ ] Installed packages list populated
- [ ] lastInstallTime, duration, installedBy populated

**Files Changed:**
- Modified: `kaspr/handlers/kasprapp.py`

---

### Task 10: Add Prometheus Metrics for Package Installation ✓

**Objective:** Instrument package installation with metrics

**Files to Modify:**
- `kaspr/sensors/prometheus.py`

**What to Implement:**
1. Add metrics in `kaspr/sensors/prometheus.py`:
   ```python
   package_install_duration_seconds = Histogram(
       'kasprop_package_install_duration_seconds',
       'Time taken to install Python packages',
       ['app_name', 'namespace']
   )
   package_install_total = Counter(
       'kasprop_package_install_total',
       'Total number of package installations',
       ['app_name', 'namespace', 'result']  # result: success/failure
   )
   package_install_errors_total = Counter(
       'kasprop_package_install_errors_total',
       'Total number of package installation errors',
       ['app_name', 'namespace', 'error_type']
   )
   ```

2. Add sensor hooks to `SensorDelegate` class:
   ```python
   def on_package_install_start(self, app_name: str, namespace: str) -> dict:
       """Called when package installation begins. Returns state for tracking."""
       return {"start_time": time.time()}
   
   def on_package_install_complete(
       self, 
       app_name: str, 
       namespace: str, 
       state: dict, 
       success: bool,
       error_type: str = None
   ):
       """Called when package installation completes (success or failure)."""
       duration = time.time() - state.get("start_time", time.time())
       
       # Record duration
       self.prometheus.package_install_duration_seconds.labels(
           app_name=app_name,
           namespace=namespace
       ).observe(duration)
       
       # Record result
       result = "success" if success else "failure"
       self.prometheus.package_install_total.labels(
           app_name=app_name,
           namespace=namespace,
           result=result
       ).inc()
       
       # Record error if failed
       if not success and error_type:
           self.prometheus.package_install_errors_total.labels(
               app_name=app_name,
               namespace=namespace,
               error_type=error_type
           ).inc()
   ```

3. Instrument from handler:
   - Record duration of install
   - Increment success/failure counters
   - Record error types

**Validation:**
- [ ] Metrics exposed on /metrics endpoint
- [ ] Duration recorded for successful installs
- [ ] Error counter increments on failures
- [ ] Labels correct (app_name, namespace, result)

**Files Changed:**
- Modified: `kaspr/sensors/prometheus.py`
- Modified: `kaspr/handlers/kasprapp.py` (add instrumentation calls)

---

### Task 11: Add PVC to Ownership Chain ✓

**Objective:** Include Python packages PVC in Kopf's adoption mechanism for automatic lifecycle management

**Files to Modify:**
- `kaspr/resources/kasprapp.py`

**What to Implement:**

Update the `unite()` method to include the Python packages PVC when it exists. Kopf will automatically set owner references, and Kubernetes will handle cascading deletion:

```python
def unite(self):
    """Ensure all child resources are owned by the root resource"""
    children = [
        self.service_account,
        self.settings_config_map,
        self.service,
        self.headless_service,
        self.stateful_set,
        self.hpa,
    ]
    
    # Add Python packages PVC if enabled
    if self.should_create_packages_pvc():
        children.append(self.packages_pvc)
    
    kopf.adopt(children)
```

**Why this approach:**
- Kopf's `adopt()` sets owner references on child resources
- Kubernetes automatically performs cascading deletion when parent is deleted
- No manual cleanup logic needed in deletion handlers
- Consistent with how all other KasprApp resources are managed
- Respects the `deleteClaim` setting through PVC retention policy (handled in Task 5)

**Validation:**
- [ ] Create a KasprApp with Python packages enabled
- [ ] Verify the PVC has owner references: `kubectl get pvc <pvc-name> -o yaml`
- [ ] Check `metadata.ownerReferences` points to the KasprApp
- [ ] Delete the KasprApp
- [ ] Verify the PVC is automatically removed by Kubernetes
- [ ] Create a KasprApp without Python packages
- [ ] Verify `unite()` doesn't fail when packages disabled

**Files Changed:**
- Modified: `kaspr/resources/kasprapp.py`

---

### Task 12: Manual Integration Testing ✓

**Objective:** Document manual test scenarios for validating the Python packages feature

**Files to Create:**
- `docs/testing/python-packages-manual-tests.md`

**What to Document:**

Create a comprehensive manual testing guide with specific test scenarios, expected outcomes, and validation commands.

**Test Scenarios to Document:**

1. **Basic Package Installation**
   - Create KasprApp with simple package list (e.g., `requests`, `numpy`)
   - Commands to check pod status, init container logs
   - Verify PVC created: `kubectl get pvc -l kaspr.io/app=<app-name>`
   - Exec into pod and verify packages importable: `python -c "import requests"`
   - Check status field shows "Ready" state
   - Verify marker file exists: `ls -la /packages/.installed-*`

2. **Package Updates**
   - Create KasprApp with package version 1
   - Update spec to different version
   - Watch for StatefulSet rollout: `kubectl rollout status sts/<app-name>`
   - Verify new init container runs with new hash
   - Check old marker file removed, new one created
   - Verify new version installed in pods

3. **Cache Reuse (Multi-replica)**
   - Create KasprApp with 3 replicas
   - Check init container logs across pods
   - Verify only first pod installs (others skip with "Packages already installed")
   - Scale to 6 replicas: `kubectl scale kasprapp <name> --replicas=6`
   - Verify new pods skip installation (fast startup)
   - Time new pod readiness (<5s expected)

4. **Feature Disable/Enable**
   - Create KasprApp with pythonPackages
   - Verify PVC exists
   - Remove pythonPackages from spec
   - Verify PVC is deleted during reconciliation
   - Re-add pythonPackages
   - Verify PVC recreated and packages reinstalled

5. **Installation Failure Handling**
   - Create KasprApp with invalid package name (e.g., `this-package-does-not-exist-12345`)
   - Verify init container fails
   - Check init container logs for error message
   - Verify status shows "Failed" state with error details
   - Verify main container doesn't start
   - Fix package name and verify recovery

6. **PVC Lifecycle**
   - Create KasprApp with packages
   - Verify PVC created with correct labels
   - Check owner references: `kubectl get pvc <name> -o yaml | grep -A5 ownerReferences`
   - Delete KasprApp
   - Verify PVC automatically deleted (cascading deletion)

7. **Storage Class and Size Configuration**
   - Create KasprApp with custom storageClass
   - Verify PVC uses specified storage class
   - Create KasprApp with custom size (e.g., 1Gi)
   - Verify PVC has correct storage size
   - Test with different access modes if supported

8. **Multiple Apps Isolation**
   - Create two KasprApps with different packages
   - Verify each has separate PVC
   - Verify packages don't interfere with each other
   - Check marker files are app-specific

9. **Status Reporting Validation**
   - Monitor status during installation
   - Verify status.pythonPackages.state transitions: Installing → Ready
   - Check status.pythonPackages.installed contains correct package list
   - Verify status.pythonPackages.lastInstallTime populated
   - Check status.pythonPackages.installedBy shows correct pod name

10. **Metrics Validation**
    - Access operator metrics endpoint
    - Verify `kasprop_package_install_duration_seconds` recorded
    - Check `kasprop_package_install_total{result="success"}` incremented
    - Trigger failure, verify `kasprop_package_install_errors_total` incremented
    - Validate metric labels (app_name, namespace)

**Testing Checklist Format:**

Each scenario should include:
- **Prerequisites**: Cluster requirements, operator running
- **Steps**: Numbered list of commands to execute
- **Expected Results**: What should happen at each step
- **Validation Commands**: Specific kubectl/exec commands
- **Success Criteria**: How to know the test passed
- **Cleanup**: Commands to remove test resources

**Validation:**
- [ ] All 10 test scenarios documented with detailed steps
- [ ] Commands tested and verified in local cluster
- [ ] Expected outputs documented (screenshots optional)
- [ ] Troubleshooting tips included for common issues
- [ ] Cleanup procedures documented for each scenario

**Files Changed:**
- New: `docs/testing/python-packages-manual-tests.md`

---

### Task 13: Add Example Manifests and Documentation ✓

**Objective:** Provide examples and user documentation

**Files to Create:**
- `examples/python-packages/basic.yaml`
- `examples/python-packages/with-cache-config.yaml`
- `examples/python-packages/README.md`
- `docs/user-guide/python-packages.md`

**What to Implement:**
1. Basic example: Simple package list
2. Advanced example: Cache config, install policy, resources
3. README: How to use examples
4. User guide: 
   - Overview
   - Quick start
   - Configuration reference
   - Troubleshooting

**Validation:**
- [ ] Examples apply without errors
- [ ] Examples result in working deployments
- [ ] Documentation clear and accurate

**Files Changed:**
- New: `examples/python-packages/basic.yaml`
- New: `examples/python-packages/with-cache-config.yaml`
- New: `examples/python-packages/README.md`
- New: `docs/user-guide/python-packages.md`

---

## Task Dependencies

```
Task 1 (Models/Schemas)
  ↓
Task 2 (Utilities)
  ↓
Task 3 (CRD) ← Can be parallel with Task 1-2
  ↓
Task 4 (Integrate Models)
  ↓
Task 5 (PVC Generation)
  ↓
Task 6 (Init Container)
  ↓
Task 7 (StatefulSet Integration)
  ↓
Task 8 (Handler) ← Task 9 depends on this
  ↓
Task 9 (Status Reporting)
  ↓
Task 10 (Metrics) ← Can be parallel with Task 11
Task 11 (Cleanup) ← Can be parallel with Task 10
  ↓
Task 12 (Manual Testing Guide)
  ↓
Task 13 (Examples & Docs)
```

## Testing Strategy Per Task

### Unit Testing
- After each task that adds code logic (Tasks 1, 2, 4-7)
- Run: `pytest tests/unit/test_python_packages.py -v`

### Manual Testing
- After Task 7 (first E2E capability)
- Create test KasprApp with packages
- Verify init container runs
- Check logs, marker files, PVC

### Integration Testing
- Task 12 (manual testing guide)
- Follow documented scenarios
- Validate in local cluster (minikube/kind)
- Test all documented scenarios

### Smoke Testing
- After Task 13 (examples)
- Apply examples, verify they work
- Test in local cluster

## Rollout Plan

### Local Development
1. Implement tasks 1-13 on feature branch
2. Test each task independently
3. Run full test suite after task 7, 11
4. Manual testing following Task 12 guide

### Dev Cluster Testing
1. Deploy operator to dev cluster
2. Test with real workloads
3. Monitor metrics, logs
4. Test edge cases (failures, scale up/down, etc.)

### Beta Release
1. Feature flag: `PYTHON_PACKAGES_ENABLED` (default: false)
2. Documentation published
3. Beta announcement
4. Gather feedback

### GA Release
1. Address beta feedback
2. Update to default: true
3. GA documentation
4. Monitor adoption metrics

## Success Criteria

After completing all tasks, we should have:

- [ ] pythonPackages field in KasprApp spec
- [ ] Automatic PVC creation for package storage
- [ ] Init container installs packages on first pod only
- [ ] Subsequent pods/restarts skip installation (<1s startup)
- [ ] Package changes trigger rollout
- [ ] Status reflects installation state
- [ ] Prometheus metrics available
- [ ] PVC cleaned up on deletion
- [ ] Manual testing scenarios validated
- [ ] Examples working
- [ ] Documentation complete

## Risk Mitigation

### Risk: RWX Storage Not Available
**Mitigation:** Detect and fall back to emptyDir mode, warn in status

### Risk: Large Packages Cause Timeout
**Mitigation:** Configurable timeout, retries, resource limits

### Risk: Race Conditions in Installation
**Mitigation:** flock-based locking, extensive testing with high replica counts

### Risk: Breaking Changes to Existing Apps
**Mitigation:** All new fields optional, backward compatibility tests

## Review Checkpoints

After completing each task:
1. Self-review code changes
2. Run relevant tests
3. Commit changes with descriptive message
4. Request review before moving to next task

Key review points:
- After Task 4: Data model complete, CRD updated
- After Task 7: Core functionality implemented
- After Task 9: Status reporting working
- After Task 12: Manual testing scenarios validated
- After Task 13: Ready for beta release

---

**Document Status:** Ready for Implementation  
**Last Updated:** 2025-11-28
