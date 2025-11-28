# Python Package Management - Phase 3 Implementation Plan

## Overview

This document outlines the step-by-step implementation plan for Phase 3 (Supply Chain Security & Advanced Features) of the Python package management feature. Phase 3 builds on the foundation of Phase 1 (MVP) and Phase 2 (Production Hardening), adding enterprise-grade security features and support for air-gapped environments.

## Prerequisites

**Phase 1 & 2 Completion:**
- ✅ Phase 1 (MVP) completed and stable in production
- ✅ Phase 2 (Production Hardening) validated with enterprise users
- ✅ Package installation, private registries, and monitoring working reliably
- ✅ User feedback incorporated and production issues resolved

## Implementation Approach

- **Security-focused**: Emphasis on supply chain security and integrity verification
- **Enterprise-ready**: Support for air-gapped and highly regulated environments
- **Incremental**: Each task builds on existing foundation
- **Testable**: Comprehensive validation at each step
- **Reviewable**: Small, focused changes for easy review

## Task Breakdown

### Task 1: Add Package Hash Verification Models ✓

**Objective:** Define data models for package hash verification (PEP 658 support)

**Files to Modify:**
- `kaspr/types/models/python_packages.py`
- `kaspr/types/schemas/python_packages.py`

**What to Implement:**

1. Add `PythonPackageHash` model:
   ```python
   from typing import Optional
   from kaspr.types.base import BaseModel
   
   class PythonPackageHash(BaseModel):
       """Package integrity hash specification."""
       algorithm: str  # sha256, sha384, sha512
       digest: str  # hex-encoded hash
   ```

2. Add `PythonPackageWithHash` model:
   ```python
   from typing import Optional, List
   from kaspr.types.base import BaseModel
   
   class PythonPackageWithHash(BaseModel):
       """Package specification with integrity hashes."""
       name: str
       version: str
       hashes: List[PythonPackageHash]
   ```

3. Update `PythonPackagesSpec` to support both formats:
   ```python
   class PythonPackagesSpec(BaseModel):
       # ... existing fields ...
       packages: Optional[List[str]]  # Simple format (existing)
       packages_with_hashes: Optional[List[PythonPackageWithHash]]  # New format
       require_hashes: Optional[bool]  # Enforce hash verification
   ```

4. Update Marshmallow schemas for validation

5. Add default constants in `kaspr/resources/kasprapp.py`:
   ```python
   class KasprApp(BaseResource):
       # ... existing constants ...
       DEFAULT_REQUIRE_HASHES = False
       DEFAULT_HASH_ALGORITHM = "sha256"
   ```

**Note:** All models inherit from `BaseModel`, NOT `@dataclass`. Do NOT set default values in model classes - defaults are defined as constants in resource classes.

**Validation:**
- [ ] Unit tests for hash model instantiation
- [ ] Schema validation for hash format (algorithm, digest)
- [ ] Validation fails for unsupported algorithms
- [ ] Both package formats (simple and with hashes) parse correctly

**Files Changed:**
- Modified: `kaspr/types/models/python_packages.py`
- Modified: `kaspr/types/schemas/python_packages.py`
- Modified: `tests/unit/test_python_packages.py`

---

### Task 2: Update CRD with Hash Verification Fields ✓

**Objective:** Extend KasprApp CRD with hash verification support

**Files to Modify:**
- `crds/kasprapp.crd.yaml`

**What to Implement:**

Add to `spec.pythonPackages`:
```yaml
properties:
  pythonPackages:
    properties:
      # ... existing fields ...
      
      # NEW: Hash verification
      packagesWithHashes:
        type: array
        description: Packages with integrity hashes for verification
        items:
          type: object
          required: [name, version, hashes]
          properties:
            name:
              type: string
              description: Package name
            version:
              type: string
              description: Package version (exact)
            hashes:
              type: array
              description: List of acceptable hashes
              items:
                type: object
                required: [algorithm, digest]
                properties:
                  algorithm:
                    type: string
                    enum: [sha256, sha384, sha512]
                    description: Hash algorithm
                  digest:
                    type: string
                    pattern: '^[a-fA-F0-9]+$'
                    description: Hex-encoded hash digest
      
      requireHashes:
        type: boolean
        default: false
        description: Require hash verification for all packages
```

**Validation:**
- [ ] CRD applies without errors: `kubectl apply -f crds/kasprapp.crd.yaml`
- [ ] Create KasprApp with packagesWithHashes
- [ ] Schema rejects invalid hash format
- [ ] Schema rejects unsupported algorithms

**Files Changed:**
- Modified: `crds/kasprapp.crd.yaml`

---

### Task 3: Implement Hash Verification in Install Script ✓

**Objective:** Generate pip install commands with --require-hashes flag

**Files to Modify:**
- `kaspr/utils/python_packages.py`

**What to Implement:**

1. Update `generate_install_script()` to support hash verification:
   ```python
   def generate_install_script(spec: dict, hash: str) -> str:
       """Generate init container install script with hash verification."""
       packages = spec.get('packages', [])
       packages_with_hashes = spec.get('packagesWithHashes', [])
       require_hashes = spec.get('requireHashes', False)
       
       # Generate requirements file content
       if packages_with_hashes:
           requirements = generate_requirements_with_hashes(packages_with_hashes)
       else:
           requirements = '\n'.join(packages)
       
       # Build pip install command
       pip_cmd_parts = ['pip install', '--target=/packages', '--no-cache-dir']
       
       if require_hashes or packages_with_hashes:
           pip_cmd_parts.append('--require-hashes')
       
       # ... rest of command construction ...
       
       script = f'''
       # Write requirements to file
       cat > /tmp/requirements.txt <<'REQUIREMENTS_EOF'
       {requirements}
       REQUIREMENTS_EOF
       
       # Install from requirements file
       {' '.join(pip_cmd_parts)} -r /tmp/requirements.txt
       '''
       
       return script
   ```

2. Add helper function for requirements generation:
   ```python
   def generate_requirements_with_hashes(packages_with_hashes: list) -> str:
       """Generate pip requirements.txt format with hashes."""
       lines = []
       
       for pkg in packages_with_hashes:
           # Add package line
           lines.append(f"{pkg['name']}=={pkg['version']} \\")
           
           # Add hash lines
           for hash_spec in pkg['hashes']:
               algo = hash_spec['algorithm']
               digest = hash_spec['digest']
               lines.append(f"    --hash={algo}:{digest} \\")
           
           # Remove trailing backslash from last hash
           lines[-1] = lines[-1].rstrip(' \\')
       
       return '\n'.join(lines)
   ```

3. Update hash computation to include hash specs:
   ```python
   def compute_packages_hash(packages_spec):
       components = {
           'packages': sorted(packages_spec.get('packages', [])),
           'packagesWithHashes': sorted(
               json.dumps(pkg, sort_keys=True) 
               for pkg in packages_spec.get('packagesWithHashes', [])
           ),
           'requireHashes': packages_spec.get('requireHashes', False),
           # ... existing fields ...
       }
       # ... rest of hash computation ...
   ```

**Validation:**
- [ ] Requirements file generated correctly with hashes
- [ ] pip install uses --require-hashes flag
- [ ] Installation succeeds with valid hashes
- [ ] Installation fails with invalid hashes
- [ ] Hash mismatch produces clear error message

**Files Changed:**
- Modified: `kaspr/utils/python_packages.py`
- Modified: `tests/unit/test_python_packages.py`

---

### Task 4: Add Hash Generation Utility ✓

**Objective:** Provide utility to generate package hashes from PyPI

**Files to Create:**
- `kaspr/utils/hash_generator.py`

**What to Implement:**

Create utility script for generating hash specifications:

```python
"""Utility for generating package hash specifications from PyPI."""

import hashlib
import json
import sys
from typing import List, Dict
from urllib.request import urlopen
from urllib.error import URLError


def fetch_package_hashes(
    package_name: str,
    version: str,
    index_url: str = "https://pypi.org/simple",
    algorithm: str = "sha256"
) -> List[Dict[str, str]]:
    """
    Fetch package hashes from PyPI JSON API.
    
    Returns list of hashes for all distribution files (wheels + sdist).
    """
    # PyPI JSON API endpoint
    api_url = f"https://pypi.org/pypi/{package_name}/{version}/json"
    
    try:
        with urlopen(api_url) as response:
            data = json.loads(response.read())
        
        hashes = []
        for file_info in data['urls']:
            # Get hash from PyPI metadata
            if 'digests' in file_info and algorithm in file_info['digests']:
                digest = file_info['digests'][algorithm]
                hashes.append({
                    'algorithm': algorithm,
                    'digest': digest,
                    'filename': file_info['filename']  # For debugging
                })
        
        return hashes
        
    except URLError as e:
        print(f"Error fetching package metadata: {e}", file=sys.stderr)
        return []


def generate_package_spec_with_hashes(
    package_name: str,
    version: str,
    algorithm: str = "sha256"
) -> Dict:
    """Generate package specification with hashes."""
    hashes = fetch_package_hashes(package_name, version, algorithm=algorithm)
    
    if not hashes:
        raise ValueError(f"No hashes found for {package_name}=={version}")
    
    return {
        'name': package_name,
        'version': version,
        'hashes': [
            {'algorithm': h['algorithm'], 'digest': h['digest']}
            for h in hashes
        ]
    }


def main():
    """CLI for hash generation."""
    if len(sys.argv) < 2:
        print("Usage: python hash_generator.py <package>==<version> [...]")
        print("Example: python hash_generator.py requests==2.31.0 pandas==2.1.0")
        sys.exit(1)
    
    packages = []
    
    for pkg_spec in sys.argv[1:]:
        if '==' not in pkg_spec:
            print(f"Error: Package must specify exact version: {pkg_spec}")
            sys.exit(1)
        
        name, version = pkg_spec.split('==', 1)
        print(f"Fetching hashes for {name}=={version}...", file=sys.stderr)
        
        try:
            pkg = generate_package_spec_with_hashes(name, version)
            packages.append(pkg)
            print(f"  Found {len(pkg['hashes'])} hashes", file=sys.stderr)
        except Exception as e:
            print(f"  Error: {e}", file=sys.stderr)
            sys.exit(1)
    
    # Output YAML format
    print("\npackagesWithHashes:")
    for pkg in packages:
        print(f"  - name: {pkg['name']}")
        print(f"    version: '{pkg['version']}'")
        print(f"    hashes:")
        for h in pkg['hashes']:
            print(f"      - algorithm: {h['algorithm']}")
            print(f"        digest: {h['digest']}")


if __name__ == '__main__':
    main()
```

**Usage Example:**
```bash
# Generate hashes for packages
python -m kaspr.utils.hash_generator requests==2.31.0 pandas==2.1.0

# Output (copy to KasprApp spec):
packagesWithHashes:
  - name: requests
    version: '2.31.0'
    hashes:
      - algorithm: sha256
        digest: 942c5a758f98c59...
      - algorithm: sha256
        digest: 8a2d4c798d44a16...
  - name: pandas
    version: '2.1.0'
    hashes:
      - algorithm: sha256
        digest: abc123def456...
```

**Validation:**
- [ ] Utility fetches hashes from PyPI correctly
- [ ] Output format matches CRD schema
- [ ] Works with multiple packages
- [ ] Handles missing packages gracefully
- [ ] Supports different hash algorithms

**Files Changed:**
- New: `kaspr/utils/hash_generator.py`
- New: `tests/unit/test_hash_generator.py`

---

### Task 5: Add Pre-cached Package Support Models ✓

**Objective:** Define models for pre-cached package bundles (air-gapped environments)

**Files to Modify:**
- `kaspr/types/models/python_packages.py`
- `kaspr/types/schemas/python_packages.py`

**What to Implement:**

1. Add `PythonPackageBundleSource` model:
   ```python
   from typing import Optional
   from kaspr.types.base import BaseModel
   
   class PythonPackageBundleSource(BaseModel):
       """Source for pre-cached package bundle."""
       type: str  # configmap | secret | pvc
       name: str
       path: Optional[str]  # Path within ConfigMap/Secret/PVC
   ```

2. Add to `PythonPackagesSpec`:
   ```python
   class PythonPackagesSpec(BaseModel):
       # ... existing fields ...
       bundle_source: Optional[PythonPackageBundleSource]
       offline_mode: Optional[bool]  # Skip PyPI, use bundle only
   ```

3. Update Marshmallow schemas for validation

4. Add default constants in `kaspr/resources/kasprapp.py`:
   ```python
   class KasprApp(BaseResource):
       # ... existing constants ...
       DEFAULT_OFFLINE_MODE = False
       DEFAULT_BUNDLE_PATH = "/bundle"
   ```

**Note:** All models inherit from `BaseModel`. Do NOT set default values in model classes.

**Validation:**
- [ ] Unit tests for bundle source model
- [ ] Schema validation for source types
- [ ] Validation rejects unsupported source types

**Files Changed:**
- Modified: `kaspr/types/models/python_packages.py`
- Modified: `kaspr/types/schemas/python_packages.py`
- Modified: `tests/unit/test_python_packages.py`

---

### Task 6: Update CRD with Bundle Support ✓

**Objective:** Extend CRD to support pre-cached package bundles

**Files to Modify:**
- `crds/kasprapp.crd.yaml`

**What to Implement:**

Add to `spec.pythonPackages`:
```yaml
properties:
  pythonPackages:
    properties:
      # ... existing fields ...
      
      # NEW: Bundle support
      bundleSource:
        type: object
        description: Source for pre-cached package bundle (air-gapped environments)
        required: [type, name]
        properties:
          type:
            type: string
            enum: [configmap, secret, pvc]
            description: Type of bundle source
          name:
            type: string
            description: Name of ConfigMap/Secret/PVC
          path:
            type: string
            description: Path within source to bundle file
      
      offlineMode:
        type: boolean
        default: false
        description: Skip PyPI download, use bundle only (air-gapped)
```

**Validation:**
- [ ] CRD applies without errors
- [ ] Create KasprApp with bundleSource
- [ ] Schema validates source type enum
- [ ] Schema requires name field

**Files Changed:**
- Modified: `crds/kasprapp.crd.yaml`

---

### Task 7: Implement Bundle Volume Mounting ✓

**Objective:** Mount bundle source as volume in init container

**Files to Modify:**
- `kaspr/resources/kasprapp.py`

**What to Implement:**

1. Add method `prepare_python_packages_bundle_volume() -> Optional[V1Volume]`:
   ```python
   def prepare_python_packages_bundle_volume(self) -> Optional[V1Volume]:
       """Prepare volume for package bundle."""
       if not self.python_packages or not self.python_packages.bundle_source:
           return None
       
       bundle = self.python_packages.bundle_source
       
       if bundle.type == 'configmap':
           return V1Volume(
               name='package-bundle',
               config_map=V1ConfigMapVolumeSource(
                   name=bundle.name
               )
           )
       elif bundle.type == 'secret':
           return V1Volume(
               name='package-bundle',
               secret=V1SecretVolumeSource(
                   secret_name=bundle.name
               )
           )
       elif bundle.type == 'pvc':
           return V1Volume(
               name='package-bundle',
               persistent_volume_claim=V1PersistentVolumeClaimVolumeSource(
                   claim_name=bundle.name
               )
           )
       
       return None
   ```

2. Add method `prepare_python_packages_bundle_volume_mount() -> Optional[V1VolumeMount]`:
   ```python
   def prepare_python_packages_bundle_volume_mount(self) -> Optional[V1VolumeMount]:
       """Prepare volume mount for package bundle."""
       if not self.python_packages or not self.python_packages.bundle_source:
           return None
       
       return V1VolumeMount(
           name='package-bundle',
           mount_path=self.DEFAULT_BUNDLE_PATH,
           read_only=True
       )
   ```

3. Update `prepare_statefulset()` to include bundle volume:
   ```python
   def prepare_statefulset(self) -> V1StatefulSet:
       volumes = [...]
       
       # Add bundle volume if configured
       bundle_volume = self.prepare_python_packages_bundle_volume()
       if bundle_volume:
           volumes.append(bundle_volume)
       
       # ... rest of StatefulSet preparation ...
   ```

4. Update init container to mount bundle:
   ```python
   def prepare_python_packages_init_container(self) -> V1Container:
       volume_mounts = [
           self.prepare_python_packages_pvc_volume_mount()
       ]
       
       # Add bundle mount if configured
       bundle_mount = self.prepare_python_packages_bundle_volume_mount()
       if bundle_mount:
           volume_mounts.append(bundle_mount)
       
       # ... rest of init container preparation ...
   ```

**Validation:**
- [ ] Bundle volume created for each source type
- [ ] Init container mounts bundle correctly
- [ ] Volume mount is read-only
- [ ] Works with ConfigMap, Secret, and PVC sources

**Files Changed:**
- Modified: `kaspr/resources/kasprapp.py`
- Modified: `tests/unit/test_python_packages.py`

---

### Task 8: Implement Offline Installation Logic ✓

**Objective:** Support package installation from pre-cached bundle

**Files to Modify:**
- `kaspr/utils/python_packages.py`

**What to Implement:**

Update `generate_install_script()` to support offline mode:

```python
def generate_install_script(spec: dict, hash: str) -> str:
    """Generate init container install script with offline support."""
    offline_mode = spec.get('offlineMode', False)
    bundle_source = spec.get('bundleSource')
    
    if offline_mode and bundle_source:
        # Offline installation from bundle
        bundle_path = bundle_source.get('path', '/bundle')
        
        script = f'''
        echo "→ Offline mode: Installing from bundle"
        
        # Check bundle exists
        if [ ! -d "{bundle_path}" ] && [ ! -f "{bundle_path}" ]; then
          echo "✗ Bundle not found at {bundle_path}"
          exit 1
        fi
        
        # Install from bundle (no network access)
        if [ -d "{bundle_path}" ]; then
          # Directory with wheel files
          pip install \\
            --target=/packages \\
            --no-cache-dir \\
            --no-index \\
            --find-links="{bundle_path}" \\
            {' '.join(spec.get('packages', []))}
        else
          # Tar/zip bundle
          tar -xzf "{bundle_path}" -C /tmp/bundle
          pip install \\
            --target=/packages \\
            --no-cache-dir \\
            --no-index \\
            --find-links="/tmp/bundle" \\
            {' '.join(spec.get('packages', []))}
        fi
        '''
    else:
        # Online installation (existing logic)
        script = generate_online_install_script(spec, hash)
    
    return script
```

**Offline Mode Behavior:**
- Uses `--no-index` flag (no PyPI access)
- Uses `--find-links` to point to bundle
- Fails fast if bundle not found
- Supports both directory and archive bundles

**Validation:**
- [ ] Offline installation works from directory bundle
- [ ] Offline installation works from tar.gz bundle
- [ ] Installation fails gracefully if bundle missing
- [ ] No network requests made in offline mode
- [ ] Hash verification still works in offline mode

**Files Changed:**
- Modified: `kaspr/utils/python_packages.py`
- Modified: `tests/unit/test_python_packages.py`

---

### Task 9: Create Bundle Generation Utility ✓

**Objective:** Provide utility to create package bundles for air-gapped environments

**Files to Create:**
- `kaspr/utils/bundle_creator.py`

**What to Implement:**

Create utility for generating package bundles:

```python
"""Utility for creating package bundles for offline installation."""

import os
import sys
import shutil
import tempfile
import subprocess
from pathlib import Path
from typing import List


def download_packages(
    packages: List[str],
    output_dir: str,
    index_url: str = None,
    extra_index_urls: List[str] = None
) -> bool:
    """Download packages and dependencies to directory."""
    cmd = [
        'pip', 'download',
        '--dest', output_dir,
        '--no-cache-dir'
    ]
    
    if index_url:
        cmd.extend(['--index-url', index_url])
    
    if extra_index_urls:
        for extra_url in extra_index_urls:
            cmd.extend(['--extra-index-url', extra_url])
    
    cmd.extend(packages)
    
    print(f"Downloading packages: {' '.join(packages)}")
    print(f"Command: {' '.join(cmd)}")
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"Error downloading packages:\n{result.stderr}", file=sys.stderr)
        return False
    
    print(result.stdout)
    return True


def create_bundle_archive(source_dir: str, output_file: str) -> bool:
    """Create compressed bundle archive."""
    print(f"Creating bundle archive: {output_file}")
    
    cmd = [
        'tar', '-czf', output_file,
        '-C', source_dir,
        '.'
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"Error creating archive:\n{result.stderr}", file=sys.stderr)
        return False
    
    size_mb = os.path.getsize(output_file) / (1024 * 1024)
    print(f"Bundle created: {output_file} ({size_mb:.2f} MB)")
    return True


def create_configmap_yaml(
    bundle_file: str,
    configmap_name: str,
    output_file: str
) -> bool:
    """Generate ConfigMap YAML for bundle."""
    import base64
    
    with open(bundle_file, 'rb') as f:
        bundle_data = f.read()
    
    bundle_b64 = base64.b64encode(bundle_data).decode('utf-8')
    
    yaml_content = f"""apiVersion: v1
kind: ConfigMap
metadata:
  name: {configmap_name}
binaryData:
  packages.tar.gz: {bundle_b64}
"""
    
    with open(output_file, 'w') as f:
        f.write(yaml_content)
    
    print(f"ConfigMap YAML written to: {output_file}")
    return True


def main():
    """CLI for bundle creation."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Create package bundle for offline Kaspr deployment'
    )
    parser.add_argument(
        'packages',
        nargs='+',
        help='Packages to include (e.g., requests==2.31.0)'
    )
    parser.add_argument(
        '--output',
        default='packages-bundle.tar.gz',
        help='Output bundle file (default: packages-bundle.tar.gz)'
    )
    parser.add_argument(
        '--index-url',
        help='Custom PyPI index URL'
    )
    parser.add_argument(
        '--extra-index-url',
        action='append',
        help='Extra PyPI index URLs'
    )
    parser.add_argument(
        '--generate-configmap',
        help='Generate ConfigMap YAML file'
    )
    parser.add_argument(
        '--configmap-name',
        default='python-packages-bundle',
        help='ConfigMap name (default: python-packages-bundle)'
    )
    
    args = parser.parse_args()
    
    # Create temp directory for downloads
    with tempfile.TemporaryDirectory() as tmpdir:
        download_dir = os.path.join(tmpdir, 'packages')
        os.makedirs(download_dir)
        
        # Download packages
        success = download_packages(
            packages=args.packages,
            output_dir=download_dir,
            index_url=args.index_url,
            extra_index_urls=args.extra_index_url
        )
        
        if not success:
            sys.exit(1)
        
        # Create archive
        success = create_bundle_archive(
            source_dir=download_dir,
            output_file=args.output
        )
        
        if not success:
            sys.exit(1)
    
    # Generate ConfigMap if requested
    if args.generate_configmap:
        success = create_configmap_yaml(
            bundle_file=args.output,
            configmap_name=args.configmap_name,
            output_file=args.generate_configmap
        )
        
        if not success:
            sys.exit(1)
    
    print("\n✓ Bundle creation complete")
    print(f"\nTo use in air-gapped environment:")
    print(f"  1. Transfer {args.output} to air-gapped cluster")
    if args.generate_configmap:
        print(f"  2. kubectl apply -f {args.generate_configmap}")
    print(f"  3. Reference in KasprApp spec:")
    print(f"     bundleSource:")
    print(f"       type: configmap")
    print(f"       name: {args.configmap_name}")
    print(f"     offlineMode: true")


if __name__ == '__main__':
    main()
```

**Usage Example:**
```bash
# Create bundle
python -m kaspr.utils.bundle_creator \
  requests==2.31.0 pandas==2.1.0 \
  --output packages.tar.gz \
  --generate-configmap packages-configmap.yaml

# Transfer to air-gapped cluster and apply
kubectl apply -f packages-configmap.yaml

# Use in KasprApp
pythonPackages:
  packages:
    - requests==2.31.0
    - pandas==2.1.0
  bundleSource:
    type: configmap
    name: python-packages-bundle
  offlineMode: true
```

**Validation:**
- [ ] Utility downloads packages correctly
- [ ] Bundle archive created successfully
- [ ] ConfigMap YAML generated correctly
- [ ] Bundle size reasonable (compression works)
- [ ] Handles large packages (ML libraries)

**Files Changed:**
- New: `kaspr/utils/bundle_creator.py`
- New: `tests/unit/test_bundle_creator.py`

---

### Task 10: Add Supply Chain Security Metrics ✓

**Objective:** Add metrics for hash verification and bundle usage

**Files to Modify:**
- `kaspr/sensors/prometheus.py`

**What to Implement:**

Add new metrics:

```python
# Hash verification metrics
package_hash_verification_enabled = Gauge(
    'kasprop_package_hash_verification_enabled',
    'Whether package hash verification is enabled',
    ['app_name', 'namespace']
)

package_hash_verification_failures_total = Counter(
    'kasprop_package_hash_verification_failures_total',
    'Total number of hash verification failures',
    ['app_name', 'namespace', 'package']
)

# Offline/bundle metrics
package_offline_mode_enabled = Gauge(
    'kasprop_package_offline_mode_enabled',
    'Whether offline mode (bundle) is enabled',
    ['app_name', 'namespace']
)

package_bundle_source_type = Gauge(
    'kasprop_package_bundle_source_type',
    'Type of bundle source (1=configmap, 2=secret, 3=pvc)',
    ['app_name', 'namespace', 'source_type']
)

package_bundle_install_total = Counter(
    'kasprop_package_bundle_install_total',
    'Total number of installations from bundle',
    ['app_name', 'namespace', 'result']
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
    hash_verification: bool = False,  # NEW
    offline_mode: bool = False,  # NEW
    error_type: str = None
):
    # ... existing metrics ...
    
    # Hash verification
    self.prometheus.package_hash_verification_enabled.labels(
        app_name=app_name,
        namespace=namespace
    ).set(1 if hash_verification else 0)
    
    # Offline mode
    self.prometheus.package_offline_mode_enabled.labels(
        app_name=app_name,
        namespace=namespace
    ).set(1 if offline_mode else 0)
    
    # Bundle install counter
    if offline_mode:
        self.prometheus.package_bundle_install_total.labels(
            app_name=app_name,
            namespace=namespace,
            result='success' if success else 'failure'
        ).inc()
```

**Validation:**
- [ ] Metrics exposed on /metrics endpoint
- [ ] Hash verification metric set correctly
- [ ] Offline mode metric set correctly
- [ ] Bundle source type metric set correctly
- [ ] Counters increment appropriately

**Files Changed:**
- Modified: `kaspr/sensors/prometheus.py`
- Modified: `kaspr/handlers/kasprapp.py`

---

### Task 11: Add Enhanced Status for Security Features ✓

**Objective:** Update status to report security and bundle information

**Files to Modify:**
- `kaspr/handlers/kasprapp.py`

**What to Implement:**

Update `fetch_python_packages_status()` to include security info:

```python
async def fetch_python_packages_status(app: KasprApp) -> dict:
    # ... existing status logic ...
    
    status = {
        'state': 'Ready',
        'hash': marker_data['hash'],
        'installed': marker_data['packages'].split(),
        'lastInstallTime': marker_data['installed_at'],
        'installDuration': marker_data['duration'],
        'installedBy': marker_data['installed_by'],
        'cacheMode': 'shared-pvc',
        'warnings': []
    }
    
    # Add security info
    if app.python_packages.require_hashes or app.python_packages.packages_with_hashes:
        status['security'] = {
            'hashVerification': True,
            'algorithm': 'sha256',
            'verifiedPackages': len(app.python_packages.packages_with_hashes or [])
        }
    
    # Add bundle info
    if app.python_packages.bundle_source:
        status['bundle'] = {
            'enabled': True,
            'sourceType': app.python_packages.bundle_source.type,
            'sourceName': app.python_packages.bundle_source.name,
            'offlineMode': app.python_packages.offline_mode or False
        }
    
    return status
```

Update CRD status schema:
```yaml
status:
  properties:
    pythonPackages:
      properties:
        # ... existing fields ...
        
        # NEW: Security info
        security:
          type: object
          properties:
            hashVerification:
              type: boolean
            algorithm:
              type: string
            verifiedPackages:
              type: integer
        
        # NEW: Bundle info
        bundle:
          type: object
          properties:
            enabled:
              type: boolean
            sourceType:
              type: string
            sourceName:
              type: string
            offlineMode:
              type: boolean
```

**Validation:**
- [ ] Status shows hash verification info
- [ ] Status shows bundle configuration
- [ ] Security fields populated when using hashes
- [ ] Bundle fields populated when using bundle
- [ ] Fields absent when features not enabled

**Files Changed:**
- Modified: `kaspr/handlers/kasprapp.py`
- Modified: `crds/kasprapp.crd.yaml`
- Modified: `tests/unit/test_python_packages.py`

---

### Task 12: Create Manual Testing Guide for Phase 3 ✓

**Objective:** Document manual test scenarios for Phase 3 features

**Files to Create:**
- `docs/testing/python-packages-phase3-manual-tests.md`

**What to Document:**

**Test Scenarios:**

1. **Hash Verification - Valid Hashes**
   - Generate hash specs using hash_generator utility
   - Create KasprApp with packagesWithHashes
   - Verify installation succeeds
   - Verify status shows hash verification enabled
   - Check no hash verification failures in metrics

2. **Hash Verification - Invalid Hashes**
   - Create KasprApp with incorrect hash digest
   - Verify installation fails
   - Check error message mentions hash mismatch
   - Verify hash verification failure metric incremented

3. **Hash Verification - requireHashes Flag**
   - Create KasprApp with requireHashes: true and simple packages
   - Verify installation fails (no hashes provided)
   - Update to include hashes
   - Verify installation succeeds

4. **Offline Mode - ConfigMap Bundle**
   - Create bundle using bundle_creator utility
   - Create ConfigMap with bundle
   - Create KasprApp with bundleSource + offlineMode
   - Verify packages install from bundle
   - Block network access, verify still works

5. **Offline Mode - PVC Bundle**
   - Create PVC with pre-downloaded packages
   - Create KasprApp pointing to bundle PVC
   - Verify installation from bundle
   - Check offline mode metric set correctly

6. **Offline Mode - Missing Bundle**
   - Create KasprApp with bundleSource but bundle doesn't exist
   - Verify installation fails gracefully
   - Check error message clear about missing bundle

7. **Hash Verification + Offline Mode**
   - Create bundle with packages
   - Generate hash specs for bundled packages
   - Create KasprApp with both features
   - Verify hash verification works with bundle
   - Confirm no network access needed

8. **Hash Verification + Private Registry**
   - Use private registry with authentication
   - Generate hashes for private packages
   - Create KasprApp with both features
   - Verify installation works correctly

9. **Bundle Size Testing**
   - Create bundle with large packages (tensorflow, torch)
   - Test ConfigMap size limits (1MB limit)
   - Test with PVC bundle instead
   - Verify performance with large bundles

10. **End-to-End Air-Gapped Scenario**
    - Simulate air-gapped environment (no internet)
    - Create bundle on connected machine
    - Transfer bundle to air-gapped cluster
    - Deploy KasprApp in offline mode
    - Verify full functionality without network

**Testing Checklist Format:**

Each scenario includes:
- Prerequisites (bundles, ConfigMaps, network policies)
- Step-by-step commands
- Expected results at each step
- Validation commands
- Success criteria
- Cleanup procedures

**Validation:**
- [ ] All 10 scenarios documented with commands
- [ ] Scenarios tested in dev cluster
- [ ] Air-gapped testing validated
- [ ] Security features verified
- [ ] Known limitations documented

**Files Changed:**
- New: `docs/testing/python-packages-phase3-manual-tests.md`

---

### Task 13: Add Phase 3 Examples ✓

**Objective:** Create example manifests for Phase 3 features

**Files to Create:**
- `examples/python-packages/with-hashes.yaml`
- `examples/python-packages/offline-configmap.yaml`
- `examples/python-packages/offline-pvc.yaml`
- `examples/python-packages/air-gapped-complete.yaml`

**What to Create:**

**1. Hash Verification Example:**
```yaml
# examples/python-packages/with-hashes.yaml
apiVersion: kaspr.io/v1alpha1
kind: KasprApp
metadata:
  name: app-with-hash-verification
  namespace: default
spec:
  replicas: 3
  bootstrapServers: kafka:9092
  
  pythonPackages:
    # Packages with hash verification
    packagesWithHashes:
      - name: requests
        version: '2.31.0'
        hashes:
          - algorithm: sha256
            digest: 942c5a758f98c59dca3a83c5e679e8b4f4f4e8a5d4c5e8a3f7c9a2b1c8d9e0f1
          - algorithm: sha256
            digest: 8a2d4c798d44a165a9e0c3e4f5d6e7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4
      
      - name: pandas
        version: '2.1.0'
        hashes:
          - algorithm: sha256
            digest: abc123def456789abc123def456789abc123def456789abc123def456789abcd
    
    # Require hash verification for all packages
    requireHashes: true
```

**2. Offline ConfigMap Example:**
```yaml
# examples/python-packages/offline-configmap.yaml
---
# First, create the bundle ConfigMap
apiVersion: v1
kind: ConfigMap
metadata:
  name: python-packages-bundle
  namespace: default
binaryData:
  packages.tar.gz: H4sIAAAAAAAA...  # Base64-encoded bundle
---
apiVersion: kaspr.io/v1alpha1
kind: KasprApp
metadata:
  name: app-offline-configmap
  namespace: default
spec:
  replicas: 3
  bootstrapServers: kafka:9092
  
  pythonPackages:
    packages:
      - requests==2.31.0
      - pandas==2.1.0
    
    # Bundle source
    bundleSource:
      type: configmap
      name: python-packages-bundle
    
    # Offline mode (no PyPI access)
    offlineMode: true
```

**3. Offline PVC Example:**
```yaml
# examples/python-packages/offline-pvc.yaml
---
# Pre-create PVC with packages
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: package-bundle-pvc
  namespace: default
spec:
  accessModes:
    - ReadWriteMany
  resources:
    requests:
      storage: 5Gi
  storageClass: fast-nfs
---
# Job to populate bundle (run once)
apiVersion: batch/v1
kind: Job
metadata:
  name: populate-package-bundle
  namespace: default
spec:
  template:
    spec:
      restartPolicy: OnFailure
      containers:
        - name: downloader
          image: python:3.11-slim
          command:
            - /bin/sh
            - -c
            - |
              pip download \
                --dest /bundle \
                requests==2.31.0 pandas==2.1.0 numpy==1.24.0
          volumeMounts:
            - name: bundle
              mountPath: /bundle
      volumes:
        - name: bundle
          persistentVolumeClaim:
            claimName: package-bundle-pvc
---
apiVersion: kaspr.io/v1alpha1
kind: KasprApp
metadata:
  name: app-offline-pvc
  namespace: default
spec:
  replicas: 3
  bootstrapServers: kafka:9092
  
  pythonPackages:
    packages:
      - requests==2.31.0
      - pandas==2.1.0
      - numpy==1.24.0
    
    bundleSource:
      type: pvc
      name: package-bundle-pvc
    
    offlineMode: true
```

**4. Complete Air-Gapped Example:**
```yaml
# examples/python-packages/air-gapped-complete.yaml
apiVersion: kaspr.io/v1alpha1
kind: KasprApp
metadata:
  name: air-gapped-app
  namespace: production
spec:
  replicas: 5
  bootstrapServers: kafka-prod:9092
  
  pythonPackages:
    # Packages with hash verification
    packagesWithHashes:
      - name: requests
        version: '2.31.0'
        hashes:
          - algorithm: sha256
            digest: 942c5a758f98c59dca3a83c5e679e8b4f4f4e8a5d4c5e8a3f7c9a2b1c8d9e0f1
      
      - name: pandas
        version: '2.1.0'
        hashes:
          - algorithm: sha256
            digest: abc123def456789abc123def456789abc123def456789abc123def456789abcd
      
      - name: sqlalchemy
        version: '2.0.23'
        hashes:
          - algorithm: sha256
            digest: def456abc123789def456abc123789def456abc123789def456abc123789def4
    
    # Require hash verification (supply chain security)
    requireHashes: true
    
    # Bundle source (air-gapped environment)
    bundleSource:
      type: pvc
      name: production-package-bundle
    
    # Offline mode (no external network)
    offlineMode: true
    
    # Generous cache for bundle
    cache:
      enabled: true
      storageClass: fast-nfs
      size: 10Gi
      accessMode: ReadWriteMany
      deleteClaim: false  # Keep for troubleshooting
    
    # Strict install policy
    installPolicy:
      retries: 1  # Don't retry in air-gapped (will fail same way)
      timeout: 300  # Faster timeout (local install)
      onFailure: block
```

**5. README Update:**
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

### Security & Air-Gapped (Phase 3)
- `with-hashes.yaml` - Hash verification for supply chain security
- `offline-configmap.yaml` - Offline mode with ConfigMap bundle
- `offline-pvc.yaml` - Offline mode with PVC bundle
- `air-gapped-complete.yaml` - Complete air-gapped deployment

## Phase 3 Features

### Hash Verification

Generate hashes:
```bash
python -m kaspr.utils.hash_generator requests==2.31.0 pandas==2.1.0
```

Use in KasprApp:
```yaml
pythonPackages:
  packagesWithHashes:
    - name: requests
      version: '2.31.0'
      hashes:
        - algorithm: sha256
          digest: 942c5a758f98...
  requireHashes: true
```

### Offline Bundles

Create bundle:
```bash
python -m kaspr.utils.bundle_creator \
  requests==2.31.0 pandas==2.1.0 \
  --output packages.tar.gz \
  --generate-configmap packages-configmap.yaml
```

Apply and use:
```bash
kubectl apply -f packages-configmap.yaml
kubectl apply -f offline-configmap.yaml
```

## Troubleshooting

See [Python Packages User Guide](../../docs/user-guide/python-packages.md)
```

**Validation:**
- [ ] All examples apply without errors
- [ ] Hash verification examples work
- [ ] Offline examples work in simulated air-gap
- [ ] Bundle utilities documented
- [ ] README comprehensive

**Files Changed:**
- New: `examples/python-packages/with-hashes.yaml`
- New: `examples/python-packages/offline-configmap.yaml`
- New: `examples/python-packages/offline-pvc.yaml`
- New: `examples/python-packages/air-gapped-complete.yaml`
- Modified: `examples/python-packages/README.md`

---

### Task 14: Update User Documentation ✓

**Objective:** Document Phase 3 features in user guide

**Files to Modify:**
- `docs/user-guide/python-packages.md`

**What to Add:**

Add sections to existing user guide:

**1. Hash Verification**
```markdown
## Hash Verification (Supply Chain Security)

Verify package integrity using cryptographic hashes:

### Generating Hash Specifications

Use the hash generator utility:

```bash
python -m kaspr.utils.hash_generator requests==2.31.0 pandas==2.1.0
```

Output:
```yaml
packagesWithHashes:
  - name: requests
    version: '2.31.0'
    hashes:
      - algorithm: sha256
        digest: 942c5a758f98c59...
  - name: pandas
    version: '2.1.0'
    hashes:
      - algorithm: sha256
        digest: abc123def456...
```

### Using Hash Verification

Copy the output to your KasprApp spec:

```yaml
spec:
  pythonPackages:
    packagesWithHashes:
      - name: requests
        version: '2.31.0'
        hashes:
          - algorithm: sha256
            digest: 942c5a758f98c59...
    requireHashes: true  # Enforce verification
```

**Security Benefits:**
- Prevents supply chain attacks (compromised packages)
- Ensures reproducible builds
- Meets compliance requirements (SOC 2, etc.)

**Important:** Hash verification requires exact version pinning. Version ranges (>=, ~=) not supported with hashes.
```

**2. Offline/Air-Gapped Environments**
```markdown
## Offline Installation (Air-Gapped Environments)

Deploy Kaspr applications without internet access:

### Creating Package Bundle

On a machine with internet access:

```bash
# Create bundle
python -m kaspr.utils.bundle_creator \
  requests==2.31.0 pandas==2.1.0 numpy==1.24.0 \
  --output packages.tar.gz \
  --generate-configmap packages-configmap.yaml
```

This creates:
- `packages.tar.gz` - Compressed package bundle (wheels + dependencies)
- `packages-configmap.yaml` - Kubernetes ConfigMap with embedded bundle

### Transferring Bundle

Transfer files to air-gapped cluster:

```bash
# Option 1: USB drive
cp packages.tar.gz packages-configmap.yaml /mnt/usb/

# Option 2: Secure copy (if bastion available)
scp packages.tar.gz packages-configmap.yaml user@bastion:/tmp/
```

### Deploying in Air-Gapped Cluster

```bash
# Apply ConfigMap
kubectl apply -f packages-configmap.yaml

# Create KasprApp
kubectl apply -f - <<EOF
apiVersion: kaspr.io/v1alpha1
kind: KasprApp
metadata:
  name: my-app
spec:
  pythonPackages:
    packages:
      - requests==2.31.0
      - pandas==2.1.0
      - numpy==1.24.0
    bundleSource:
      type: configmap
      name: python-packages-bundle
    offlineMode: true
EOF
```

**Bundle Source Options:**

1. **ConfigMap** (small bundles < 1MB):
   ```yaml
   bundleSource:
     type: configmap
     name: python-packages-bundle
   ```

2. **PVC** (large bundles, ML libraries):
   ```yaml
   bundleSource:
     type: pvc
     name: package-bundle-pvc
   ```

3. **Secret** (sensitive packages):
   ```yaml
   bundleSource:
     type: secret
     name: python-packages-bundle
   ```

**Offline Mode Behavior:**
- No network requests to PyPI
- Uses only bundled packages
- Fails fast if bundle incomplete
- Compatible with hash verification
```

**3. Combined Security Features**
```markdown
## Complete Security Example

Combine hash verification with offline mode for maximum security:

```yaml
spec:
  pythonPackages:
    # Packages with cryptographic verification
    packagesWithHashes:
      - name: requests
        version: '2.31.0'
        hashes:
          - algorithm: sha256
            digest: 942c5a758f98c59...
    
    # Require hashes (block unverified packages)
    requireHashes: true
    
    # Offline mode (no external network)
    bundleSource:
      type: pvc
      name: approved-packages-bundle
    offlineMode: true
```

**Use Cases:**
- Regulated industries (finance, healthcare)
- Government/defense applications
- High-security environments
- Air-gapped production deployments

**Benefits:**
- Supply chain attack prevention
- Reproducible builds
- Compliance attestation
- No external dependencies
```

**4. Troubleshooting**
```markdown
## Troubleshooting Phase 3 Features

### Hash Verification Failures

If installation fails with hash mismatch:

1. Regenerate hashes:
   ```bash
   python -m kaspr.utils.hash_generator requests==2.31.0
   ```

2. Verify package version exact (no ~=, >=):
   ```yaml
   # ✓ Correct
   - name: requests
     version: '2.31.0'  # Exact version
   
   # ✗ Incorrect
   - name: requests
     version: '>=2.31.0'  # Version range not supported
   ```

3. Check PyPI package hasn't been updated:
   - Package republished with same version
   - Hash changed legitimately
   - Regenerate hashes to get new digest

### Bundle Issues

If offline installation fails:

1. Verify bundle exists:
   ```bash
   kubectl get configmap python-packages-bundle
   kubectl describe configmap python-packages-bundle
   ```

2. Check bundle contents:
   ```bash
   kubectl exec <pod-name> -c install-packages -- ls -la /bundle
   ```

3. Validate bundle size:
   ```bash
   # ConfigMap limit: 1MB
   du -h packages.tar.gz
   
   # If >1MB, use PVC instead
   ```

4. Test bundle integrity:
   ```bash
   tar -tzf packages.tar.gz
   ```

### Air-Gapped Network Policies

Verify no network access in offline mode:

```bash
# Should fail (no internet)
kubectl exec <pod-name> -- curl https://pypi.org

# Should succeed (bundle)
kubectl exec <pod-name> -- ls /bundle
```
```

**Validation:**
- [ ] Documentation clear and comprehensive
- [ ] All Phase 3 features documented
- [ ] Examples included in each section
- [ ] Troubleshooting section helpful
- [ ] Security benefits clearly explained

**Files Changed:**
- Modified: `docs/user-guide/python-packages.md`

---

## Task Dependencies

```
Task 1 (Hash Models)
  ↓
Task 2 (CRD Hash Fields)
  ↓
Task 3 (Hash Verification Script)
  ↓
Task 4 (Hash Generator Utility) ← Can be parallel with Task 3
  ↓
Task 5 (Bundle Models)
  ↓
Task 6 (CRD Bundle Fields)
  ↓
Task 7 (Bundle Volume Mounting)
  ↓
Task 8 (Offline Install Script)
  ↓
Task 9 (Bundle Creator Utility) ← Can be parallel with Task 8
  ↓
Task 10 (Security Metrics)
Task 11 (Enhanced Status) ← Can be parallel with Task 10
  ↓
Task 12 (Manual Testing)
  ↓
Task 13 (Examples)
Task 14 (Documentation) ← Can be parallel with Task 13
```

## Testing Strategy Per Task

### Unit Testing
- After tasks that add logic (Tasks 1, 3, 4, 5, 8, 9)
- Run: `pytest tests/unit/test_python_packages.py -v`
- Focus on hash computation, verification, bundle handling

### Manual Testing
- After Task 8 (offline install complete)
- Test hash verification scenarios
- Test bundle installation (ConfigMap, PVC)
- Test air-gapped simulation

### Integration Testing
- Task 12 (manual testing guide)
- Follow documented scenarios
- Validate in simulated air-gapped cluster
- Test security features end-to-end

### Security Testing
- Hash tampering tests
- Bundle integrity tests
- Network isolation verification
- Supply chain attack simulation

## Rollout Plan

### Local Development
1. Implement tasks 1-14 on feature branch (continue from Phase 2)
2. Test each task independently
3. Run unit tests after tasks 1, 3-5, 8-9
4. Manual testing following Task 12 guide

### Dev Cluster Testing
1. Deploy operator to dev cluster
2. Set up simulated air-gapped environment (NetworkPolicy)
3. Test hash verification with valid/invalid hashes
4. Test bundle installation (all source types)
5. Validate security metrics

### Staging Deployment
1. Deploy to staging with security features
2. Test with real air-gapped scenario
3. Validate hash verification compliance
4. Performance test with large bundles
5. Soak test (48h+ stability)

### Production Rollout
1. Phase 3 features enabled (builds on Phase 1 & 2)
2. Security documentation published
3. Beta announcement for Phase 3 features
4. Gather feedback from regulated/air-gapped users
5. GA release after validation period

## Success Criteria

After completing all Phase 3 tasks, we should have:

- [ ] Hash verification working (PEP 658 compliance)
- [ ] Hash generator utility functional
- [ ] Offline mode supported (ConfigMap, Secret, PVC bundles)
- [ ] Bundle creator utility functional
- [ ] Air-gapped deployments working
- [ ] Security metrics exposed
- [ ] Enhanced status with security info
- [ ] Manual testing guide complete
- [ ] Phase 3 examples working
- [ ] Documentation updated with security features

## Risk Mitigation

### Risk: Hash Generation Complexity
**Mitigation:**
- Provide automated hash generator utility
- Clear documentation with examples
- Support for common algorithms (sha256, sha384, sha512)
- Error messages guide users to regenerate hashes

### Risk: Bundle Size Limits
**Mitigation:**
- Document ConfigMap 1MB limit
- Recommend PVC for large bundles (ML libraries)
- Bundle creator shows size warnings
- Compression enabled by default

### Risk: Air-Gapped Connectivity
**Mitigation:**
- Clear documentation for bundle transfer
- Multiple bundle source options (ConfigMap, PVC, Secret)
- Validation tools to verify bundle integrity
- Fallback strategies documented

### Risk: Hash Maintenance
**Mitigation:**
- Automated hash regeneration on package updates
- CI/CD integration examples
- Hash verification optional (not breaking existing workflows)
- Clear migration path from Phase 1/2

### Risk: Supply Chain False Positives
**Mitigation:**
- Clear error messages for hash mismatches
- Documentation explains legitimate hash changes
- Support for multiple hashes per package (wheels + sdist)
- Hash regeneration utility easily accessible

## Review Checkpoints

After completing each task:
1. Self-review code changes
2. Run relevant unit tests
3. Commit with descriptive message
4. Request review before next task

Key review points:
- After Task 4: Hash generation utility working
- After Task 9: Bundle creation utility working
- After Task 11: Security features integrated
- After Task 12: Testing guide complete
- After Task 14: Ready for security-focused beta release

---

**Document Status:** Ready for Implementation  
**Last Updated:** 2025-11-28  
**Prerequisites:** Phase 1 & 2 complete
