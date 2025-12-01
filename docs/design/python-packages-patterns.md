# Python Packages Implementation - Code Patterns Reference

This document outlines the established code patterns in `kaspr/resources/kasprapp.py` that must be followed when implementing the Python packages feature.

## Pattern: Lazy K8s Resource Construction

### 1. Private Attribute Declaration

At the top of the `KasprApp` class, declare private attributes initialized to `None`:

```python
class KasprApp(BaseResource):
    # ... existing attributes ...
    
    # Python packages resources
    _python_packages_pvc: V1PersistentVolumeClaim = None
    _python_packages_pvc_name: str = None
    _python_packages_init_container: V1Container = None
    _python_packages_hash: str = None
```

### 2. Prepare Method

Create a `prepare_*()` method that constructs the Kubernetes resource:

```python
def prepare_python_packages_pvc(self) -> V1PersistentVolumeClaim:
    """Build python packages PVC resource."""
    annotations = {}
    pvc = V1PersistentVolumeClaim(
        api_version="v1",
        kind="PersistentVolumeClaim",
        metadata=V1ObjectMeta(
            name=self.python_packages_pvc_name,
            namespace=self.namespace,
            labels=self.labels.as_dict(),
            annotations=annotations,
        ),
        spec=V1PersistentVolumeClaimSpec(
            access_modes=["ReadWriteMany"],
            resources=V1ResourceRequirements(
                requests={"storage": "5Gi"}  # or from spec
            ),
            storage_class_name=None,  # or from spec
        ),
    )
    # Add hash annotation for drift detection
    annotations.update(
        self.prepare_hash_annotation(self.prepare_python_packages_pvc_hash(pvc))
    )
    return pvc
```

### 3. Cached Property Accessor

Use `@cached_property` decorator to lazily construct the resource:

```python
@cached_property
def python_packages_pvc(self) -> V1PersistentVolumeClaim:
    if self._python_packages_pvc is None:
        self._python_packages_pvc = self.prepare_python_packages_pvc()
    return self._python_packages_pvc
```

### 4. Hash Computation

Add a hash method for drift detection:

```python
def prepare_python_packages_pvc_hash(self, pvc: V1PersistentVolumeClaim) -> str:
    """Compute hash for PVC resource."""
    return self.compute_hash(pvc.to_dict())
```

## Pattern: Resource Synchronization

Follow the `sync_*()` pattern used by `sync_service()`, `sync_settings_config_map()`, etc:

```python
async def sync_python_packages_pvc(self):
    """Check current state of python packages PVC and create/patch if needed."""
    # Only sync if feature is enabled
    if not self.should_create_packages_pvc():
        return
    
    pvc: V1PersistentVolumeClaim = await self.fetch_persistent_volume_claim(
        self.core_v1_api, self.python_packages_pvc_name, self.namespace
    )
    
    if not pvc:
        # Instrument create operation
        sensor_state = self.sensor.on_resource_sync_start(
            self.cluster, self.cluster, self.python_packages_pvc.metadata.name, 
            self.namespace, "python_packages_pvc"
        )
        
        success = True
        try:
            await self.create_persistent_volume_claim(
                self.core_v1_api, self.namespace, self.python_packages_pvc
            )
        except Exception:
            success = False
            raise
        finally:
            self.sensor.on_resource_sync_complete(
                self.cluster, self.cluster, self.python_packages_pvc.metadata.name,
                self.namespace, "python_packages_pvc", sensor_state, "create", success
            )
    else:
        # Check for drift
        actual = self.prepare_python_packages_pvc_watch_fields(pvc)
        desired = self.prepare_python_packages_pvc_watch_fields(self.python_packages_pvc)
        actual_hash = self.compute_hash(actual)
        desired_hash = self.compute_hash(desired)
        
        if actual_hash != desired_hash:
            # Detect drift
            self.sensor.on_resource_drift_detected(
                self.cluster, self.cluster, self.python_packages_pvc.metadata.name,
                self.namespace, "python_packages_pvc", ["spec"]
            )
            
            # Instrument patch operation
            sensor_state = self.sensor.on_resource_sync_start(
                self.cluster, self.cluster, self.python_packages_pvc.metadata.name,
                self.namespace, "python_packages_pvc"
            )
            
            success = True
            try:
                await self.patch_persistent_volume_claim(
                    self.core_v1_api,
                    self.python_packages_pvc_name,
                    self.namespace,
                    pvc=self.prepare_python_packages_pvc_patch(self.python_packages_pvc),
                )
            except Exception:
                success = False
                raise
            finally:
                self.sensor.on_resource_sync_complete(
                    self.cluster, self.cluster, self.python_packages_pvc.metadata.name,
                    self.namespace, "python_packages_pvc", sensor_state, "patch", success
                )
```

## Pattern: Prepare Patch and Watch Fields

### Patch Method

Define which fields can be patched (some K8s resources have immutable fields):

```python
def prepare_python_packages_pvc_patch(self, pvc: V1PersistentVolumeClaim) -> Dict:
    """Prepare patch for PVC resource.
    A PVC can only have certain fields updated via patch.
    This method should be used to prepare the patch.
    """
    patch = []
    
    # Example: Update storage size (if supported by storage class)
    if pvc.spec.resources and pvc.spec.resources.requests:
        patch.append({
            "op": "replace",
            "path": "/spec/resources/requests/storage",
            "value": pvc.spec.resources.requests.get("storage"),
        })
    
    return patch
```

### Watch Fields Method

Define which fields to monitor for drift:

```python
def prepare_python_packages_pvc_watch_fields(self, pvc: V1PersistentVolumeClaim) -> Dict:
    """
    Prepare fields of interest when comparing actual vs desired state.
    These fields are tracked for changes made outside the operator and are used to
    determine if a patch is needed.
    """
    return {
        "spec": {
            "accessModes": pvc.spec.access_modes,
            "resources": {
                "requests": {
                    "storage": pvc.spec.resources.requests.get("storage")
                }
            },
            "storageClassName": pvc.spec.storage_class_name,
        },
    }
```

## Pattern: Spec Field Integration

### In `from_spec()` Method

Add the new spec field assignment:

```python
@classmethod
def from_spec(
    self,
    name: str,
    kind: str,
    namespace: str,
    spec: KasprAppSpec,
    annotations: Optional[Dict[str, str]] = None,
    logger: Logger = None,
) -> "KasprApp":
    app = KasprApp(name, kind, namespace, self.KIND)
    # ... existing assignments ...
    app.python_packages = spec.python_packages  # Add this line
    return app
```

### Access Pattern

Access spec fields directly as instance attributes:

```python
def should_create_packages_pvc(self) -> bool:
    """Check if python packages PVC should be created."""
    if not hasattr(self, 'python_packages') or self.python_packages is None:
        return False
    
    # Check if cache is enabled (default: True)
    if self.python_packages.cache:
        return self.python_packages.cache.enabled
    
    return True  # Default to enabled if cache config not specified
```

## Pattern: Conditional Resource Inclusion

### In Volume Preparation

```python
def prepare_volumes(self) -> List[V1Volume]:
    volumes = []
    volumes.extend(self.prepare_agent_volumes())
    volumes.extend(self.prepare_webview_volumes())
    volumes.extend(self.prepare_table_volumes())
    volumes.extend(self.prepare_task_volumes())
    
    # Conditionally add python packages volume
    if self.should_mount_python_packages():
        volumes.append(self.prepare_python_packages_volume())
    
    volumes.extend(self.prepare_pod_template_volumes())
    return volumes
```

### In Volume Mounts

```python
def prepare_volume_mounts(self) -> List[V1VolumeMount]:
    volume_mounts = []
    volume_mounts.extend([
        V1VolumeMount(
            name=self.persistent_volume_claim_name,
            mount_path=self.table_dir_path,
        ),
        *self.prepare_agent_volume_mounts(),
        *self.prepare_webview_volume_mounts(),
        *self.prepare_table_volume_mounts(),
        *self.prepare_task_volume_mounts(),
    ])
    
    # Conditionally add python packages mount
    if self.should_mount_python_packages():
        volume_mounts.append(self.prepare_python_packages_volume_mount())
    
    volume_mounts.extend(self.prepare_container_template_volume_mounts())
    return volume_mounts
```

### In Pod Spec

```python
def prepare_pod_spec(self) -> V1PodSpec:
    """Build pod spec for kaspr app."""
    # Conditionally add init containers
    init_containers = []
    if self.should_mount_python_packages():
        init_containers.append(self.python_packages_init_container)
    
    return V1PodSpec(
        image_pull_secrets=self.template_pod.image_pull_secrets,
        security_context=self.template_pod.security_context,
        # ... other fields ...
        init_containers=init_containers if init_containers else None,
        containers=[self.kaspr_container],
        volumes=self.volumes,
    )
```

## Pattern: Environment Variables

Add to `prepare_env_vars()`:

```python
def prepare_env_vars(self) -> List[V1EnvVar]:
    env_vars = []
    
    # ... existing env var preparation ...
    
    # Conditionally add python packages env vars
    if self.should_mount_python_packages():
        env_vars.append(V1EnvVar(
            name="PYTHONPATH",
            value="/packages/site-packages:${PYTHONPATH}"
        ))
        env_vars.append(V1EnvVar(
            name="PYTHON_PACKAGES_HASH",
            value=self.python_packages_hash
        ))
    
    return env_vars
```

## Pattern: Synchronize Method

Update the main `synchronize()` method:

```python
async def synchronize(self) -> "KasprApp":
    """Compare current state with desired state for all child resources and create/patch as needed."""
    await self.sync_auth_credentials()
    await self.sync_service()
    await self.sync_headless_service()
    await self.sync_service_account()
    await self.sync_settings_config_map()
    await self.sync_python_packages_pvc()  # Add this line
    await self.sync_hpa()
    await self.sync_stateful_set()
```

## Key Principles

1. **Lazy Construction**: Resources are only constructed when accessed via cached_property
2. **Hash Annotations**: All resources include hash annotations for drift detection
3. **Conditional Logic**: Check `should_*()` methods before creating optional resources
4. **Sensor Instrumentation**: All sync operations are instrumented with sensor callbacks
5. **Error Handling**: Use try/except/finally for proper success/failure tracking
6. **Backwards Compatibility**: All new fields are optional, existing apps continue to work
7. **Consistent Naming**: Follow `prepare_*()`, `sync_*()`, pattern naming

## Common Mistakes to Avoid

❌ **Don't** create resources directly without using cached_property pattern
❌ **Don't** forget to add sensor instrumentation to sync methods
❌ **Don't** forget hash annotations for drift detection
❌ **Don't** access spec fields without checking if they exist first
❌ **Don't** forget to update `from_spec()` when adding new spec fields
❌ **Don't** add resources to StatefulSet without conditional checks

✅ **Do** follow the established patterns consistently
✅ **Do** include proper error handling
✅ **Do** add comprehensive docstrings
✅ **Do** test backwards compatibility
✅ **Do** use helper methods like `should_*()` for conditional logic
