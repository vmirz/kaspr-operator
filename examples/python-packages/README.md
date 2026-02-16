# Python Packages Examples

This directory contains example KasprApp manifests demonstrating Python package management capabilities.

## Examples

### 1. Basic Configuration (`basic.yaml`)

Simple example with common packages and default cache settings.

**Features:**
- Basic package list with version constraints
- Default cache configuration (512Mi, ReadWriteMany)
- Standard installation policy

**Use case:** Quick setup for applications needing common packages like requests, pandas, numpy.

```bash
kubectl apply -f basic.yaml
```

### 2. Minimal Configuration (`minimal.yaml`)

Minimal example showing just the required fields.

**Features:**
- Simple package list without versions
- All defaults for cache and installation

**Use case:** Getting started quickly with basic package requirements.

```bash
kubectl apply -f minimal.yaml
```

### 3. Advanced Configuration (`with-cache-config.yaml`)

Comprehensive example showing all available configuration options.

**Features:**
- Multiple packages with version constraints
- Custom storage class and size
- Custom installation policy (retries, timeout)
- Resource limits for init container
- Comments explaining each field
- Examples of private PyPI index configuration (commented out)

**Use case:** Production deployments requiring fine-tuned control over package installation.

```bash
kubectl apply -f with-cache-config.yaml
```

### 4. Private Registry (`private-registry.yaml`)

Install packages from a private PyPI registry with authentication.

**Features:**
- Custom index URL pointing to private registry
- Secret-based credentials (username/password)
- Credentials injected securely via environment variables

**Prerequisites:**
```bash
kubectl apply -f secrets/pypi-credentials.yaml
```

**Use case:** Enterprise environments with private package registries.

```bash
kubectl apply -f private-registry.yaml
```

### 5. Custom Indexes (`custom-indexes.yaml`)

Use multiple package indexes to combine public and private packages.

**Features:**
- Primary index URL with fallback to additional indexes
- Trusted hosts for self-signed certificates
- Packages resolved across multiple registries

**Use case:** Organizations that host internal packages alongside public ones.

```bash
kubectl apply -f custom-indexes.yaml
```

### 6. Install Policy (`install-policy.yaml`)

Aggressive install policy for large packages (ML/DL libraries).

**Features:**
- Higher retry count and longer timeout
- Generous init container resource limits
- Large cache PVC for big packages

**Use case:** ML/Data workloads with tensorflow, pytorch, or similar large packages.

```bash
kubectl apply -f install-policy.yaml
```

### 7. Enterprise Complete (`enterprise-complete.yaml`)

Production-ready configuration combining all Phase 2 features.

**Features:**
- Private registry with authentication
- Multiple indexes (private + public fallback)
- Trusted hosts for self-signed certs
- Production-grade install policy
- Generous resource limits and cache

**Prerequisites:**
```bash
kubectl create secret generic production-pypi-creds \
  --namespace=production \
  --from-literal=username=svc-account \
  --from-literal=password=token-value
```

**Use case:** Full-featured production deployment.

```bash
kubectl apply -f enterprise-complete.yaml
```

## Quick Start

1. **Create a KasprApp with Python packages:**

```yaml
apiVersion: kaspr.io/v1alpha1
kind: KasprApp
metadata:
  name: my-app
spec:
  replicas: 2
  bootstrapServers: "kafka:9092"
  pythonPackages:
    packages:
      - requests
      - pandas>=2.0.0
```

2. **Apply the manifest:**

```bash
kubectl apply -f my-app.yaml
```

3. **Verify package installation:**

```bash
# Check init container logs
kubectl logs my-app-0 -c install-packages

# Check status
kubectl get kasprapp my-app -o jsonpath='{.status.pythonPackages}'

# Verify packages are importable
kubectl exec my-app-0 -- python -c "import requests; print(requests.__version__)"
```

## Configuration Options

### Package Specification

Packages use standard pip version specifiers:

```yaml
packages:
  - package-name              # Latest version
  - package==1.2.3           # Exact version
  - package>=1.2.0           # Minimum version
  - package>=1.2.0,<2.0.0    # Version range
  - package[extra]           # With extras
```

### Cache Configuration

Control the shared package cache:

```yaml
cache:
  enabled: true              # Enable/disable cache (default: true)
  size: "1Gi"               # PVC size (default: 256Mi)
  storageClass: "fast-ssd"  # Storage class (default: cluster default)
  accessMode: ReadWriteMany  # RWX or RWO (default: RWX)
  deleteClaim: true          # Delete PVC with app (default: true)
```

**Cache Benefits:**
- First pod installs packages once
- Subsequent pods/restarts skip installation (<5s startup)
- Scales efficiently with ReadWriteMany access mode
- Persists across pod restarts

### Installation Policy

Control installation behavior:

```yaml
installPolicy:
  retries: 3        # Retry count (default: 3)
  timeout: 600      # Timeout in seconds (default: 600)
  onFailure: block  # "block" or "warn" (default: block)
```

- **block**: Prevent pod startup if installation fails
- **warn**: Log warning but allow pod to start

### Resource Limits

Set init container resources:

```yaml
resources:
  requests:
    cpu: "100m"
    memory: "256Mi"
  limits:
    cpu: "500m"
    memory: "512Mi"
```

## Common Patterns

### Data Science Workloads

```yaml
pythonPackages:
  packages:
    - pandas>=2.0.0
    - numpy>=1.24.0
    - scikit-learn>=1.3.0
    - matplotlib>=3.7.0
    - seaborn>=0.12.0
  cache:
    size: "2Gi"  # Larger cache for ML packages
  resources:
    limits:
      memory: "2Gi"  # More memory for large packages
```

### API/Web Applications

```yaml
pythonPackages:
  packages:
    - requests>=2.31.0
    - httpx>=0.24.0
    - pydantic>=2.0.0
    - python-dotenv>=1.0.0
  cache:
    size: "512Mi"  # Smaller cache for lightweight packages
```

### Database Applications

```yaml
pythonPackages:
  packages:
    - psycopg2-binary>=2.9.0  # PostgreSQL
    - pymongo>=4.0.0          # MongoDB
    - redis[hiredis]>=5.0.0   # Redis
    - sqlalchemy>=2.0.0       # ORM
```

## Troubleshooting

### Check Installation Status

```bash
# View overall status
kubectl get kasprapp my-app -o jsonpath='{.status.pythonPackages}' | jq

# Check init container logs
kubectl logs my-app-0 -c install-packages

# Check for errors
kubectl describe pod my-app-0
```

### Common Issues

**Issue: Init container stuck in "Installing"**
- Check init container logs for network issues
- Verify PyPI access from cluster
- Check resource limits (may need more memory)

**Issue: "Failed" state with timeout error**
- Increase `installPolicy.timeout`
- Increase init container memory limits
- Consider reducing number of packages

**Issue: PVC not created**
- Verify `cache.enabled: true`
- Check storage class exists: `kubectl get storageclass`
- Verify cluster supports requested access mode (RWX/RWO)

**Issue: Packages not found in pods**
- Verify init container completed successfully
- Check PYTHONPATH is set: `kubectl exec my-app-0 -- env | grep PYTHONPATH`
- Verify marker file exists: `kubectl exec my-app-0 -- ls -la /opt/kaspr/packages/.installed-*`

### View Metrics

Access operator metrics endpoint:

```bash
# Port forward to operator
kubectl port-forward -n kaspr-operator deployment/kaspr-operator 8080:8080

# Query package installation metrics
curl http://localhost:8080/metrics | grep kasprop_package_install

# Specific metrics:
# - kasprop_package_install_duration_seconds
# - kasprop_package_install_total
# - kasprop_package_install_errors_total
```

## Advanced Topics

### Private PyPI Index

Use custom package indexes:

```yaml
pythonPackages:
  packages:
    - my-private-package
  indexUrl: "https://pypi.example.com/simple"
  trustedHosts:
    - "pypi.example.com"
```

### Multiple Indexes

Combine public and private packages:

```yaml
pythonPackages:
  packages:
    - requests            # from public PyPI
    - my-company-lib     # from private index
  indexUrl: "https://pypi.org/simple"
  extraIndexUrls:
    - "https://private.example.com/simple"
  trustedHosts:
    - "private.example.com"
```

### Authentication for Private Indexes

Reference a Kubernetes Secret containing PyPI credentials:

```yaml
pythonPackages:
  packages:
    - my-private-package
  indexUrl: "https://pypi.company.com/simple"
  credentials:
    secretRef:
      name: pypi-credentials
      usernameKey: username  # default
      passwordKey: password  # default
```

Create the Secret:
```bash
kubectl create secret generic pypi-credentials \
  --from-literal=username=your-username \
  --from-literal=password=your-password
```

See [private-registry.yaml](private-registry.yaml) and [enterprise-complete.yaml](enterprise-complete.yaml) for full examples.

## Best Practices

1. **Pin versions** for reproducible builds:
   ```yaml
   packages:
     - requests==2.31.0  # Good
     - pandas            # Avoid - version may change
   ```

2. **Use appropriate cache size**:
   - Small packages (requests, redis): 256Mi-512Mi
   - Data science packages (pandas, numpy): 1Gi-2Gi
   - ML packages (tensorflow, pytorch): 5Gi-10Gi

3. **Set resource limits** based on package size:
   - Lightweight: 256Mi memory
   - Medium: 512Mi-1Gi memory
   - Heavy (ML): 2Gi+ memory

4. **Monitor installation time**:
   - First install: Expect 1-5 minutes for typical packages
   - Cached installs: <5 seconds
   - Use metrics to identify slow installations

5. **Handle failures gracefully**:
   - Use `onFailure: warn` for non-critical packages
   - Use `onFailure: block` for essential dependencies

## See Also

- [User Guide](../../docs/user-guide/python-packages.md) - Comprehensive documentation
- [Design Document](../../docs/design/python-packages-phase1-implementation.md) - Implementation details
- [Manual Testing Guide](../../docs/testing/python-packages-manual-tests.md) - Test scenarios
