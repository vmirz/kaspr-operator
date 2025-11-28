# Phase 1 Task 4: Testing Plan

## Manual Testing

### 1. Apply Minimal Example
```bash
kubectl apply -f examples/app/python-packages-minimal.yaml
```

**Expected Results:**
- KasprApp resource created successfully
- StatefulSet created with 2 PVCs in volume claim templates:
  - `minimal-packages-example-storage` (main storage)
  - `minimal-packages-example-packages` (package cache)
- Init container `install-packages` runs before main container
- Packages installed to `/opt/kaspr/packages`
- Main container has PYTHONPATH set to `/opt/kaspr/packages:${PYTHONPATH}`

**Verification Commands:**
```bash
# Check KasprApp status
kubectl get kasprapp minimal-packages-example -o yaml

# Check StatefulSet
kubectl get statefulset minimal-packages-example -o yaml

# Check PVCs
kubectl get pvc | grep minimal-packages-example

# Check pod init containers
kubectl get pod minimal-packages-example-0 -o jsonpath='{.spec.initContainers[*].name}'

# Check init container logs
kubectl logs minimal-packages-example-0 -c install-packages

# Check PYTHONPATH in main container
kubectl exec minimal-packages-example-0 -- printenv PYTHONPATH

# Verify packages installed
kubectl exec minimal-packages-example-0 -- ls -la /opt/kaspr/packages
kubectl exec minimal-packages-example-0 -- python -c "import pandas; import requests; print('Success!')"
```

### 2. Apply Full Example with Custom Configuration
```bash
kubectl apply -f examples/app/python-packages.yaml
```

**Expected Results:**
- Package cache PVC size is 512Mi (custom size)
- Storage class is "fast-ssd" (custom)
- Init container has custom resource limits
- Install retries set to 5
- Install timeout set to 900 seconds

**Verification Commands:**
```bash
# Check PVC size and storage class
kubectl get pvc python-packages-example-packages -o jsonpath='{.spec.resources.requests.storage}{"\n"}{.spec.storageClassName}'

# Check init container resources
kubectl get statefulset python-packages-example -o jsonpath='{.spec.template.spec.initContainers[0].resources}'

# Check init container command for retries and timeout
kubectl get statefulset python-packages-example -o jsonpath='{.spec.template.spec.initContainers[0].command}' | grep -E "retries|timeout"
```

### 3. Test Package Change Detection
```bash
# Apply initial configuration
kubectl apply -f examples/app/python-packages-minimal.yaml

# Wait for pod to be ready
kubectl wait --for=condition=ready pod/minimal-packages-example-0 --timeout=300s

# Get current pod creation time
BEFORE=$(kubectl get pod minimal-packages-example-0 -o jsonpath='{.metadata.creationTimestamp}')

# Update packages list
cat << EOF | kubectl apply -f -
apiVersion: kaspr.io/v1
kind: KasprApp
metadata:
  name: minimal-packages-example
  namespace: default
spec:
  replicas: 1
  image: my-registry/kaspr-app:latest
  kafka:
    bootstrapServers: "kafka-broker:9092"
    topics:
      - input-topic
  storage:
    size: "1Gi"
  pythonPackages:
    packages:
      - "pandas"
      - "requests"
      - "numpy"  # Added new package
EOF

# Wait for pod restart
sleep 5
kubectl wait --for=condition=ready pod/minimal-packages-example-0 --timeout=300s

# Get new pod creation time
AFTER=$(kubectl get pod minimal-packages-example-0 -o jsonpath='{.metadata.creationTimestamp}')

# Verify pod was recreated (timestamps differ)
echo "Before: $BEFORE"
echo "After: $AFTER"

# Verify new package installed
kubectl exec minimal-packages-example-0 -- python -c "import numpy; print('NumPy installed successfully!')"
```

**Expected Results:**
- Pod is recreated (different creation timestamp)
- New package (numpy) is installed
- Packages hash annotation on StatefulSet changes

### 4. Test Cache Disabled Scenario
```bash
cat << EOF | kubectl apply -f -
apiVersion: kaspr.io/v1
kind: KasprApp
metadata:
  name: no-cache-example
  namespace: default
spec:
  replicas: 1
  image: my-registry/kaspr-app:latest
  kafka:
    bootstrapServers: "kafka-broker:9092"
    topics:
      - input-topic
  storage:
    size: "1Gi"
  pythonPackages:
    packages:
      - "pandas"
    cache:
      enabled: false  # Disable cache
EOF
```

**Expected Results:**
- No packages PVC created
- No init container added
- PYTHONPATH not set
- Packages not installed

**Verification Commands:**
```bash
# Should not find packages PVC
kubectl get pvc | grep no-cache-example-packages || echo "No packages PVC (expected)"

# Should not have init container
kubectl get pod no-cache-example-0 -o jsonpath='{.spec.initContainers}' | grep "install-packages" || echo "No init container (expected)"

# PYTHONPATH should not include /opt/kaspr/packages
kubectl exec no-cache-example-0 -- printenv PYTHONPATH
```

## Unit Testing

### Tests to Create in `tests/unit/test_kasprapp_resource.py`

#### 1. Test prepare_packages_pvc()
```python
def test_prepare_packages_pvc_with_defaults():
    """Test PVC generation with default values"""
    # Setup: KasprApp with minimal packages config
    # Assert: PVC created with correct name, size (256Mi), access mode (ReadWriteMany)

def test_prepare_packages_pvc_with_custom_config():
    """Test PVC generation with custom configuration"""
    # Setup: KasprApp with custom cache size, storage class, access mode
    # Assert: PVC respects custom values

def test_prepare_packages_pvc_cache_disabled():
    """Test that no PVC is created when cache is disabled"""
    # Setup: KasprApp with cache.enabled = false
    # Assert: prepare_packages_pvc() returns None

def test_prepare_packages_pvc_no_packages():
    """Test that no PVC is created when python_packages is None"""
    # Setup: KasprApp without python_packages field
    # Assert: prepare_packages_pvc() returns None
```

#### 2. Test prepare_packages_init_container()
```python
def test_prepare_packages_init_container_basic():
    """Test init container generation with basic config"""
    # Setup: KasprApp with packages list
    # Assert: Init container created with correct name, image, volume mounts

def test_prepare_packages_init_container_custom_resources():
    """Test init container with custom resource limits"""
    # Setup: KasprApp with resources.limits and resources.requests
    # Assert: Init container has correct resource configuration

def test_prepare_packages_init_container_custom_policy():
    """Test init container with custom install policy"""
    # Setup: KasprApp with custom retries and timeout
    # Assert: Init container command includes correct retry and timeout values

def test_prepare_packages_init_container_cache_disabled():
    """Test that no init container is created when cache is disabled"""
    # Setup: KasprApp with cache.enabled = false
    # Assert: prepare_packages_init_container() returns None
```

#### 3. Test prepare_packages_volume_mounts()
```python
def test_prepare_packages_volume_mounts():
    """Test volume mount generation for main container"""
    # Setup: KasprApp with packages enabled
    # Assert: Volume mount list contains /opt/kaspr/packages mount with read_only=True

def test_prepare_packages_volume_mounts_empty():
    """Test that no volume mounts when cache disabled"""
    # Setup: KasprApp with cache.enabled = false
    # Assert: Empty list returned
```

#### 4. Test prepare_env_vars()
```python
def test_prepare_env_vars_with_pythonpath():
    """Test that PYTHONPATH is added when packages enabled"""
    # Setup: KasprApp with python_packages
    # Assert: PYTHONPATH environment variable in list with correct value

def test_prepare_env_vars_no_pythonpath():
    """Test that PYTHONPATH is not added when cache disabled"""
    # Setup: KasprApp with cache.enabled = false
    # Assert: PYTHONPATH not in environment variables list
```

#### 5. Test prepare_pod_spec()
```python
def test_prepare_pod_spec_with_init_containers():
    """Test that init containers are added to pod spec"""
    # Setup: KasprApp with python_packages
    # Assert: Pod spec includes init_containers with install-packages container

def test_prepare_pod_spec_no_init_containers():
    """Test that init containers not added when packages disabled"""
    # Setup: KasprApp without python_packages or cache disabled
    # Assert: Pod spec init_containers is None or empty
```

#### 6. Test prepare_statefulset()
```python
def test_prepare_statefulset_with_packages_pvc():
    """Test that packages PVC is in volume claim templates"""
    # Setup: KasprApp with python_packages
    # Assert: StatefulSet has 2 PVCs in volume_claim_templates

def test_prepare_statefulset_packages_hash_annotation():
    """Test that packages hash annotation is added"""
    # Setup: KasprApp with python_packages
    # Assert: StatefulSet annotations include packages-hash

def test_prepare_statefulset_no_packages_pvc():
    """Test that packages PVC not added when cache disabled"""
    # Setup: KasprApp with cache.enabled = false
    # Assert: StatefulSet has only 1 PVC (main storage)
```

#### 7. Test Cached Properties
```python
def test_packages_pvc_cached_property():
    """Test packages_pvc cached property"""
    # Setup: KasprApp with python_packages
    # Assert: Property returns PVC, subsequent calls return cached value

def test_packages_init_container_cached_property():
    """Test packages_init_container cached property"""
    # Setup: KasprApp with python_packages
    # Assert: Property returns container, subsequent calls return cached value
```

## Integration Testing

### Test Scenarios

1. **Basic Integration**: Deploy KasprApp with python packages and verify all resources created
2. **Package Installation**: Verify packages are actually installed and importable
3. **Cache Persistence**: Restart pod, verify packages not reinstalled (cached)
4. **Package Update**: Change packages list, verify new packages installed
5. **Resource Limits**: Verify init container respects resource limits
6. **Error Handling**: Test with invalid package names, verify retries work
7. **Storage Class**: Test with different storage classes
8. **Multi-Replica**: Deploy with multiple replicas, verify each has own packages

## Cleanup
```bash
kubectl delete kasprapp minimal-packages-example
kubectl delete kasprapp python-packages-example
kubectl delete kasprapp no-cache-example
```

## Success Criteria
- ✅ All manual tests pass
- ✅ All unit tests pass
- ✅ No errors or warnings in operator logs
- ✅ Packages installed correctly and importable
- ✅ Cache works correctly (no reinstall on pod restart)
- ✅ Change detection works (pod restart on package change)
- ✅ Resource limits respected
- ✅ Custom configuration respected
