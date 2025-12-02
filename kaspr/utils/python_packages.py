"""Utility functions for Python package management."""

import hashlib
import json
import re

from kaspr.types.models.python_packages import PythonPackagesSpec


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
    
    # Build the packages list for pip install
    packages_str = " ".join(f'"{pkg}"' for pkg in spec.packages)
    
    # Use provided hash or compute it
    if packages_hash is None:
        packages_hash = compute_packages_hash(spec)
    marker_file = f"{cache_path}/.installed-{packages_hash}"
    
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

# Function to install packages with retry logic
install_packages() {{
    local attempt=1
    local max_attempts={retries}
    local install_start=$(date -u +"%Y-%m-%dT%H:%M:%S.%6N+00:00")
    local install_start_ts=$(date +%s)
    
    while [ $attempt -le $max_attempts ]; do
        echo "Installation attempt $attempt of $max_attempts"
        
        # Run pip install with timeout
        if timeout {timeout}s pip install --no-warn-script-location \\
            --target {cache_path} \\
            --no-cache-dir \\
            {packages_str}; then
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
    
    # Build the packages list for pip install
    packages_str = " ".join(f'"{pkg}"' for pkg in spec.packages)
    
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

# Function to install packages with retry logic
install_packages() {{
    local attempt=1
    local max_attempts={retries}
    local install_start=$(date -u +"%Y-%m-%dT%H:%M:%S.%6N+00:00")
    local install_start_ts=$(date +%s)
    
    while [ $attempt -le $max_attempts ]; do
        echo "Installation attempt $attempt of $max_attempts"
        
        # Run pip install with timeout
        if timeout {timeout}s pip install --no-warn-script-location \\
            --target {cache_path} \\
            --no-cache-dir \\
            {packages_str}; then
            echo "Successfully installed packages"
            
            # Calculate duration
            local install_end_ts=$(date +%s)
            local duration=$((install_end_ts - install_start_ts))
            
            echo "Installation completed in ${{duration}}s"
            return 0
        else
            local exit_code=$?
            echo "Installation failed with exit code $exit_code"
            
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

