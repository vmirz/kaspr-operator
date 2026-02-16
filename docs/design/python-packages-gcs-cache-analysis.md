# GCS as Python Packages Cache — Feasibility Analysis

**Status:** Explored / Not Recommended as Default  
**Date:** 2026-02-16  
**Context:** Evaluate Google Cloud Storage as an alternative backing store for the Python packages cache, which currently relies on ReadWriteMany PVCs.

---

## Current PVC Cache Architecture

The existing system uses a **ReadWriteMany PVC** shared across all pods in a StatefulSet:

1. All pods mount the same PVC at `/opt/kaspr/packages`
2. The **first pod** to start acquires an exclusive `flock` on `.install.lock`, installs packages, writes a marker file (`.installed-<hash>`), then releases the lock
3. **Subsequent pods** acquire the lock, see the marker file, skip installation, and start in <5s
4. Hash-based invalidation detects spec changes and triggers reinstall

The `flock` mechanism works because RWX PVCs expose a POSIX filesystem — all init containers see the same files and the same lock.

---

## Proposed GCS Cache Architecture

Replace the PVC with a GCS bucket as the backing store for cached packages.

### Conceptual Flow

1. Init container starts, checks GCS for an archive keyed by the packages hash (e.g., `gs://bucket/kaspr-packages/<app-name>/<hash>.tar.gz`)
2. If found → download and extract to local (emptyDir) volume → done
3. If not found → install packages via pip into local emptyDir → upload archive to GCS → done
4. Main container mounts the local emptyDir (read-only)

### CRD Shape

```yaml
cache:
  type: gcs              # new field: "pvc" (default) | "gcs"
  gcs:
    bucket: "my-kaspr-packages"
    prefix: "cache/"      # optional key prefix
    secretRef:
      name: gcs-credentials  # SA key or Workload Identity annotation
```

---

## Pros

| | |
|---|---|
| **No RWX dependency** | Many cloud environments don't have great RWX storage (e.g., GKE default `pd-standard` is RWO only). GCS removes the need for Filestore/NFS provisioners entirely. |
| **Cross-cluster sharing** | A GCS bucket can be shared across multiple clusters, regions, or environments. Deploy the same app in staging and prod — the cache is warm from the first install. |
| **No storage class headaches** | PVC-based caching requires users to set up the right storage class with RWX support. GCS "just works" with a bucket + credentials. |
| **Unlimited size** | No need to pre-size a PVC. Packages grow/shrink freely. No PVC expansion logic needed. |
| **Durability** | GCS has 99.999999999% durability vs. PVCs tied to a single disk/NFS share. |
| **Simpler cleanup** | No orphaned PVCs. Object lifecycle policies can auto-expire old cache entries. |

## Cons

| | |
|---|---|
| **No native file-locking** | GCS has no equivalent to `flock`. When many pods start simultaneously, you can't prevent all of them from installing packages concurrently. (See locking analysis below.) |
| **Network latency** | Downloading a tarball from GCS adds ~5-30s depending on package size, vs. near-instant for a PVC that's already mounted. For large ML packages (5-10GB), this could be significant. |
| **Egress costs** | Every pod start downloads from GCS. At scale (many restarts, many replicas), egress costs can add up, especially cross-region. |
| **Auth complexity** | Requires either GCP Workload Identity (recommended) or a service account key Secret. The PVC approach needs zero auth config. |
| **GCP dependency** | Ties the operator to a specific cloud provider. Users on AWS/Azure/on-prem would need equivalent support (S3, Azure Blob), fragmenting the implementation. |
| **Init container tooling** | The init container would need `gsutil` or `gcloud` CLI installed, increasing the image size and attack surface. |

---

## The Locking Problem — Critical Analysis

This is the make-or-break issue. The current system works precisely because `flock` provides **atomic, exclusive file locking** on a shared POSIX filesystem:

```bash
exec 200>/opt/kaspr/packages/.install.lock
flock -x -w 600 200   # Only ONE init container proceeds
```

With GCS, there is no filesystem-level lock. Below are the options considered when many pods start simultaneously.

### Option A: No coordination (accept the race)

All pods check GCS → cache miss → all install packages in parallel → all upload. The last upload wins and subsequent restarts are fast.

- **Upside:** Simplest to implement
- **Downside:** First deployment wastes N× CPU/network (where N = replica count)
- **Verdict:** "Good enough" for most cases. Wasteful but not incorrect.

### Option B: GCS object-based distributed lock

Use a lock object in GCS (e.g., `gs://bucket/.lock-<app>`) with `if-generation-match: 0` for conditional creation:

```bash
gsutil -h "x-goog-if-generation-match:0" cp /dev/null gs://bucket/.lock-myapp
```

- Only one pod "wins" the lock, installs, uploads, deletes lock
- Other pods poll for the lock to be released
- **Problem:** Lock can become stale if the winning pod crashes. GCS doesn't have native TTLs on individual objects with sub-minute granularity.
- **Problem:** Polling introduces delay and complexity in the init container script.
- **Verdict:** Doable but brittle.

### Option C: Kubernetes-native lock (ConfigMap/Lease)

Use a Kubernetes Lease or ConfigMap as a distributed lock:

- The operator creates a lock resource, the init container uses `kubectl` to acquire it
- **Problem:** Init containers would need RBAC + kubectl/API access — significant privilege escalation
- Goes against the principle of minimal init container privileges
- **Verdict:** Not recommended.

### Option D: Leader election in operator (pre-populate cache)

The operator itself downloads/uploads to GCS before creating the StatefulSet:

- Operator installs packages in a temporary Pod, uploads to GCS
- StatefulSet pods only download (no locking needed)
- **Problem:** Adds significant complexity to the reconciliation loop
- **Problem:** Operator needs GCS credentials and a way to run pip
- **Verdict:** Architecturally complex. Out of scope for current operator design.

### Locking Verdict

None of these are as clean as `flock` on a PVC. Option A (accept the race) is the simplest and "good enough" — first deployment wastes some resources but subsequent restarts are fast. Option B is doable but brittle.

---

## Comparison Summary

| Criteria | PVC (current) | GCS |
|---|---|---|
| **Locking / concurrency** | Excellent (`flock`) | Poor (no native lock) |
| **First-deploy efficiency** | One pod installs, rest wait | All pods may install in parallel |
| **Subsequent starts** | Instant (shared FS) | Fast (download archive) |
| **RWX requirement** | Yes (biggest pain point) | No |
| **Cross-cluster reuse** | No | Yes |
| **Cloud portability** | Any K8s | GCP only (or need S3/Azure too) |
| **Auth complexity** | None | Moderate |
| **Operator complexity** | Low | Medium-High |
| **Cost** | PV storage cost | GCS storage + egress |

---

## Recommendation

**GCS is not recommended as a replacement for PVC caching**, but could be considered as an **additional option** for environments where RWX storage is unavailable.

The strongest argument *for* GCS is eliminating the RWX requirement — a real pain point for users on GKE with `pd-standard`. But the locking gap is a fundamental downgrade. The current `flock` approach is elegant and battle-tested. GCS introduces distributed systems complexity (stale locks, race conditions, polling) that the PVC model avoids entirely.

### If Pursued

The pragmatic approach would be:

1. Accept the first-deploy "thundering herd" (Option A) — all pods install, one uploads, rest are redundant
2. Keep `emptyDir` as the local volume in each pod, with GCS as a "warm cache" layer
3. Abstract it behind a `cache.type` field (`pvc` | `objectStore`) rather than GCS-specific, to allow future S3/Azure support
4. Require `gsutil` or a small Go binary in the init container image for GCS operations

### Alternatives Considered

- **Pre-built container images** with packages baked in — conceptually avoids the caching problem by shifting installation to build time, but **not practical in the Kaspr model**. Automating this would require the operator to run in-cluster container builds (Kaniko/BuildKit), manage registry credentials, push images, and update StatefulSet image references. This is dramatically heavier than the current init container + PVC approach and fundamentally changes the operator's scope from resource management to image building. Only viable when an external CI/CD pipeline owns the image — which defeats the purpose of the declarative `pythonPackages` spec.
- **OCI artifact cache** — store packages as OCI artifacts, leveraging existing container registry infrastructure. Similar auth/registry complexity as pre-built images.
- **emptyDir with warm-up Job** — a one-shot Job populates GCS/S3, pods download on start. Simpler than full operator integration but still requires object store credentials and adds a Job lifecycle to manage.
