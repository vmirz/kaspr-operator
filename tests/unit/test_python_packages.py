"""Unit tests for Python packages models and schemas."""

import pytest
from marshmallow import ValidationError
from kaspr.types.models.python_packages import (
    GCSCacheConfig,
    GCSSecretReference,
    PythonPackagesCache,
    PythonPackagesCredentials,
    PythonPackagesInstallPolicy,
    PythonPackagesResources,
    PythonPackagesSpec,
    PythonPackagesStatus,
    SecretReference,
)
from kaspr.types.schemas.python_packages import (
    GCSCacheConfigSchema,
    GCSSecretReferenceSchema,
    PythonPackagesCacheSchema,
    PythonPackagesCredentialsSchema,
    PythonPackagesInstallPolicySchema,
    PythonPackagesResourcesSchema,
    PythonPackagesSpecSchema,
    PythonPackagesStatusSchema,
    SecretReferenceSchema,
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
        """Test cache schema rejects non-ReadWriteMany access mode."""
        schema = PythonPackagesCacheSchema()
        data = {
            "accessMode": "ReadWriteOnce"
        }
        with pytest.raises(ValidationError) as exc_info:
            schema.load(data)
        assert "Only 'ReadWriteMany' is currently supported" in str(exc_info.value)
    
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


# =============================================================================
# Phase 2 Tests
# =============================================================================


class TestSecretReference:
    """Tests for SecretReference model and schema."""

    def test_secret_reference_model_instantiation(self):
        """Test SecretReference model can be instantiated."""
        ref = SecretReference(
            name="my-secret",
            username_key="user",
            password_key="pass",
        )
        assert ref.name == "my-secret"
        assert ref.username_key == "user"
        assert ref.password_key == "pass"

    def test_secret_reference_schema_valid(self):
        """Test SecretReferenceSchema with valid data."""
        schema = SecretReferenceSchema()
        data = {
            "name": "pypi-credentials",
            "usernameKey": "user",
            "passwordKey": "token",
        }
        result = schema.load(data)
        assert isinstance(result, SecretReference)
        assert result.name == "pypi-credentials"
        assert result.username_key == "user"
        assert result.password_key == "token"

    def test_secret_reference_schema_name_required(self):
        """Test SecretReferenceSchema requires name."""
        schema = SecretReferenceSchema()
        with pytest.raises(ValidationError) as exc_info:
            schema.load({})
        assert "name" in str(exc_info.value)

    def test_secret_reference_schema_optional_keys(self):
        """Test SecretReferenceSchema with only name."""
        schema = SecretReferenceSchema()
        result = schema.load({"name": "my-secret"})
        assert isinstance(result, SecretReference)
        assert result.name == "my-secret"
        assert result.username_key is None
        assert result.password_key is None


class TestPythonPackagesCredentials:
    """Tests for PythonPackagesCredentials model and schema."""

    def test_credentials_model_instantiation(self):
        """Test PythonPackagesCredentials model can be instantiated."""
        ref = SecretReference(name="my-secret")
        creds = PythonPackagesCredentials(secret_ref=ref)
        assert creds.secret_ref.name == "my-secret"

    def test_credentials_schema_valid(self):
        """Test PythonPackagesCredentialsSchema with valid data."""
        schema = PythonPackagesCredentialsSchema()
        data = {
            "secretRef": {
                "name": "pypi-creds",
                "usernameKey": "user",
                "passwordKey": "pass",
            }
        }
        result = schema.load(data)
        assert isinstance(result, PythonPackagesCredentials)
        assert result.secret_ref.name == "pypi-creds"
        assert result.secret_ref.username_key == "user"
        assert result.secret_ref.password_key == "pass"

    def test_credentials_schema_requires_secret_ref(self):
        """Test PythonPackagesCredentialsSchema requires secretRef."""
        schema = PythonPackagesCredentialsSchema()
        with pytest.raises(ValidationError):
            schema.load({})


class TestPythonPackagesSpecPhase2:
    """Tests for Phase 2 fields on PythonPackagesSpec."""

    def test_spec_with_index_url(self):
        """Test spec schema with indexUrl."""
        schema = PythonPackagesSpecSchema()
        data = {
            "packages": ["requests"],
            "indexUrl": "https://pypi.company.com/simple",
        }
        result = schema.load(data)
        assert result.index_url == "https://pypi.company.com/simple"

    def test_spec_with_extra_index_urls(self):
        """Test spec schema with extraIndexUrls."""
        schema = PythonPackagesSpecSchema()
        data = {
            "packages": ["requests"],
            "extraIndexUrls": [
                "https://pypi.company.com/simple",
                "https://internal.example.com/simple",
            ],
        }
        result = schema.load(data)
        assert len(result.extra_index_urls) == 2

    def test_spec_with_trusted_hosts(self):
        """Test spec schema with trustedHosts."""
        schema = PythonPackagesSpecSchema()
        data = {
            "packages": ["requests"],
            "trustedHosts": ["pypi.company.com", "internal.example.com"],
        }
        result = schema.load(data)
        assert len(result.trusted_hosts) == 2

    def test_spec_with_credentials(self):
        """Test spec schema with credentials."""
        schema = PythonPackagesSpecSchema()
        data = {
            "packages": ["my-lib"],
            "indexUrl": "https://pypi.company.com/simple",
            "credentials": {
                "secretRef": {
                    "name": "pypi-credentials",
                }
            },
        }
        result = schema.load(data)
        assert isinstance(result.credentials, PythonPackagesCredentials)
        assert result.credentials.secret_ref.name == "pypi-credentials"

    def test_spec_invalid_index_url(self):
        """Test spec schema rejects invalid indexUrl."""
        schema = PythonPackagesSpecSchema()
        data = {
            "packages": ["requests"],
            "indexUrl": "ftp://invalid.com/simple",
        }
        with pytest.raises(ValidationError) as exc_info:
            schema.load(data)
        assert "http://" in str(exc_info.value) or "https://" in str(exc_info.value)

    def test_spec_invalid_extra_index_url(self):
        """Test spec schema rejects invalid extraIndexUrls."""
        schema = PythonPackagesSpecSchema()
        data = {
            "packages": ["requests"],
            "extraIndexUrls": ["not-a-url"],
        }
        with pytest.raises(ValidationError) as exc_info:
            schema.load(data)
        assert "http://" in str(exc_info.value) or "https://" in str(exc_info.value)

    def test_spec_full_phase2_config(self):
        """Test spec schema with all Phase 2 fields."""
        schema = PythonPackagesSpecSchema()
        data = {
            "packages": ["my-lib==1.0.0", "internal-utils>=2.0.0"],
            "indexUrl": "https://artifacts.company.com/pypi/simple",
            "extraIndexUrls": ["https://pypi.org/simple"],
            "trustedHosts": ["artifacts.company.com"],
            "credentials": {
                "secretRef": {
                    "name": "prod-pypi-creds",
                    "usernameKey": "svc-user",
                    "passwordKey": "svc-token",
                }
            },
            "installPolicy": {
                "retries": 3,
                "timeout": 900,
                "onFailure": "block",
            },
            "cache": {
                "enabled": True,
                "size": "20Gi",
            },
        }
        result = schema.load(data)
        assert isinstance(result, PythonPackagesSpec)
        assert result.index_url == "https://artifacts.company.com/pypi/simple"
        assert result.extra_index_urls == ["https://pypi.org/simple"]
        assert result.trusted_hosts == ["artifacts.company.com"]
        assert result.credentials.secret_ref.name == "prod-pypi-creds"
        assert result.credentials.secret_ref.username_key == "svc-user"
        assert result.install_policy.retries == 3
        assert result.cache.size == "20Gi"


class TestPhase2HashComputation:
    """Tests for hash computation with Phase 2 fields."""

    def test_hash_changes_with_index_url(self):
        """Test hash changes when indexUrl is set."""
        from kaspr.utils.python_packages import compute_packages_hash

        spec1 = PythonPackagesSpec(packages=["requests"])
        spec2 = PythonPackagesSpec(
            packages=["requests"],
            index_url="https://pypi.company.com/simple",
        )
        assert compute_packages_hash(spec1) != compute_packages_hash(spec2)

    def test_hash_changes_with_extra_index_urls(self):
        """Test hash changes when extraIndexUrls change."""
        from kaspr.utils.python_packages import compute_packages_hash

        spec1 = PythonPackagesSpec(packages=["requests"])
        spec2 = PythonPackagesSpec(
            packages=["requests"],
            extra_index_urls=["https://private.example.com/simple"],
        )
        assert compute_packages_hash(spec1) != compute_packages_hash(spec2)

    def test_hash_changes_with_trusted_hosts(self):
        """Test hash changes when trustedHosts change."""
        from kaspr.utils.python_packages import compute_packages_hash

        spec1 = PythonPackagesSpec(packages=["requests"])
        spec2 = PythonPackagesSpec(
            packages=["requests"],
            trusted_hosts=["private.example.com"],
        )
        assert compute_packages_hash(spec1) != compute_packages_hash(spec2)

    def test_hash_stable_with_extra_index_order(self):
        """Test hash is order-independent for extraIndexUrls."""
        from kaspr.utils.python_packages import compute_packages_hash

        spec1 = PythonPackagesSpec(
            packages=["requests"],
            extra_index_urls=["https://a.com/simple", "https://b.com/simple"],
        )
        spec2 = PythonPackagesSpec(
            packages=["requests"],
            extra_index_urls=["https://b.com/simple", "https://a.com/simple"],
        )
        assert compute_packages_hash(spec1) == compute_packages_hash(spec2)

    def test_hash_does_not_include_credentials(self):
        """Test hash does not change when credentials are added (credentials don't affect packages)."""
        from kaspr.utils.python_packages import compute_packages_hash

        spec1 = PythonPackagesSpec(
            packages=["requests"],
            index_url="https://pypi.company.com/simple",
        )
        spec2 = PythonPackagesSpec(
            packages=["requests"],
            index_url="https://pypi.company.com/simple",
            credentials=PythonPackagesCredentials(
                secret_ref=SecretReference(name="my-secret")
            ),
        )
        # Credentials should not change the hash (same packages, same index)
        assert compute_packages_hash(spec1) == compute_packages_hash(spec2)


class TestPhase2InstallScript:
    """Tests for Phase 2 install script features."""

    def test_stale_lock_detection_in_script(self):
        """Test install script contains stale lock detection."""
        from kaspr.utils.python_packages import generate_install_script

        spec = PythonPackagesSpec(packages=["requests"])
        script = generate_install_script(spec)
        assert "check_stale_lock" in script
        assert "Stale lock detected" in script
        assert "stat -c %Y" in script  # Linux stat
        assert "stat -f %m" in script  # macOS fallback

    def test_stale_lock_threshold_matches_timeout(self):
        """Test stale lock threshold is timeout + 300s."""
        from kaspr.utils.python_packages import generate_install_script

        spec = PythonPackagesSpec(
            packages=["requests"],
            install_policy=PythonPackagesInstallPolicy(timeout=1200),
        )
        script = generate_install_script(spec)
        # threshold = 1200 + 300 = 1500
        assert "stale_threshold=1500" in script

    def test_pip_command_builder_in_script(self):
        """Test install script contains pip command builder function."""
        from kaspr.utils.python_packages import generate_install_script

        spec = PythonPackagesSpec(packages=["requests"])
        script = generate_install_script(spec)
        assert "build_pip_command()" in script
        assert "pip install" in script
        assert "INDEX_URL" in script
        assert "PYPI_USERNAME" in script
        assert "PYPI_PASSWORD" in script
        assert "EXTRA_INDEX_URLS" in script
        assert "TRUSTED_HOSTS" in script

    def test_error_detection_block_in_script(self):
        """Test install script contains error detection block."""
        from kaspr.utils.python_packages import generate_install_script

        spec = PythonPackagesSpec(packages=["requests"])
        script = generate_install_script(spec)
        assert "ERROR_TYPE:" in script
        assert "ERROR_MSG:" in script
        assert "package_not_found" in script
        assert "authentication" in script
        assert "network" in script
        assert "hash_mismatch" in script
        assert "/tmp/pip-error.log" in script

    def test_emptydir_script_has_pip_command_builder(self):
        """Test emptyDir script contains pip command builder."""
        from kaspr.utils.python_packages import generate_emptydir_install_script

        spec = PythonPackagesSpec(packages=["requests"])
        script = generate_emptydir_install_script(spec)
        assert "build_pip_command()" in script
        assert "emptyDir" in script
        # Should NOT have flock
        assert "flock" not in script
        assert "check_stale_lock" not in script

    def test_emptydir_script_has_error_detection(self):
        """Test emptyDir script contains error detection."""
        from kaspr.utils.python_packages import generate_emptydir_install_script

        spec = PythonPackagesSpec(packages=["requests"])
        script = generate_emptydir_install_script(spec)
        assert "ERROR_TYPE:" in script
        assert "/tmp/pip-error.log" in script

    def test_error_messages_dict(self):
        """Test ERROR_MESSAGES contains expected keys."""
        from kaspr.utils.python_packages import ERROR_MESSAGES

        assert "network" in ERROR_MESSAGES
        assert "package_not_found" in ERROR_MESSAGES
        assert "hash_mismatch" in ERROR_MESSAGES
        assert "authentication" in ERROR_MESSAGES
        assert "timeout" in ERROR_MESSAGES


class TestGCSSecretReference:
    """Tests for GCSSecretReference model and schema."""

    def test_model_instantiation(self):
        ref = GCSSecretReference(name="gcs-sa-key")
        assert ref.name == "gcs-sa-key"
        assert not hasattr(ref, 'key')

    def test_model_with_custom_key(self):
        ref = GCSSecretReference(name="gcs-sa-key", key="credentials.json")
        assert ref.key == "credentials.json"

    def test_schema_valid(self):
        schema = GCSSecretReferenceSchema()
        result = schema.load({"name": "my-secret", "key": "sa.json"})
        assert isinstance(result, GCSSecretReference)
        assert result.name == "my-secret"
        assert result.key == "sa.json"

    def test_schema_name_required(self):
        schema = GCSSecretReferenceSchema()
        with pytest.raises(ValidationError):
            schema.load({})

    def test_schema_key_optional(self):
        schema = GCSSecretReferenceSchema()
        result = schema.load({"name": "my-secret"})
        assert result.key is None


class TestGCSCacheConfig:
    """Tests for GCSCacheConfig model and schema."""

    def test_model_instantiation(self):
        ref = GCSSecretReference(name="gcs-sa-key")
        config = GCSCacheConfig(bucket="my-bucket", secret_ref=ref)
        assert config.bucket == "my-bucket"
        assert not hasattr(config, 'prefix')
        assert not hasattr(config, 'max_archive_size')
        assert config.secret_ref.name == "gcs-sa-key"

    def test_model_with_all_fields(self):
        ref = GCSSecretReference(name="gcs-sa-key", key="key.json")
        config = GCSCacheConfig(
            bucket="my-bucket",
            prefix="custom/prefix/",
            max_archive_size="2Gi",
            secret_ref=ref,
        )
        assert config.prefix == "custom/prefix/"
        assert config.max_archive_size == "2Gi"

    def test_schema_valid(self):
        schema = GCSCacheConfigSchema()
        data = {
            "bucket": "my-bucket",
            "prefix": "kaspr-packages/",
            "maxArchiveSize": "1Gi",
            "secretRef": {"name": "gcs-sa-key", "key": "sa.json"},
        }
        result = schema.load(data)
        assert isinstance(result, GCSCacheConfig)
        assert result.bucket == "my-bucket"
        assert result.prefix == "kaspr-packages/"
        assert result.max_archive_size == "1Gi"
        assert result.secret_ref.name == "gcs-sa-key"

    def test_schema_bucket_required(self):
        schema = GCSCacheConfigSchema()
        with pytest.raises(ValidationError):
            schema.load({"secretRef": {"name": "s"}})

    def test_schema_secret_ref_required(self):
        schema = GCSCacheConfigSchema()
        with pytest.raises(ValidationError):
            schema.load({"bucket": "b"})


class TestPythonPackagesCacheGCS:
    """Tests for PythonPackagesCache with GCS type."""

    def test_cache_with_gcs_type(self):
        schema = PythonPackagesCacheSchema()
        data = {
            "type": "gcs",
            "gcs": {
                "bucket": "my-bucket",
                "secretRef": {"name": "gcs-key"},
            },
        }
        result = schema.load(data)
        assert result.type == "gcs"
        assert result.gcs.bucket == "my-bucket"
        assert result.gcs.secret_ref.name == "gcs-key"

    def test_cache_with_pvc_type(self):
        schema = PythonPackagesCacheSchema()
        data = {"type": "pvc", "enabled": True}
        result = schema.load(data)
        assert result.type == "pvc"

    def test_cache_invalid_type(self):
        schema = PythonPackagesCacheSchema()
        data = {"type": "s3"}
        with pytest.raises(ValidationError, match="Must be one of"):
            schema.load(data)

    def test_gcs_type_requires_gcs_config(self):
        schema = PythonPackagesCacheSchema()
        data = {"type": "gcs"}
        with pytest.raises(ValidationError, match="gcs"):
            schema.load(data)

    def test_cache_no_type_defaults_to_none(self):
        schema = PythonPackagesCacheSchema()
        data = {"enabled": True}
        result = schema.load(data)
        assert result.type is None

    def test_gcs_type_with_enabled_emits_warning(self):
        """Setting enabled with type=gcs should emit a UserWarning."""
        import warnings
        schema = PythonPackagesCacheSchema()
        data = {
            "type": "gcs",
            "enabled": True,
            "gcs": {
                "bucket": "my-bucket",
                "secretRef": {"name": "gcs-key"},
            },
        }
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = schema.load(data)
            assert len(w) == 1
            assert issubclass(w[0].category, UserWarning)
            assert "cache.enabled is ignored" in str(w[0].message)
        assert result.type == "gcs"

    def test_gcs_type_without_enabled_no_warning(self):
        """No warning when enabled is not set with type=gcs."""
        import warnings
        schema = PythonPackagesCacheSchema()
        data = {
            "type": "gcs",
            "gcs": {
                "bucket": "my-bucket",
                "secretRef": {"name": "gcs-key"},
            },
        }
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            schema.load(data)
            gcs_warnings = [x for x in w if "cache.enabled" in str(x.message)]
            assert len(gcs_warnings) == 0


class TestGenerateGcsInstallScript:
    """Tests for generate_gcs_install_script()."""

    def test_basic_script_structure(self):
        from kaspr.utils.python_packages import generate_gcs_install_script

        spec = PythonPackagesSpec(packages=["requests"])
        script = generate_gcs_install_script(spec)
        assert "GCS Cache Mode" in script
        assert "requests" in script
        assert "python3 -c" in script

    def test_contains_gcs_download(self):
        from kaspr.utils.python_packages import generate_gcs_install_script

        spec = PythonPackagesSpec(packages=["numpy"])
        script = generate_gcs_install_script(spec)
        assert "Cache hit" in script
        assert "Cache miss" in script
        assert "GCS_BUCKET" in script
        assert "GCS_OBJECT_KEY" in script

    def test_contains_gcs_upload(self):
        from kaspr.utils.python_packages import generate_gcs_install_script

        spec = PythonPackagesSpec(packages=["pandas"])
        script = generate_gcs_install_script(spec)
        assert "upload" in script.lower() or "Upload" in script

    def test_contains_pip_fallback(self):
        from kaspr.utils.python_packages import generate_gcs_install_script

        spec = PythonPackagesSpec(packages=["flask"])
        script = generate_gcs_install_script(spec)
        assert "pip install" in script
        assert "build_pip_command" in script

    def test_archive_size_check(self):
        from kaspr.utils.python_packages import generate_gcs_install_script

        max_bytes = 500 * 1024 * 1024  # 500Mi
        spec = PythonPackagesSpec(packages=["requests"])
        script = generate_gcs_install_script(spec, max_archive_size_bytes=max_bytes)
        assert str(max_bytes) in script

    def test_sa_key_path_in_script(self):
        from kaspr.utils.python_packages import generate_gcs_install_script

        spec = PythonPackagesSpec(packages=["requests"])
        script = generate_gcs_install_script(spec, sa_key_path="/custom/sa.json")
        assert "/custom/sa.json" in script

    def test_no_flock(self):
        """GCS mode should NOT use flock (emptyDir per pod)."""
        from kaspr.utils.python_packages import generate_gcs_install_script

        spec = PythonPackagesSpec(packages=["requests"])
        script = generate_gcs_install_script(spec)
        assert "flock" not in script

    def test_retry_logic(self):
        from kaspr.utils.python_packages import generate_gcs_install_script

        spec = PythonPackagesSpec(packages=["requests"])
        script = generate_gcs_install_script(spec, retries=5)
        assert "max_attempts=5" in script

    def test_on_failure_block(self):
        from kaspr.utils.python_packages import generate_gcs_install_script

        spec = PythonPackagesSpec(packages=["requests"])
        script = generate_gcs_install_script(spec)
        assert "blocking pod startup" in script

    def test_on_failure_continue(self):
        from kaspr.utils.python_packages import generate_gcs_install_script

        policy = PythonPackagesInstallPolicy(on_failure="continue")
        spec = PythonPackagesSpec(packages=["requests"], install_policy=policy)
        script = generate_gcs_install_script(spec)
        assert "allowing pod to start in degraded mode" in script

    def test_invalid_package_raises(self):
        from kaspr.utils.python_packages import generate_gcs_install_script

        spec = PythonPackagesSpec(packages=["requests; echo bad"])
        with pytest.raises(ValueError, match="Invalid package names"):
            generate_gcs_install_script(spec)

    def test_error_detection_block(self):
        from kaspr.utils.python_packages import generate_gcs_install_script

        spec = PythonPackagesSpec(packages=["requests"])
        script = generate_gcs_install_script(spec)
        assert "ERROR_TYPE:" in script
        assert "/tmp/pip-error.log" in script

    def test_extracts_archive_on_hit(self):
        from kaspr.utils.python_packages import generate_gcs_install_script

        spec = PythonPackagesSpec(packages=["requests"])
        script = generate_gcs_install_script(spec)
        assert "tar xzf" in script
        assert "tar czf" in script

