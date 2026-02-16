# Python Packages — GCS Cache Implementation Plan

## Overview

Add Google Cloud Storage as an alternative cache backend for the Python packages feature. This supplements the existing PVC and emptyDir modes with a cloud object store option, eliminating the need for ReadWriteMany storage classes.

See [python-packages-gcs-cache-analysis.md](python-packages-gcs-cache-analysis.md) for the feasibility analysis that led to this plan.

## Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Scope | GCS-only (not abstract `objectStore`) | Ship faster; extend to S3/Azure later if needed |
| Init container tooling | Python `urllib` (stdlib) | No `curl` in Kaspr base image; `urllib` is always available in Python images; no extra dependencies in app image |
| Concurrency | Accept thundering herd | Simplest approach. All pods install on first cache miss. First to finish uploads. Subsequent starts get cache hits. |
| Auth | Secret ref (SA key JSON) | Works across any K8s environment, not just GKE |
| Auth | Direct SA key mount | User's SA key Secret is mounted as a volume in the init container. Init container authenticates directly with GCS using Python stdlib + `openssl` CLI. No signed URLs, no operator-managed Secrets, no expiry concerns. |
| Max archive size | 1 GB | Prevents unbounded uploads for very large dependency sets |
| Pod volume | Always emptyDir | GCS mode downloads into emptyDir; no PVC created |

## User-Facing API

```yaml
spec:
  pythonPackages:
    packages:
      - requests
      - pandas>=2.0.0
    cache:
      type: gcs                    # "pvc" (default) | "gcs"
      gcs:
        bucket: "my-kaspr-cache"   # Required
        prefix: "kaspr-packages/"  # Optional (default: "kaspr-packages/")
        maxArchiveSize: "1Gi"      # Optional (default: "1Gi", max archive size)
        secretRef:
          name: gcs-sa-key         # Required - K8s Secret with SA key
          key: sa.json             # Optional (default: "sa.json")
      # PVC fields (storageClass, size, accessMode, deleteClaim) are
      # ignored when type=gcs
```

## Architecture

```
┌──────────────────────────────────────────────────────┐
│  Reconciliation (Operator)                           │
│  1. Read GCS config from spec (bucket, prefix, etc.) │
│  2. Mount user's SA key Secret as a volume on init   │
│  3. Generate init script with bucket/prefix/hash     │
│  4. No GCS auth on operator side (no signed URLs)    │
│  5. Volume = emptyDir for packages (no PVC)          │
└───────────────────┬──────────────────────────────────┘
                    │
┌───────────────────▼──────────────────────────────────┐
│  Init Container (same Kaspr image, Python stdlib)    │
│                                                      │
│  1. urllib GET → signed download URL                 │
│     ├─ 200 OK → extract tar.gz → done (cache hit)   │
│     └─ 404    → cache miss, continue                 │
│  2. pip install --target /opt/kaspr/packages         │
│  3. Check archive size < maxArchiveSize              │
│  4. tar czf → urllib PUT → signed upload URL         │
│     └─ Upload failure is non-fatal (logged, ignored) │
└───────────────────┬──────────────────────────────────┘
                    │
┌───────────────────▼──────────────────────────────────┐
│  Main Container                                      │
│  PYTHONPATH includes /opt/kaspr/packages (read-only) │
│  emptyDir volume mount                               │
└──────────────────────────────────────────────────────┘
```

### GCS Object Key Structure

```
gs://<bucket>/<prefix><app-name>/<packages-hash>.tar.gz
```

Example: `gs://my-cache/kaspr-packages/my-app/a1b2c3d4e5f6g7h8.tar.gz`

When the packages hash changes (spec updated), a new key is used and the old archive becomes stale. Users can set GCS lifecycle rules to auto-delete old objects.

### GCS Authentication (Init Container)

The init container authenticates directly with GCS using the mounted SA key. No signed URLs or operator-managed Secrets are involved.

**Flow (all in init container via inline Python):**
1. Read SA key JSON from `/var/run/secrets/gcs/sa.json`
2. Create a JWT: header (`{"alg":"RS256","typ":"JWT"}`) + payload (iss, scope, aud, iat, exp)
3. Sign the JWT with the private key using `openssl dgst -sha256 -sign` (CLI, available in Python base images)
4. POST the signed JWT to `https://oauth2.googleapis.com/token` to exchange for an access token (one network call)
5. Use the access token as a Bearer token for GCS JSON API operations (download/upload)

**Why this works:**
- The SA key is long-lived (user manages rotation) — no expiry concerns
- A fresh access token is created every time the init container runs — always valid
- Only Python stdlib (`json`, `base64`, `time`, `subprocess`, `urllib`) + `openssl` CLI are needed
- `openssl` is available in Python Docker images (required by Python's `ssl` module)
- The operator touches nothing GCS-related — it just mounts the Secret and generates the script

## Implementation Tasks

### Task 1: Models & Schema

**Files modified:**
- `kaspr/types/models/python_packages.py`
- `kaspr/types/schemas/python_packages.py`

**Changes:**

Add new models:
```python
class GCSSecretReference(BaseModel):
    """Reference to a K8s Secret containing GCS SA key."""
    name: str                    # Secret name
    key: Optional[str]           # Key within Secret (default: "sa.json")

class GCSCacheConfig(BaseModel):
    """GCS cache configuration."""
    bucket: str
    prefix: Optional[str]        # Default: "kaspr-packages/"
    max_archive_size: Optional[str]  # Default: "1Gi"
    secret_ref: GCSSecretReference
```

Add fields to existing `PythonPackagesCache`:
```python
class PythonPackagesCache(BaseModel):
    type: Optional[str]          # "pvc" | "gcs" (default: "pvc" when enabled=true)
    enabled: Optional[bool]
    storage_class: Optional[str]
    size: Optional[str]
    access_mode: Optional[str]
    delete_claim: Optional[bool]
    gcs: Optional[GCSCacheConfig]  # New
```

Add corresponding Marshmallow schemas with validation:
- `type` must be `"pvc"` or `"gcs"`
- When `type: gcs`: `gcs.bucket` and `gcs.secretRef.name` are required
- When `type: gcs`: `enabled` is implicitly `true`

### Task 2: CRD Update

**Files modified:**
- `crds/kasprapp.crd.yaml`

**Changes:**

Add under `cache.properties`:
```yaml
type:
  type: string
  enum:
    - pvc
    - gcs
  default: pvc
  description: Cache backend type.
gcs:
  type: object
  description: GCS cache configuration. Required when type is "gcs".
  properties:
    bucket:
      type: string
      description: GCS bucket name.
    prefix:
      type: string
      default: "kaspr-packages/"
      description: Key prefix for cached archives.
    maxArchiveSize:
      type: string
      default: "1Gi"
      description: Maximum archive size to upload. Archives exceeding this are skipped.
    secretRef:
      type: object
      description: Reference to a Secret containing GCS service account key JSON.
      properties:
        name:
          type: string
          description: Name of the Secret.
        key:
          type: string
          default: sa.json
          description: Key within the Secret containing the JSON file.
      required:
        - name
  required:
    - bucket
    - secretRef
```

### Task 3: GCS Helper Module

**Files created:**
- `kaspr/utils/gcs.py`

**Functions:**

```python
def build_gcs_object_key(prefix: str, app_name: str, packages_hash: str) -> str:
    """Build the GCS object key for a packages archive.
    
    Returns: e.g. "kaspr-packages/my-app/a1b2c3d4e5f6g7h8.tar.gz"
    """

def parse_size_to_bytes(size_str: str) -> int:
    """Parse K8s-style size string to bytes. E.g. '1Gi' -> 1073741824."""

def generate_gcs_auth_python_script() -> str:
    """Generate inline Python code for GCS authentication.
    
    The generated code:
    1. Reads SA key from mounted file
    2. Creates JWT (header + payload)
    3. Signs JWT using openssl CLI (subprocess)
    4. Exchanges JWT for access token via oauth2.googleapis.com
    5. Provides a get_access_token() function for the bash script to call
    """

def generate_gcs_download_python_script(bucket: str, object_key: str) -> str:
    """Generate inline Python code for downloading an archive from GCS.
    
    Uses access token from generate_gcs_auth_python_script().
    Returns exit code 0 on success (cache hit), 1 on 404 (cache miss).
    """

def generate_gcs_upload_python_script(
    bucket: str, object_key: str, archive_path: str
) -> str:
    """Generate inline Python code for uploading an archive to GCS.
    
    Uses access token from generate_gcs_auth_python_script().
    Non-fatal: logs errors but doesn't fail.
    """
```

**No operator-side GCS dependency.** The `google-cloud-storage` package is NOT needed. All GCS operations happen inside the init container using Python stdlib + `openssl`.

### Task 4: Init Container Script Generator

**Files modified:**
- `kaspr/utils/python_packages.py`

**Add function:**

```python
def generate_gcs_install_script(
    spec: PythonPackagesSpec,
    cache_path: str = "/opt/kaspr/packages",
    timeout: int = 600,
    retries: int = 3,
    packages_hash: str = None,
    max_archive_size_bytes: int = 1073741824,  # 1Gi
) -> str:
```

The generated bash script uses **inline Python** (via `python3 -c "..."`) for HTTP operations since `curl` is not available:

```bash
#!/bin/bash
set -e

# 1. Try downloading cached archive via Python urllib
python3 -c "
import urllib.request, sys
try:
    urllib.request.urlretrieve('$GCS_DOWNLOAD_URL', '/tmp/packages.tar.gz')
    print('Cache hit')
except urllib.error.HTTPError as e:
    if e.code == 404:
        print('Cache miss')
        sys.exit(1)
    raise
"

if [ $? -eq 0 ]; then
    tar xzf /tmp/packages.tar.gz -C /opt/kaspr/packages
    rm -f /tmp/packages.tar.gz
    exit 0
fi

# 2. Cache miss — install packages via pip
install_packages  # (reuses existing retry/error logic)

# 3. Archive and upload (non-fatal)
archive_size=$(tar czf /tmp/packages.tar.gz -C /opt/kaspr/packages . && stat -f%z /tmp/packages.tar.gz 2>/dev/null || stat -c%s /tmp/packages.tar.gz)
if [ "$archive_size" -le MAX_ARCHIVE_SIZE ]; then
    python3 -c "
import urllib.request
req = urllib.request.Request('$GCS_UPLOAD_URL', method='PUT',
    data=open('/tmp/packages.tar.gz','rb').read(),
    headers={'Content-Type':'application/gzip'})
urllib.request.urlopen(req)
" 2>/dev/null && echo "Uploaded to GCS cache" || echo "GCS upload failed (non-fatal)"
else
    echo "Archive size ${archive_size} exceeds max (MAX_ARCHIVE_SIZE bytes), skipping upload"
fi
rm -f /tmp/packages.tar.gz
```

Note: The above is a simplified sketch. The actual generator will reuse the existing `_build_pip_install_cmd()`, `_build_error_detection_block()`, and retry logic patterns from `generate_install_script()` / `generate_emptydir_install_script()`.

### Task 5: Resource Generation

**Files modified:**
- `kaspr/resources/kasprapp.py`

**Changes:**

5.1 — **Constants**: Add `DEFAULT_GCS_PREFIX`, `DEFAULT_GCS_SECRET_KEY`, `DEFAULT_GCS_MAX_ARCHIVE_SIZE`

5.2 — **`should_create_packages_pvc()`**: Return `False` when `cache.type == "gcs"`

5.3 — **`prepare_packages_init_container()`**: Add third branch:
```python
elif cache_type == "gcs":
    # Mount SA key Secret, build GCS-aware script
    script = generate_gcs_install_script(...)
```

The init container gets an additional volume mount for the SA key:
```python
V1VolumeMount(
    name="gcs-sa-key",
    mount_path="/var/run/secrets/gcs",
    read_only=True,
)
```

5.4 — **`prepare_python_packages_env_vars()`**: When cache type is GCS, add `GCS_BUCKET` and `GCS_OBJECT_KEY` as plain env vars (these are stable values derived from spec, won't change between reconciliations unless the spec changes).

5.5 — **`prepare_volumes()`**: GCS mode:
- emptyDir for packages (already handled by existing `else` branch when `should_create_packages_pvc()` returns `False`)
- Add SA key Secret volume:
```python
V1Volume(
    name="gcs-sa-key",
    secret=V1SecretVolumeSource(
        secret_name=gcs_config.secret_ref.name,
        items=[V1KeyToPath(
            key=gcs_config.secret_ref.key or "sa.json",
            path="sa.json"
        )]
    )
)
```

5.6 — **`prepare_statefulset_watch_fields()`**: No changes needed. The existing method only tracks `PACKAGES_HASH` from the init container. GCS-related env vars (`GCS_BUCKET`, `GCS_OBJECT_KEY`) are stable and derived from the spec so they naturally change only when the spec changes.

5.7 — **`sync_python_packages_pvc()`**: Early return when `cache.type == "gcs"` (no PVC to sync)

5.8 — **`unite()`**: Skip PVC adoption when `cache.type == "gcs"`

5.9 — **Status**: Report `cache_mode: "gcs"` in status

### Task 6: Tests

**Files modified:**
- `tests/unit/test_python_packages.py`

**Files created:**
- `tests/unit/test_gcs.py`

**Test cases:**

Model & Schema:
- `GCSCacheConfig` / `GCSSecretReference` serialization
- `PythonPackagesCache` with `type: gcs` round-trip
- Validation: `type: gcs` requires `gcs.bucket` and `gcs.secretRef.name`
- Validation: `type` must be `"pvc"` or `"gcs"`
- PVC fields ignored when `type: gcs`

GCS utility:
- `build_gcs_object_key()` produces correct key format
- `parse_size_to_bytes()` handles Ki/Mi/Gi/Ti suffixes
- `generate_gcs_auth_python_script()` produces valid Python code
- `generate_gcs_download_python_script()` handles 200 (hit) and 404 (miss)
- `generate_gcs_upload_python_script()` handles errors non-fatally

Script:
- `generate_gcs_install_script()` contains Python auth + download/upload code
- Script reads SA key from mounted path
- Script checks archive size against max
- Script has correct fallback to pip install on 404

Resource generation:
- `should_create_packages_pvc()` returns `False` for GCS type
- Init container uses emptyDir volume when GCS
- Init container has SA key volume mount at `/var/run/secrets/gcs/`
- No PVC created when `type: gcs`
- Env vars include stable `GCS_BUCKET` and `GCS_OBJECT_KEY` (derived from spec)
- `prepare_statefulset_watch_fields()` unchanged

### Task 7: Documentation

**Files modified:**
- `docs/user-guide/python-packages.md`

**Files created or modified:**
- `examples/python-packages/gcs-cache.yaml` (new example)

**Sections to add:**
- GCS Cache overview and when to use it
- Prerequisites (GCS bucket, SA key Secret)
- Configuration reference for `cache.gcs.*` fields
- Example YAML
- Limitations (thundering herd on first deploy, 1-hour URL TTL, 1Gi max archive)
- Troubleshooting (expired URLs, auth errors, archive too large)

## Files Changed Summary

| File | Change |
|---|---|
| `requirements.txt` | No changes needed (no GCS dependency in operator) |
| `kaspr/types/models/python_packages.py` | Add `GCSSecretReference`, `GCSCacheConfig`; add `type` + `gcs` to `PythonPackagesCache` |
| `kaspr/types/schemas/python_packages.py` | Add GCS schemas + validation rules |
| `crds/kasprapp.crd.yaml` | Add `type`, `gcs` fields under `cache` |
| `kaspr/utils/gcs.py` | **New** — object key builder, size parser, Python script generators for GCS auth/download/upload |
| `kaspr/utils/python_packages.py` | Add `generate_gcs_install_script()` |
| `kaspr/resources/kasprapp.py` | GCS branch in init container, volumes (emptyDir + SA key), PVC sync, unite, status, env vars |
| `tests/unit/test_python_packages.py` | GCS model/schema/script tests |
| `tests/unit/test_gcs.py` | **New** — GCS utility tests |
| `docs/user-guide/python-packages.md` | GCS cache section |
| `examples/python-packages/gcs-cache.yaml` | **New** — example YAML |

## Known Limitations

1. **Thundering herd**: On first deploy with N replicas and an empty cache, all N pods install packages independently. The first to finish uploads the archive. Wastes extra CPU/network once, but is functionally correct. Subsequent restarts/scale-ups get cache hits.

2. **`openssl` CLI dependency**: The init container relies on `openssl` for JWT signing. This is available in Python Docker images (required by Python's `ssl` module) but should be verified for the Kaspr base image (`twmvmirz/py3.9-rocksdb8.1.1`). If missing, we'd need an alternative signing approach.

3. **Max archive size (1 Gi default)**: Archives exceeding the configured limit are not uploaded. The pod still starts successfully (packages are installed locally), but the cache is not populated. Users with large dependency sets should increase this or accept per-pod installation.

4. **Upload is best-effort**: GCS upload failure (network issues, permission errors) is logged but does not block pod startup. The next pod will simply reinstall and try uploading again.

5. **No automatic cleanup of stale archives**: When the packages hash changes, old archives remain in GCS. Users should configure GCS object lifecycle policies to auto-delete old objects, or clean up manually.
