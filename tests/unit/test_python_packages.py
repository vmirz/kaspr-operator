"""Unit tests for Python packages models and schemas."""

import pytest
from marshmallow import ValidationError
from kaspr.types.models.python_packages import (
    PythonPackagesCache,
    PythonPackagesInstallPolicy,
    PythonPackagesResources,
    PythonPackagesSpec,
    PythonPackagesStatus,
)
from kaspr.types.schemas.python_packages import (
    PythonPackagesCacheSchema,
    PythonPackagesInstallPolicySchema,
    PythonPackagesResourcesSchema,
    PythonPackagesSpecSchema,
    PythonPackagesStatusSchema,
)


class TestPythonPackagesCache:
    """Tests for PythonPackagesCache model and schema."""
    
    def test_cache_model_instantiation(self):
        """Test cache model can be instantiated."""
        cache = PythonPackagesCache(
            enabled=True,
            storage_class="fast-nfs",
            size="1Gi",
            access_mode="ReadWriteMany",
            delete_claim=True
        )
        assert cache.enabled is True
        assert cache.storage_class == "fast-nfs"
        assert cache.size == "1Gi"
        assert cache.access_mode == "ReadWriteMany"
        assert cache.delete_claim is True
    
    def test_cache_schema_valid(self):
        """Test cache schema with valid data."""
        schema = PythonPackagesCacheSchema()
        data = {
            "enabled": True,
            "storageClass": "fast-nfs",
            "size": "5Gi",
            "accessMode": "ReadWriteMany",
            "deleteClaim": False
        }
        result = schema.load(data)
        assert isinstance(result, PythonPackagesCache)
        assert result.enabled is True
        assert result.storage_class == "fast-nfs"
        assert result.size == "5Gi"
        assert result.access_mode == "ReadWriteMany"
        assert result.delete_claim is False
    
    def test_cache_schema_invalid_access_mode(self):
        """Test cache schema rejects invalid access mode."""
        schema = PythonPackagesCacheSchema()
        data = {
            "accessMode": "InvalidMode"
        }
        with pytest.raises(ValidationError) as exc_info:
            schema.load(data)
        assert "Invalid access mode" in str(exc_info.value)
    
    def test_cache_schema_optional_fields(self):
        """Test cache schema with optional fields."""
        schema = PythonPackagesCacheSchema()
        data = {}
        result = schema.load(data)
        assert isinstance(result, PythonPackagesCache)


class TestPythonPackagesInstallPolicy:
    """Tests for PythonPackagesInstallPolicy model and schema."""
    
    def test_install_policy_model_instantiation(self):
        """Test install policy model can be instantiated."""
        policy = PythonPackagesInstallPolicy(
            retries=3,
            timeout=600,
            on_failure="block"
        )
        assert policy.retries == 3
        assert policy.timeout == 600
        assert policy.on_failure == "block"
    
    def test_install_policy_schema_valid(self):
        """Test install policy schema with valid data."""
        schema = PythonPackagesInstallPolicySchema()
        data = {
            "retries": 5,
            "timeout": 300,
            "onFailure": "allow"
        }
        result = schema.load(data)
        assert isinstance(result, PythonPackagesInstallPolicy)
        assert result.retries == 5
        assert result.timeout == 300
        assert result.on_failure == "allow"
    
    def test_install_policy_schema_negative_retries(self):
        """Test install policy schema rejects negative retries."""
        schema = PythonPackagesInstallPolicySchema()
        data = {"retries": -1}
        with pytest.raises(ValidationError) as exc_info:
            schema.load(data)
        assert "non-negative" in str(exc_info.value)
    
    def test_install_policy_schema_low_timeout(self):
        """Test install policy schema rejects low timeout."""
        schema = PythonPackagesInstallPolicySchema()
        data = {"timeout": 30}
        with pytest.raises(ValidationError) as exc_info:
            schema.load(data)
        assert "at least 60 seconds" in str(exc_info.value)
    
    def test_install_policy_schema_invalid_on_failure(self):
        """Test install policy schema rejects invalid onFailure value."""
        schema = PythonPackagesInstallPolicySchema()
        data = {"onFailure": "invalid"}
        with pytest.raises(ValidationError) as exc_info:
            schema.load(data)
        assert "Invalid onFailure value" in str(exc_info.value)


class TestPythonPackagesResources:
    """Tests for PythonPackagesResources model and schema."""
    
    def test_resources_model_instantiation(self):
        """Test resources model can be instantiated."""
        resources = PythonPackagesResources(
            requests={"memory": "512Mi", "cpu": "250m"},
            limits={"memory": "2Gi", "cpu": "1000m"}
        )
        assert resources.requests == {"memory": "512Mi", "cpu": "250m"}
        assert resources.limits == {"memory": "2Gi", "cpu": "1000m"}
    
    def test_resources_schema_valid(self):
        """Test resources schema with valid data."""
        schema = PythonPackagesResourcesSchema()
        data = {
            "requests": {"memory": "512Mi", "cpu": "250m"},
            "limits": {"memory": "2Gi", "cpu": "1000m"}
        }
        result = schema.load(data)
        assert isinstance(result, PythonPackagesResources)
        assert result.requests == {"memory": "512Mi", "cpu": "250m"}
        assert result.limits == {"memory": "2Gi", "cpu": "1000m"}


class TestPythonPackagesSpec:
    """Tests for PythonPackagesSpec model and schema."""
    
    def test_spec_model_instantiation(self):
        """Test spec model can be instantiated."""
        spec = PythonPackagesSpec(
            packages=["requests==2.31.0", "pandas>=2.0.0"]
        )
        assert spec.packages == ["requests==2.31.0", "pandas>=2.0.0"]
    
    def test_spec_schema_valid_simple(self):
        """Test spec schema with simple package list."""
        schema = PythonPackagesSpecSchema()
        data = {
            "packages": ["requests==2.31.0", "pandas>=2.0.0", "sqlalchemy"]
        }
        result = schema.load(data)
        assert isinstance(result, PythonPackagesSpec)
        assert len(result.packages) == 3
        assert "requests==2.31.0" in result.packages
    
    def test_spec_schema_valid_with_cache(self):
        """Test spec schema with cache configuration."""
        schema = PythonPackagesSpecSchema()
        data = {
            "packages": ["requests==2.31.0"],
            "cache": {
                "enabled": True,
                "size": "5Gi"
            }
        }
        result = schema.load(data)
        assert isinstance(result, PythonPackagesSpec)
        assert isinstance(result.cache, PythonPackagesCache)
        assert result.cache.enabled is True
        assert result.cache.size == "5Gi"
    
    def test_spec_schema_valid_with_install_policy(self):
        """Test spec schema with install policy."""
        schema = PythonPackagesSpecSchema()
        data = {
            "packages": ["requests==2.31.0"],
            "installPolicy": {
                "retries": 3,
                "timeout": 600
            }
        }
        result = schema.load(data)
        assert isinstance(result, PythonPackagesSpec)
        assert isinstance(result.install_policy, PythonPackagesInstallPolicy)
        assert result.install_policy.retries == 3
    
    def test_spec_schema_valid_with_resources(self):
        """Test spec schema with resources."""
        schema = PythonPackagesSpecSchema()
        data = {
            "packages": ["requests==2.31.0"],
            "resources": {
                "requests": {"memory": "512Mi"}
            }
        }
        result = schema.load(data)
        assert isinstance(result, PythonPackagesSpec)
        assert isinstance(result.resources, PythonPackagesResources)
    
    def test_spec_schema_empty_packages(self):
        """Test spec schema rejects empty package list."""
        schema = PythonPackagesSpecSchema()
        data = {"packages": []}
        with pytest.raises(ValidationError) as exc_info:
            schema.load(data)
        assert "cannot be empty" in str(exc_info.value)
    
    def test_spec_schema_missing_packages(self):
        """Test spec schema requires packages field."""
        schema = PythonPackagesSpecSchema()
        data = {}
        with pytest.raises(ValidationError) as exc_info:
            schema.load(data)
        assert "packages" in str(exc_info.value)
    
    def test_spec_schema_invalid_package_whitespace(self):
        """Test spec schema rejects packages with whitespace."""
        schema = PythonPackagesSpecSchema()
        data = {"packages": ["requests == 2.31.0"]}  # Space around ==
        with pytest.raises(ValidationError) as exc_info:
            schema.load(data)
        assert "invalid whitespace" in str(exc_info.value)
    
    def test_spec_schema_various_package_formats(self):
        """Test spec schema accepts various valid package formats."""
        schema = PythonPackagesSpecSchema()
        data = {
            "packages": [
                "requests",  # No version
                "pandas==2.1.0",  # Exact version
                "numpy>=1.24.0",  # Minimum version
                "sqlalchemy>=2.0.0,<3.0.0",  # Version range
                "psycopg2-binary",  # Package with dash
            ]
        }
        result = schema.load(data)
        assert isinstance(result, PythonPackagesSpec)
        assert len(result.packages) == 5


class TestPythonPackagesStatus:
    """Tests for PythonPackagesStatus model and schema."""
    
    def test_status_model_instantiation(self):
        """Test status model can be instantiated."""
        status = PythonPackagesStatus(
            state="Ready",
            hash="abc123",
            installed=["requests==2.31.0"],
            cache_mode="shared-pvc"
        )
        assert status.state == "Ready"
        assert status.hash == "abc123"
        assert status.installed == ["requests==2.31.0"]
        assert status.cache_mode == "shared-pvc"
    
    def test_status_schema_valid(self):
        """Test status schema with valid data."""
        schema = PythonPackagesStatusSchema()
        data = {
            "hash": "abc123def456",
            "installed": ["requests==2.31.0", "pandas==2.1.0"],
            "cacheMode": "shared-pvc",
            "lastInstallTime": "2025-11-28T10:00:00.123456+00:00",
            "installDuration": "45s",
            "installedBy": "my-app-0"
        }
        result = schema.load(data)
        assert isinstance(result, PythonPackagesStatus)
        assert result.hash == "abc123def456"
        assert len(result.installed) == 2
        assert result.cache_mode == "shared-pvc"
        assert result.last_install_time == "2025-11-28T10:00:00.123456+00:00"
        assert result.install_duration == "45s"
        assert result.installed_by == "my-app-0"
    
    def test_status_schema_with_warnings(self):
        """Test status schema with warnings."""
        schema = PythonPackagesStatusSchema()
        data = {
            "hash": "def456abc123",
            "warnings": ["Package 'requests' not pinned to specific version", "Old marker file found"]
        }
        result = schema.load(data)
        assert isinstance(result, PythonPackagesStatus)
        assert result.hash == "def456abc123"
        assert len(result.warnings) == 2
    
    def test_status_schema_optional_fields(self):
        """Test status schema with minimal data."""
        schema = PythonPackagesStatusSchema()
        data = {}
        result = schema.load(data)
        assert isinstance(result, PythonPackagesStatus)


class TestPythonPackagesUtilities:
    """Tests for Python packages utility functions."""
    
    def test_compute_packages_hash_basic(self):
        """Test hash computation with basic package list."""
        from kaspr.utils.python_packages import compute_packages_hash
        
        spec = PythonPackagesSpec(packages=["requests", "numpy"])
        hash1 = compute_packages_hash(spec)
        
        # Hash should be deterministic
        hash2 = compute_packages_hash(spec)
        assert hash1 == hash2
        
        # Hash should be 16 characters
        assert len(hash1) == 16
        
        # Hash should be hex
        assert all(c in '0123456789abcdef' for c in hash1)
    
    def test_compute_packages_hash_order_independence(self):
        """Test that package order doesn't affect hash."""
        from kaspr.utils.python_packages import compute_packages_hash
        
        spec1 = PythonPackagesSpec(packages=["requests", "numpy", "pandas"])
        spec2 = PythonPackagesSpec(packages=["pandas", "numpy", "requests"])
        
        hash1 = compute_packages_hash(spec1)
        hash2 = compute_packages_hash(spec2)
        
        # Hash should be the same regardless of order
        assert hash1 == hash2
    
    def test_compute_packages_hash_different_packages(self):
        """Test that different packages produce different hashes."""
        from kaspr.utils.python_packages import compute_packages_hash
        
        spec1 = PythonPackagesSpec(packages=["requests", "numpy"])
        spec2 = PythonPackagesSpec(packages=["requests", "pandas"])
        
        hash1 = compute_packages_hash(spec1)
        hash2 = compute_packages_hash(spec2)
        
        # Different packages should produce different hashes
        assert hash1 != hash2
    
    def test_compute_packages_hash_with_install_policy(self):
        """Test hash includes install policy."""
        from kaspr.utils.python_packages import compute_packages_hash
        
        spec1 = PythonPackagesSpec(
            packages=["requests"],
            install_policy=PythonPackagesInstallPolicy(retries=3)
        )
        spec2 = PythonPackagesSpec(
            packages=["requests"],
            install_policy=PythonPackagesInstallPolicy(retries=5)
        )
        
        hash1 = compute_packages_hash(spec1)
        hash2 = compute_packages_hash(spec2)
        
        # Different install policies should produce different hashes
        assert hash1 != hash2
    
    def test_validate_package_name_valid(self):
        """Test package name validation with valid names."""
        from kaspr.utils.python_packages import validate_package_name
        
        valid_packages = [
            "requests",
            "numpy",
            "scikit-learn",
            "python_dateutil",
            "requests==2.28.0",
            "numpy>=1.24.0",
            "pandas>=2.0.0,<3.0.0",
            "scipy[all]",
            "tensorflow>=2.0.0",
            "Django~=4.2.0",
            "pillow!=9.0.0",
            "boto3>1.0.0",
            "urllib3<2.0.0",
        ]
        
        for package in valid_packages:
            assert validate_package_name(package), f"Expected {package} to be valid"
    
    def test_validate_package_name_invalid(self):
        """Test package name validation with invalid names."""
        from kaspr.utils.python_packages import validate_package_name
        
        invalid_packages = [
            "",  # Empty string
            "   ",  # Whitespace only
            "-invalid",  # Starts with hyphen
            "_invalid",  # Starts with underscore
            "in valid",  # Contains space
            "in@valid",  # Contains invalid character
        ]
        
        for package in invalid_packages:
            assert not validate_package_name(package), f"Expected {package} to be invalid"
    
    def test_validate_package_name_edge_cases(self):
        """Test package name validation edge cases."""
        from kaspr.utils.python_packages import validate_package_name
        
        assert not validate_package_name(None)
        assert not validate_package_name(123)
        assert not validate_package_name([])
        assert not validate_package_name({})
    
    def test_generate_install_script_basic(self):
        """Test basic install script generation."""
        from kaspr.utils.python_packages import generate_install_script
        
        spec = PythonPackagesSpec(packages=["requests", "numpy"])
        script = generate_install_script(spec)
        
        assert "#!/bin/bash" in script
        assert "requests" in script
        assert "numpy" in script
        assert "pip install" in script
        assert "flock" in script
        assert "/opt/kaspr/packages" in script
    
    def test_generate_install_script_with_install_policy(self):
        """Test script generation with custom install policy."""
        from kaspr.utils.python_packages import generate_install_script
        
        spec = PythonPackagesSpec(
            packages=["pandas"],
            install_policy=PythonPackagesInstallPolicy(
                retries=5,
                timeout=1200,
                on_failure="allow"
            )
        )
        script = generate_install_script(spec)
        
        assert "pandas" in script
        assert "max_attempts=5" in script
        assert "timeout 1200s" in script
        assert "On failure: allow" in script
    
    def test_generate_install_script_custom_paths(self):
        """Test script generation with custom paths."""
        from kaspr.utils.python_packages import generate_install_script
        
        spec = PythonPackagesSpec(packages=["scipy"])
        script = generate_install_script(
            spec,
            cache_path="/custom/cache",
            lock_file="/custom/lock",
        )
        
        assert "/custom/cache" in script
        assert "/custom/lock" in script
    
    def test_generate_install_script_invalid_package(self):
        """Test script generation fails with invalid package names."""
        from kaspr.utils.python_packages import generate_install_script
        
        spec = PythonPackagesSpec(packages=["invalid package"])
        
        with pytest.raises(ValueError) as exc_info:
            generate_install_script(spec)
        
        assert "Invalid package names" in str(exc_info.value)
    
    def test_generate_install_script_retry_logic(self):
        """Test that script contains proper retry logic."""
        from kaspr.utils.python_packages import generate_install_script
        
        spec = PythonPackagesSpec(
            packages=["requests"],
            install_policy=PythonPackagesInstallPolicy(retries=3)
        )
        script = generate_install_script(spec)
        
        # Check for retry logic
        assert "while [ $attempt -le $max_attempts ]" in script
        assert "attempt=$((attempt + 1))" in script
        assert "Retrying in" in script
    
    def test_generate_install_script_lock_mechanism(self):
        """Test that script contains flock-based locking."""
        from kaspr.utils.python_packages import generate_install_script
        
        spec = PythonPackagesSpec(packages=["numpy"])
        script = generate_install_script(spec)
        
        # Check for flock usage
        assert "flock -x" in script
        assert "exec 200>" in script
        assert ".install.lock" in script
        assert "Acquired installation lock" in script
    
    def test_generate_install_script_error_handling(self):
        """Test that script contains proper error handling."""
        from kaspr.utils.python_packages import generate_install_script
        
        spec = PythonPackagesSpec(
            packages=["pandas"],
            install_policy=PythonPackagesInstallPolicy(on_failure="block")
        )
        script = generate_install_script(spec)
        
        # Check for error handling
        assert "set -e" in script
        assert "exit_code=$?" in script
        assert "Installation failed" in script
        assert "blocking pod startup" in script

