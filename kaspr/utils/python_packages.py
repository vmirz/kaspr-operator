"""Utility functions for Python package management."""

import hashlib
import json
import re

from kaspr.types.models.python_packages import PythonPackagesSpec
from kaspr.utils.gcs import (
    generate_gcs_download_python_script,
    generate_gcs_upload_python_script,
)


# Package name validation pattern
# Supports: alphanumeric, hyphens, underscores, dots, and version specifiers
# Examples: requests, numpy==1.24.0, pandas>=2.0.0, scipy[all]
PACKAGE_NAME_PATTERN = re.compile(
    r'^[a-zA-Z0-9]([a-zA-Z0-9._-]*[a-zA-Z0-9])?'  # Package name (must start/end with alphanumeric)
    r'(\[[a-zA-Z0-9,._-]+\])?'  # Optional extras like [dev,test]
    r'(([<>=!~]=?|[<>])[0-9a-zA-Z._-]+(,[<>=!~]+[0-9a-zA-Z._-]+)*)?$'  # Optional version with multiple specifiers
)


def compute_packages_hash(spec: PythonPackagesSpec) -> str:
    """
    Compute a deterministic hash from the packages spec.
    
    This hash is used to detect changes in package configuration and trigger
    pod restarts when packages need to be reinstalled.
    
    Args:
        spec: The PythonPackagesSpec containing packages and install policy
        
    Returns:
        A SHA-256 hash string (first 16 characters for readability)
    """
    # Create a deterministic dict for hashing
    hash_data = {
        "packages": sorted(spec.packages),  # Sort for determinism
    }
    
    # Include index URL fields (affects where packages come from)
    if hasattr(spec, 'index_url') and spec.index_url:
        hash_data["index_url"] = spec.index_url
    if hasattr(spec, 'extra_index_urls') and spec.extra_index_urls:
        hash_data["extra_index_urls"] = sorted(spec.extra_index_urls)
    if hasattr(spec, 'trusted_hosts') and spec.trusted_hosts:
        hash_data["trusted_hosts"] = sorted(spec.trusted_hosts)
    
    # Include install policy if present (affects how packages are installed)
    if hasattr(spec, 'install_policy') and spec.install_policy:
        policy_data = {}
        if hasattr(spec.install_policy, 'retries') and spec.install_policy.retries is not None:
            policy_data["retries"] = spec.install_policy.retries
        if hasattr(spec.install_policy, 'timeout') and spec.install_policy.timeout is not None:
            policy_data["timeout"] = spec.install_policy.timeout
        if hasattr(spec.install_policy, 'on_failure') and spec.install_policy.on_failure is not None:
            policy_data["on_failure"] = spec.install_policy.on_failure
        if policy_data:
            hash_data["install_policy"] = policy_data
    
    # Convert to JSON with sorted keys for determinism
    json_str = json.dumps(hash_data, sort_keys=True, separators=(',', ':'))
    
    # Compute SHA-256 hash
    hash_obj = hashlib.sha256(json_str.encode('utf-8'))
    full_hash = hash_obj.hexdigest()
    
    # Return first 16 characters for readability in labels/annotations
    return full_hash[:16]


def validate_package_name(package: str) -> bool:
    """
    Validate that a package name follows pip's accepted format.
    
    Validates package names with optional extras and version specifiers.
    Examples of valid packages:
        - requests
        - numpy==1.24.0
        - pandas>=2.0.0,<3.0.0
        - scipy[all]
        - tensorflow>=2.0.0
    
    Args:
        package: The package string to validate
        
    Returns:
        True if the package name is valid, False otherwise
    """
    if not package or not isinstance(package, str):
        return False
    
    # Remove whitespace
    package = package.strip()
    
    if not package:
        return False
    
    # Check against pattern
    return PACKAGE_NAME_PATTERN.match(package) is not None


def _build_pip_install_cmd(cache_path: str, packages_str: str) -> str:
    """Build the pip install command with support for custom indexes and credentials.
    
    Index URL, extra index URLs, trusted hosts, and credentials are read from
    environment variables injected by the operator (see prepare_python_packages_env_vars).
    
    Credentials are embedded into both --index-url and --extra-index-url URLs
    when PYPI_USERNAME and PYPI_PASSWORD are set.
    """
    return f"""build_pip_command() {{
    local pip_cmd="pip install --no-warn-script-location --target {cache_path} --no-cache-dir"
    
    # Helper: embed credentials into a URL (insert username:password@ after scheme)
    embed_credentials() {{
        local url="$1"
        if [ -n "${{PYPI_USERNAME:-}}" ] && [ -n "${{PYPI_PASSWORD:-}}" ]; then
            echo "$url" | sed "s|://|://${{PYPI_USERNAME}}:${{PYPI_PASSWORD}}@|"
        else
            echo "$url"
        fi
    }}
    
    # Custom index URL with optional authentication
    if [ -n "${{INDEX_URL:-}}" ]; then
        local effective_index=$(embed_credentials "$INDEX_URL")
        pip_cmd="$pip_cmd --index-url $effective_index"
    elif [ -n "${{PYPI_USERNAME:-}}" ] && [ -n "${{PYPI_PASSWORD:-}}" ]; then
        # Credentials without custom index - use PyPI with auth
        pip_cmd="$pip_cmd --index-url https://${{PYPI_USERNAME}}:${{PYPI_PASSWORD}}@pypi.org/simple"
    fi
    
    # Extra index URLs (credentials embedded if available)
    if [ -n "${{EXTRA_INDEX_URLS:-}}" ]; then
        IFS=',' read -ra EXTRA_URLS <<< "$EXTRA_INDEX_URLS"
        for url in "${{EXTRA_URLS[@]}}"; do
            local effective_url=$(embed_credentials "$url")
            pip_cmd="$pip_cmd --extra-index-url $effective_url"
        done
    fi
    
    # Trusted hosts
    if [ -n "${{TRUSTED_HOSTS:-}}" ]; then
        IFS=',' read -ra HOSTS <<< "$TRUSTED_HOSTS"
        for host in "${{HOSTS[@]}}"; do
            pip_cmd="$pip_cmd --trusted-host $host"
        done
    fi
    
    pip_cmd="$pip_cmd {packages_str}"
    echo "$pip_cmd"
}}
"""


# User-friendly error messages for common failure scenarios
ERROR_MESSAGES = {
    'network': "Cannot reach package index. Check network connectivity and firewall rules.",
    'package_not_found': "Package not found in index. Verify package name and version.",
    'hash_mismatch': "Package integrity check failed. Package may be corrupted.",
    'authentication': "Authentication failed. Check credentials in referenced Secret.",
    'timeout': "Installation timed out. Consider increasing installPolicy.timeout.",
}


def _build_error_detection_block() -> str:
    """Build shell code for detecting and categorizing pip install errors."""
    return """
    # Categorize the failure
    if [ -f /tmp/pip-error.log ]; then
        if grep -qi "No matching distribution\\|Could not find a version" /tmp/pip-error.log; then
            echo "ERROR_TYPE: package_not_found"
            echo "ERROR_MSG: One or more packages not found in the index. Verify package name and version."
        elif grep -qi "THESE PACKAGES DO NOT MATCH THE HASHES\\|hash" /tmp/pip-error.log; then
            echo "ERROR_TYPE: hash_mismatch"
            echo "ERROR_MSG: Package integrity check failed. Package may be corrupted."
        elif grep -qi "403\\|401\\|authentication\\|Access denied" /tmp/pip-error.log; then
            echo "ERROR_TYPE: authentication"
            echo "ERROR_MSG: Authentication failed. Check credentials in referenced Secret."
        elif grep -qi "ConnectionError\\|NewConnectionError\\|MaxRetryError\\|Name or service not known" /tmp/pip-error.log; then
            echo "ERROR_TYPE: network"
            echo "ERROR_MSG: Cannot reach package index. Check network connectivity and firewall rules."
        else
            echo "ERROR_TYPE: unknown"
            echo "ERROR_MSG: Package installation failed. See init container logs for details."
        fi
    else
        echo "ERROR_TYPE: unknown"
        echo "ERROR_MSG: Package installation failed (no error log captured)."
    fi
"""


def generate_install_script(
    spec: PythonPackagesSpec,
    cache_path: str = "/opt/kaspr/packages",
    lock_file: str = "/opt/kaspr/packages/.install.lock",
    timeout: int = 600,
    retries: int = 3,
    packages_hash: str = None,
) -> str:
    """
    Generate a bash script for installing Python packages in an init container.
    
    The script uses flock-based locking to prevent concurrent installations
    and includes proper error handling and retry logic.
    
    Args:
        spec: The PythonPackagesSpec containing packages to install
        cache_path: Path where packages will be cached/installed
        lock_file: Path to the lock file for preventing concurrent installs
        timeout: Installation timeout in seconds (from spec or default)
        retries: Number of retry attempts (from spec or default)
        packages_hash: Pre-computed hash (if None, will be computed from spec)
        
    Returns:
        A bash script as a string
    """
    # Use values from install_policy if present
    if hasattr(spec, 'install_policy') and spec.install_policy:
        if hasattr(spec.install_policy, 'timeout') and spec.install_policy.timeout is not None:
            timeout = spec.install_policy.timeout
        if hasattr(spec.install_policy, 'retries') and spec.install_policy.retries is not None:
            retries = spec.install_policy.retries
        on_failure = getattr(spec.install_policy, 'on_failure', None) or "block"
    else:
        on_failure = "block"
    
    # Validate all package names
    invalid_packages = [pkg for pkg in spec.packages if not validate_package_name(pkg)]
    if invalid_packages:
        raise ValueError(f"Invalid package names: {', '.join(invalid_packages)}")
    
    # Build the packages list for pip install (no inner quotes needed -
    # package names are validated to contain no whitespace or shell metacharacters)
    packages_str = " ".join(spec.packages)
    
    # Use provided hash or compute it
    if packages_hash is None:
        packages_hash = compute_packages_hash(spec)
    marker_file = f"{cache_path}/.installed-{packages_hash}"
    
    # Build pip command helper and error detection block
    pip_cmd_helper = _build_pip_install_cmd(cache_path, packages_str)
    error_detection = _build_error_detection_block()
    
    # Stale lock threshold: install timeout + 5 minute buffer
    stale_threshold = timeout + 300
    
    # Generate the script
    script = f"""#!/bin/bash
set -e

echo "Python Package Installer - Starting"
echo "Cache path: {cache_path}"
echo "Packages: {' '.join(spec.packages)}"
echo "Packages hash: {packages_hash}"
echo "Timeout: {timeout}s"
echo "Retries: {retries}"
echo "On failure: {on_failure}"

# Ensure cache directory exists
mkdir -p {cache_path}
mkdir -p "$(dirname {lock_file})"

{pip_cmd_helper}

# Stale lock detection and cleanup
check_stale_lock() {{
    if [ -f "{lock_file}" ]; then
        local lock_mtime=$(stat -c %Y "{lock_file}" 2>/dev/null || stat -f %m "{lock_file}" 2>/dev/null || echo 0)
        local now=$(date +%s)
        local lock_age=$((now - lock_mtime))
        local stale_threshold={stale_threshold}
        
        if [ $lock_age -gt $stale_threshold ]; then
            echo "WARNING: Stale lock detected (${{lock_age}}s old, threshold ${{stale_threshold}}s), removing..."
            rm -f "{lock_file}"
        fi
    fi
}}

# Function to install packages with retry logic
install_packages() {{
    local attempt=1
    local max_attempts={retries}
    local install_start=$(date -u +"%Y-%m-%dT%H:%M:%S.%6N+00:00")
    local install_start_ts=$(date +%s)
    local pip_cmd=$(build_pip_command)
    
    while [ $attempt -le $max_attempts ]; do
        echo "Installation attempt $attempt of $max_attempts"
        
        # Run pip install with timeout, capturing errors
        if timeout {timeout}s bash -c "$pip_cmd" 2>/tmp/pip-error.log; then
            echo "Successfully installed packages"
            
            # Calculate duration
            local install_end_ts=$(date +%s)
            local duration=$((install_end_ts - install_start_ts))
            
            # Create marker file with metadata using proper JSON escaping
            # Build packages array with proper double quotes
            local packages_json=""
            local first=true
            for pkg in {' '.join(spec.packages)}; do
                if [ "$first" = true ]; then
                    packages_json="\\"$pkg\\""
                    first=false
                else
                    packages_json="$packages_json, \\"$pkg\\""
                fi
            done
            
            cat > "{marker_file}" <<EOF
{{
  "packages": [$packages_json],
  "install_time": "$install_start",
  "duration": "${{duration}}s",
  "pod_name": "$HOSTNAME"
}}
EOF
            echo "Created marker file: {marker_file}"
            return 0
        else
            local exit_code=$?
            echo "Installation failed with exit code $exit_code"
            cat /tmp/pip-error.log 2>/dev/null || true
            {error_detection}
            
            if [ $attempt -lt $max_attempts ]; then
                echo "Retrying in 5 seconds..."
                sleep 5
            fi
            attempt=$((attempt + 1))
        fi
    done
    
    echo "Failed to install packages after $max_attempts attempts"
    return 1
}}

# Check for stale locks before acquiring
check_stale_lock

# Acquire lock to prevent concurrent installations
# Use flock with exclusive lock and timeout
exec 200>{lock_file}
if flock -x -w {timeout} 200; then
    echo "Acquired installation lock"
    
    # Check if packages with this hash are already installed
    if [ -f "{marker_file}" ]; then
        echo "Packages with hash {packages_hash} already installed, skipping installation"
        flock -u 200
        exit 0
    fi
    
    # Remove old marker files
    rm -f {cache_path}/.installed-*
    
    # Install packages
    if install_packages; then
        echo "Package installation complete"
        flock -u 200
        exit 0
    else
        flock -u 200
        if [ "{on_failure}" = "block" ]; then
            echo "Installation failed - blocking pod startup"
            exit 1
        else
            echo "Installation failed - allowing pod to start in degraded mode"
            exit 0
        fi
    fi
else
    echo "Failed to acquire installation lock within {timeout}s"
    if [ "{on_failure}" = "block" ]; then
        exit 1
    else
        exit 0
    fi
fi
"""
    
    return script.strip()


def generate_gcs_install_script(
    spec: PythonPackagesSpec,
    cache_path: str = "/opt/kaspr/packages",
    timeout: int = 600,
    retries: int = 3,
    packages_hash: str = None,
    max_archive_size_bytes: int = 1073741824,  # 1Gi
    sa_key_path: str = "/var/run/secrets/gcs/sa.json",
) -> str:
    """
    Generate a bash script for installing Python packages with GCS cache.

    The script flow:
    1. Try downloading a cached archive from GCS (inline Python via urllib).
    2. On cache hit: extract archive and exit.
    3. On cache miss: pip install with retry/error logic.
    4. After successful install: tar + size check + GCS upload (non-fatal).

    GCS operations use inline ``python3 -c`` scripts because the Kaspr base
    image does not ship ``curl``.  Authentication is handled inside the init
    container itself using a mounted service-account key JSON + ``openssl``.

    Args:
        spec: The PythonPackagesSpec containing packages to install
        cache_path: Path where packages will be installed (emptyDir mount)
        timeout: Installation timeout in seconds
        retries: Number of retry attempts
        packages_hash: Pre-computed hash (if None, computed from spec)
        max_archive_size_bytes: Maximum archive size (bytes) to upload
        sa_key_path: Path to mounted SA key JSON file

    Returns:
        A bash script as a string
    """
    # Use values from install_policy if present
    if hasattr(spec, 'install_policy') and spec.install_policy:
        if hasattr(spec.install_policy, 'timeout') and spec.install_policy.timeout is not None:
            timeout = spec.install_policy.timeout
        if hasattr(spec.install_policy, 'retries') and spec.install_policy.retries is not None:
            retries = spec.install_policy.retries
        on_failure = getattr(spec.install_policy, 'on_failure', None) or "block"
    else:
        on_failure = "block"

    # Validate all package names
    invalid_packages = [pkg for pkg in spec.packages if not validate_package_name(pkg)]
    if invalid_packages:
        raise ValueError(f"Invalid package names: {', '.join(invalid_packages)}")

    # Build the packages list for pip install
    packages_str = " ".join(spec.packages)

    # Use provided hash or compute it
    if packages_hash is None:
        packages_hash = compute_packages_hash(spec)

    # Build pip command helper and error detection block
    pip_cmd_helper = _build_pip_install_cmd(cache_path, packages_str)
    error_detection = _build_error_detection_block()

    # Generate inline Python scripts for GCS operations
    download_script = generate_gcs_download_python_script(sa_key_path)
    upload_script = generate_gcs_upload_python_script(sa_key_path, "/tmp/packages.tar.gz")

    script = f"""#!/bin/bash
set -e

echo "Python Package Installer - GCS Cache Mode"
echo "Cache path: {cache_path}"
echo "Packages: {' '.join(spec.packages)}"
echo "Packages hash: {packages_hash}"
echo "Timeout: {timeout}s"
echo "Retries: {retries}"
echo "On failure: {on_failure}"
echo "Max archive size: {max_archive_size_bytes} bytes"

# Ensure install directory exists
mkdir -p {cache_path}

{pip_cmd_helper}

# Function to install packages with retry logic
install_packages() {{
    local attempt=1
    local max_attempts={retries}
    local install_start_ts=$(date +%s)
    local pip_cmd=$(build_pip_command)

    while [ $attempt -le $max_attempts ]; do
        echo "Installation attempt $attempt of $max_attempts"

        if timeout {timeout}s bash -c "$pip_cmd" 2>/tmp/pip-error.log; then
            echo "Successfully installed packages"
            local install_end_ts=$(date +%s)
            local duration=$((install_end_ts - install_start_ts))
            echo "Installation completed in ${{duration}}s"
            return 0
        else
            local exit_code=$?
            echo "Installation failed with exit code $exit_code"
            cat /tmp/pip-error.log 2>/dev/null || true
            {error_detection}

            if [ $attempt -lt $max_attempts ]; then
                echo "Retrying in 5 seconds..."
                sleep 5
            fi
            attempt=$((attempt + 1))
        fi
    done

    echo "Failed to install packages after $max_attempts attempts"
    return 1
}}

# ------------------------------------------------------------------
# Step 1: Try GCS cache download
# ------------------------------------------------------------------
echo "Attempting to download cached packages from GCS..."
GCS_DOWNLOAD_EXIT=0
python3 -c '
{download_script}
' || GCS_DOWNLOAD_EXIT=$?

if [ "$GCS_DOWNLOAD_EXIT" -eq 0 ]; then
    echo "Extracting cached archive..."
    tar xzf /tmp/packages.tar.gz -C {cache_path}
    rm -f /tmp/packages.tar.gz
    echo "Package installation complete (GCS cache hit)"
    exit 0
fi

# ------------------------------------------------------------------
# Step 2: Cache miss — install packages via pip
# ------------------------------------------------------------------
echo "GCS cache miss — falling back to pip install"
if install_packages; then
    echo "Package installation via pip succeeded"
else
    if [ "{on_failure}" = "block" ]; then
        echo "Installation failed - blocking pod startup"
        exit 1
    else
        echo "Installation failed - allowing pod to start in degraded mode"
        exit 0
    fi
fi

# ------------------------------------------------------------------
# Step 3: Archive and upload to GCS (non-fatal)
# ------------------------------------------------------------------
echo "Creating archive for GCS upload..."
tar czf /tmp/packages.tar.gz -C {cache_path} .

# Get archive size (macOS stat vs GNU stat)
ARCHIVE_SIZE=$(stat -f%z /tmp/packages.tar.gz 2>/dev/null || stat -c%s /tmp/packages.tar.gz 2>/dev/null || echo 0)

if [ "$ARCHIVE_SIZE" -le {max_archive_size_bytes} ]; then
    echo "Archive size: ${{ARCHIVE_SIZE}} bytes (limit: {max_archive_size_bytes}), uploading..."
    python3 -c '
{upload_script}
' || true
else
    echo "Archive size ${{ARCHIVE_SIZE}} bytes exceeds limit ({max_archive_size_bytes} bytes), skipping upload"
fi

rm -f /tmp/packages.tar.gz
echo "Package installation complete (GCS cache miss, installed from pip)"
exit 0
"""

    return script.strip()


def generate_emptydir_install_script(
    spec: PythonPackagesSpec,
    cache_path: str = "/opt/kaspr/packages",
    timeout: int = 600,
    retries: int = 3,
) -> str:
    """
    Generate a bash script for installing Python packages in emptyDir mode.
    
    This is used when cache is disabled (cache.enabled=false). Each pod gets its own
    ephemeral storage and packages are always reinstalled on pod start.
    
    Unlike the shared cache mode:
    - No file locking (no concurrent access)
    - No marker files (always reinstall)
    - No hash checking
    - Simpler script structure
    
    Args:
        spec: The PythonPackagesSpec containing packages to install
        cache_path: Path where packages will be installed (emptyDir mount)
        timeout: Installation timeout in seconds
        retries: Number of retry attempts
        
    Returns:
        A bash script as a string
    """
    # Use values from install_policy if present
    if hasattr(spec, 'install_policy') and spec.install_policy:
        if hasattr(spec.install_policy, 'timeout') and spec.install_policy.timeout is not None:
            timeout = spec.install_policy.timeout
        if hasattr(spec.install_policy, 'retries') and spec.install_policy.retries is not None:
            retries = spec.install_policy.retries
        on_failure = getattr(spec.install_policy, 'on_failure', None) or "block"
    else:
        on_failure = "block"
    
    # Validate all package names
    invalid_packages = [pkg for pkg in spec.packages if not validate_package_name(pkg)]
    if invalid_packages:
        raise ValueError(f"Invalid package names: {', '.join(invalid_packages)}")
    
    # Build the packages list for pip install (no inner quotes needed -
    # package names are validated to contain no whitespace or shell metacharacters)
    packages_str = " ".join(spec.packages)
    
    # Build pip command helper and error detection block
    pip_cmd_helper = _build_pip_install_cmd(cache_path, packages_str)
    error_detection = _build_error_detection_block()
    
    # Generate the script
    script = f"""#!/bin/bash
set -e

echo "Python Package Installer - emptyDir Mode"
echo "Install path: {cache_path}"
echo "Packages: {' '.join(spec.packages)}"
echo "Timeout: {timeout}s"
echo "Retries: {retries}"
echo "On failure: {on_failure}"
echo "Note: Packages will be reinstalled on every pod start (emptyDir is ephemeral)"

# Ensure install directory exists
mkdir -p {cache_path}

{pip_cmd_helper}

# Function to install packages with retry logic
install_packages() {{
    local attempt=1
    local max_attempts={retries}
    local install_start=$(date -u +"%Y-%m-%dT%H:%M:%S.%6N+00:00")
    local install_start_ts=$(date +%s)
    local pip_cmd=$(build_pip_command)
    
    while [ $attempt -le $max_attempts ]; do
        echo "Installation attempt $attempt of $max_attempts"
        
        # Run pip install with timeout, capturing errors
        if timeout {timeout}s bash -c "$pip_cmd" 2>/tmp/pip-error.log; then
            echo "Successfully installed packages"
            
            # Calculate duration
            local install_end_ts=$(date +%s)
            local duration=$((install_end_ts - install_start_ts))
            
            echo "Installation completed in ${{duration}}s"
            return 0
        else
            local exit_code=$?
            echo "Installation failed with exit code $exit_code"
            cat /tmp/pip-error.log 2>/dev/null || true
            {error_detection}
            
            if [ $attempt -lt $max_attempts ]; then
                echo "Retrying in 5 seconds..."
                sleep 5
            fi
            attempt=$((attempt + 1))
        fi
    done
    
    echo "Failed to install packages after $max_attempts attempts"
    return 1
}}

# Install packages (no locking needed for emptyDir)
if install_packages; then
    echo "Package installation complete (emptyDir mode)"
    exit 0
else
    if [ "{on_failure}" = "block" ]; then
        echo "Installation failed - blocking pod startup"
        exit 1
    else
        echo "Installation failed - allowing pod to start in degraded mode"
        exit 0
    fi
fi
"""
    
    return script.strip()

