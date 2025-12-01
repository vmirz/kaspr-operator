"""Unit tests for KasprApp resource Python packages integration."""

import pytest
from unittest.mock import Mock, patch
from kaspr.resources.kasprapp import KasprApp
from kaspr.types.models.python_packages import (
    PythonPackagesSpec,
    PythonPackagesCache,
    PythonPackagesInstallPolicy,
    PythonPackagesResources,
)
from kaspr.types.models.kasprapp_spec import KasprAppSpec
from kaspr.types.models.storage import KasprAppStorage
from kaspr.types.models.config import KasprAppConfig


@pytest.fixture
def base_spec():
    """Create a basic KasprAppSpec for testing."""
    spec = Mock(spec=KasprAppSpec)
    spec.replicas = 1
    spec.image = "test-image:latest"
    spec.version = None
    spec.bootstrap_servers = "kafka:9092"
    spec.tls = None
    spec.authentication = Mock()
    spec.authentication.sasl_enabled = False
    spec.storage = Mock(spec=KasprAppStorage)
    spec.storage.size = "1Gi"
    spec.storage.storage_class = None
    spec.storage.delete_claim = True
    spec.config = Mock(spec=KasprAppConfig)
    spec.config.kafka_broker = "kafka:9092"
    spec.config.topic_name = "test-topic"
    spec.resources = None
    spec.liveness_probe = None
    spec.readiness_probe = None
    spec.template = Mock()
    spec.template.service_account = None
    spec.template.pod = Mock()
    spec.template.pod.metadata = Mock()
    spec.template.pod.metadata.annotations = None
    spec.template.service = None
    spec.template.kaspr_container = None
    spec.python_packages = None
    return spec


@pytest.fixture
def kasprapp_with_packages(base_spec):
    """Create KasprApp instance with Python packages configured."""
    packages_spec = PythonPackagesSpec(
        packages=["pandas==2.0.0", "numpy>=1.24.0"],
        cache=PythonPackagesCache(
            enabled=True,
            size="256Mi",
            access_mode="ReadWriteMany",
            storage_class=None,
            delete_claim=True,
        ),
        install_policy=PythonPackagesInstallPolicy(
            retries=3,
            timeout=600,
        ),
        resources=None,
    )
    base_spec.python_packages = packages_spec
    
    app = KasprApp.from_spec(
        name="test-app",
        kind="KasprApp",
        namespace="test-namespace",
        spec=base_spec,
    )
    return app


@pytest.fixture
def kasprapp_without_packages(base_spec):
    """Create KasprApp instance without Python packages."""
    base_spec.python_packages = None
    
    app = KasprApp.from_spec(
        name="test-app",
        kind="KasprApp",
        namespace="test-namespace",
        spec=base_spec,
    )
    return app


@pytest.fixture
def kasprapp_cache_disabled(base_spec):
    """Create KasprApp instance with cache disabled."""
    packages_spec = PythonPackagesSpec(
        packages=["pandas"],
        cache=PythonPackagesCache(enabled=False),
        install_policy=None,
        resources=None,
    )
    base_spec.python_packages = packages_spec
    
    app = KasprApp.from_spec(
        name="test-app",
        kind="KasprApp",
        namespace="test-namespace",
        spec=base_spec,
    )
    return app


class TestPreparePackagesPVC:
    """Tests for prepare_packages_pvc method."""
    
    def test_prepare_packages_pvc_with_defaults(self, kasprapp_with_packages):
        """Test PVC generation with default values."""
        pvc = kasprapp_with_packages.prepare_python_packages_pvc()
        
        assert pvc is not None
        assert pvc.metadata.name.endswith("-packages")
        assert pvc.spec.access_modes == ["ReadWriteMany"]
        assert pvc.spec.resources.requests["storage"] == "256Mi"
        assert "kaspr.io/resource-hash" in pvc.metadata.annotations
    
    def test_prepare_packages_pvc_with_custom_size(self, base_spec):
        """Test PVC generation with custom size."""
        packages_spec = PythonPackagesSpec(
            packages=["pandas"],
            cache=PythonPackagesCache(
                enabled=True,
                size="1Gi",
                access_mode="ReadWriteMany",
            ),
        )
        base_spec.python_packages = packages_spec
        
        app = KasprApp.from_spec(
            name="test-app",
            kind="KasprApp",
            namespace="test-namespace",
            spec=base_spec,
        )
        
        pvc = app.prepare_python_packages_pvc()
        
        assert pvc is not None
        assert pvc.metadata.name.endswith("-python-packages")
        assert pvc.spec.access_modes == ["ReadWriteMany"]
        assert pvc.spec.resources.requests["storage"] == "1Gi"
    
    def test_prepare_packages_pvc_with_storage_class(self, base_spec):
        """Test PVC generation with custom storage class."""
        packages_spec = PythonPackagesSpec(
            packages=["pandas"],
            cache=PythonPackagesCache(
                enabled=True,
                storage_class="fast-ssd",
            ),
        )
        base_spec.python_packages = packages_spec
        
        app = KasprApp.from_spec(
            name="test-app",
            kind="KasprApp",
            namespace="test-namespace",
            spec=base_spec,
        )
        
        pvc = app.prepare_python_packages_pvc()
        
        assert pvc is not None
        assert pvc.spec.storage_class_name == "fast-ssd"
    
    def test_prepare_packages_pvc_with_custom_access_mode(self, base_spec):
        """Test PVC generation with custom access mode."""
        packages_spec = PythonPackagesSpec(
            packages=["pandas"],
            cache=PythonPackagesCache(
                enabled=True,
                access_mode="ReadWriteOnce",
            ),
        )
        base_spec.python_packages = packages_spec
        
        app = KasprApp.from_spec(
            name="test-app",
            kind="KasprApp",
            namespace="test-namespace",
            spec=base_spec,
        )
        
        pvc = app.prepare_python_packages_pvc()
        
        assert pvc is not None
        assert pvc.spec.access_modes == ["ReadWriteOnce"]
    
    def test_prepare_packages_pvc_cache_disabled(self, kasprapp_cache_disabled):
        """Test that no PVC is created when cache is disabled."""
        pvc = kasprapp_cache_disabled.prepare_python_packages_pvc()
        assert pvc is None
    
    def test_prepare_packages_pvc_no_packages(self, kasprapp_without_packages):
        """Test that no PVC is created when python_packages is None."""
        pvc = kasprapp_without_packages.prepare_python_packages_pvc()
        assert pvc is None
    
    def test_prepare_packages_pvc_no_cache_field(self, base_spec):
        """Test PVC creation when cache field is not specified (uses defaults)."""
        packages_spec = PythonPackagesSpec(packages=["pandas"])
        # Don't set cache field, should use defaults
        base_spec.python_packages = packages_spec
        
        app = KasprApp.from_spec(
            name="test-app",
            kind="KasprApp",
            namespace="test-namespace",
            spec=base_spec,
        )
        
        pvc = app.prepare_python_packages_pvc()
        
        assert pvc is not None
        assert pvc.spec.access_modes == ["ReadWriteMany"]  # Default
        assert pvc.spec.resources.requests["storage"] == "256Mi"  # Default


class TestPreparePackagesInitContainer:
    """Tests for prepare_packages_init_container method."""
    
    def test_prepare_packages_init_container_basic(self, kasprapp_with_packages):
        """Test init container generation with basic config."""
        container = kasprapp_with_packages.prepare_packages_init_container()
        
        assert container is not None
        assert container.name == "install-packages"
        assert container.image == "test-image:latest"
        assert len(container.command) == 2
        assert container.command[0] == "/bin/bash"
        assert container.command[1] == "-c"
        assert len(container.args) == 1
        assert "pandas==2.0.0" in container.args[0]
        assert "numpy>=1.24.0" in container.args[0]
        
        # Check volume mount
        assert len(container.volume_mounts) == 1
        assert container.volume_mounts[0].name.endswith("-packages")
        assert container.volume_mounts[0].mount_path == "/opt/kaspr/packages"
        assert container.volume_mounts[0].read_only is not True  # Should be read-write for init container
    
    def test_prepare_packages_init_container_with_resources(self, base_spec):
        """Test init container with custom resource limits."""
        packages_spec = PythonPackagesSpec(
            packages=["pandas"],
            cache=PythonPackagesCache(enabled=True),
            resources=PythonPackagesResources(
                limits={"cpu": "1", "memory": "1Gi"},
                requests={"cpu": "500m", "memory": "512Mi"},
            ),
        )
        base_spec.python_packages = packages_spec
        
        app = KasprApp.from_spec(
            name="test-app",
            kind="KasprApp",
            namespace="test-namespace",
            spec=base_spec,
        )
        
        container = app.prepare_packages_init_container()
        assert container.resources is not None
        assert container.resources.limits["cpu"] == "1"
        assert container.resources.limits["memory"] == "1Gi"
        assert container.resources.requests["cpu"] == "500m"
        assert container.resources.requests["memory"] == "512Mi"
    
    def test_prepare_packages_init_container_custom_policy(self, base_spec):
        """Test init container with custom install policy."""
        packages_spec = PythonPackagesSpec(
            packages=["pandas"],
            cache=PythonPackagesCache(enabled=True),
            install_policy=PythonPackagesInstallPolicy(
                retries=10,
                timeout=1800,
            ),
        )
        base_spec.python_packages = packages_spec
        
        app = KasprApp.from_spec(
            name="test-app",
            kind="KasprApp",
            namespace="test-namespace",
            spec=base_spec,
        )
        
        container = app.prepare_packages_init_container()
        # Check that script contains custom values
        script = container.args[0]
        assert "max_attempts=10" in script
        assert "timeout 1800s" in script
    
    def test_prepare_packages_init_container_cache_disabled(self, kasprapp_cache_disabled):
        """Test that no init container is created when cache is disabled."""
        container = kasprapp_cache_disabled.prepare_packages_init_container()
        assert container is None
    
    def test_prepare_packages_init_container_no_packages(self, kasprapp_without_packages):
        """Test that no init container is created when python_packages is None."""
        container = kasprapp_without_packages.prepare_packages_init_container()
        assert container is None
    
    def test_prepare_packages_init_container_script_has_flock(self, kasprapp_with_packages):
        """Test that init container script uses flock for locking."""
        container = kasprapp_with_packages.prepare_packages_init_container()
        script = container.args[0]
        assert "flock" in script
        assert "/opt/kaspr/packages/.install.lock" in script


class TestPreparePackagesVolumeMounts:
    """Tests for prepare_packages_volume_mounts method."""
    
    def test_prepare_packages_volume_mounts(self, kasprapp_with_packages):
        """Test volume mount generation for main container."""
        mounts = kasprapp_with_packages.prepare_packages_volume_mounts()
        
        assert len(mounts) == 1
        assert mounts[0].name.endswith("-packages")
        assert mounts[0].mount_path == "/opt/kaspr/packages"
        assert mounts[0].read_only is True
    
    def test_prepare_packages_volume_mounts_cache_disabled(self, kasprapp_cache_disabled):
        """Test that no volume mounts when cache disabled."""
        mounts = kasprapp_cache_disabled.prepare_packages_volume_mounts()
        assert len(mounts) == 0
    
    def test_prepare_packages_volume_mounts_no_packages(self, kasprapp_without_packages):
        """Test that no volume mounts when packages not configured."""
        mounts = kasprapp_without_packages.prepare_packages_volume_mounts()
        assert len(mounts) == 0


class TestPrepareEnvVars:
    """Tests for prepare_env_vars method with PYTHONPATH."""
    
    def test_prepare_env_vars_with_pythonpath(self, kasprapp_with_packages):
        """Test that PYTHONPATH is added when packages enabled."""
        # Mock the config to avoid complex dependencies
        kasprapp_with_packages.config = Mock()
        kasprapp_with_packages.config.env_for = lambda x: f"KASPR_{x.upper()}"
        kasprapp_with_packages.authentication = Mock()
        kasprapp_with_packages.authentication.sasl_enabled = False
        kasprapp_with_packages._settings_config_map = Mock()
        kasprapp_with_packages._settings_config_map.data = {}
        kasprapp_with_packages._env_dict = {}
        kasprapp_with_packages.annotations = {}
        kasprapp_with_packages.template_container = Mock()
        kasprapp_with_packages.template_container.env = None
        
        env_vars = kasprapp_with_packages.prepare_env_vars()
        
        pythonpath_vars = [v for v in env_vars if v.name == "PYTHONPATH"]
        assert len(pythonpath_vars) == 1
        assert pythonpath_vars[0].value == "/opt/kaspr/packages:${PYTHONPATH}"
    
    def test_prepare_env_vars_no_pythonpath_cache_disabled(self, kasprapp_cache_disabled):
        """Test that PYTHONPATH is not added when cache disabled."""
        # Mock the config to avoid complex dependencies
        kasprapp_cache_disabled.config = Mock()
        kasprapp_cache_disabled.config.env_for = lambda x: f"KASPR_{x.upper()}"
        kasprapp_cache_disabled.authentication = Mock()
        kasprapp_cache_disabled.authentication.sasl_enabled = False
        kasprapp_cache_disabled._settings_config_map = Mock()
        kasprapp_cache_disabled._settings_config_map.data = {}
        kasprapp_cache_disabled._env_dict = {}
        kasprapp_cache_disabled.annotations = {}
        kasprapp_cache_disabled.template_container = Mock()
        kasprapp_cache_disabled.template_container.env = None
        
        env_vars = kasprapp_cache_disabled.prepare_env_vars()
        
        pythonpath_vars = [v for v in env_vars if v.name == "PYTHONPATH"]
        assert len(pythonpath_vars) == 0
    
    def test_prepare_env_vars_no_pythonpath_no_packages(self, kasprapp_without_packages):
        """Test that PYTHONPATH is not added when packages not configured."""
        # Mock the config to avoid complex dependencies
        kasprapp_without_packages.config = Mock()
        kasprapp_without_packages.config.env_for = lambda x: f"KASPR_{x.upper()}"
        kasprapp_without_packages.authentication = Mock()
        kasprapp_without_packages.authentication.sasl_enabled = False
        kasprapp_without_packages._settings_config_map = Mock()
        kasprapp_without_packages._settings_config_map.data = {}
        kasprapp_without_packages._env_dict = {}
        kasprapp_without_packages.annotations = {}
        kasprapp_without_packages.template_container = Mock()
        kasprapp_without_packages.template_container.env = None
        
        env_vars = kasprapp_without_packages.prepare_env_vars()
        
        pythonpath_vars = [v for v in env_vars if v.name == "PYTHONPATH"]
        assert len(pythonpath_vars) == 0


class TestStatefulSetIntegration:
    """Tests for StatefulSet integration with packages."""
    
    def test_prepare_statefulset_includes_packages_pvc(self, kasprapp_with_packages):
        """Test that packages PVC is created as standalone when enabled."""
        # Simply check if packages PVC is prepared
        packages_pvc = kasprapp_with_packages.prepare_python_packages_pvc()
        assert packages_pvc is not None
        assert packages_pvc.metadata.name.endswith("-python-packages")
    
    def test_prepare_statefulset_no_packages_when_cache_disabled(self, kasprapp_cache_disabled):
        """Test that packages PVC not added when cache disabled."""
        packages_pvc = kasprapp_cache_disabled.prepare_python_packages_pvc()
        assert packages_pvc is None
    
    def test_prepare_statefulset_no_packages_when_not_configured(self, kasprapp_without_packages):
        """Test that packages PVC not added when packages not configured."""
        packages_pvc = kasprapp_without_packages.prepare_python_packages_pvc()
        assert packages_pvc is None
    
    def test_packages_pvc_has_hash_annotation(self, kasprapp_with_packages):
        """Test that packages PVC includes hash annotation."""
        pvc = kasprapp_with_packages.prepare_python_packages_pvc()
        assert pvc is not None
        assert "kaspr.io/resource-hash" in pvc.metadata.annotations


class TestPrepareVolumeMount:
    """Tests for prepare_volume_mounts integration."""
    
    @patch.object(KasprApp, 'prepare_agent_volume_mounts', return_value=[])
    @patch.object(KasprApp, 'prepare_webview_volume_mounts', return_value=[])
    @patch.object(KasprApp, 'prepare_table_volume_mounts', return_value=[])
    @patch.object(KasprApp, 'prepare_task_volume_mounts', return_value=[])
    @patch.object(KasprApp, 'prepare_container_template_volume_mounts', return_value=[])
    def test_prepare_volume_mounts_includes_packages(
        self, mock_ct, mock_task, mock_table, mock_wv, mock_agent,
        kasprapp_with_packages
    ):
        """Test that prepare_volume_mounts includes packages mount."""
        mounts = kasprapp_with_packages.prepare_volume_mounts()
        
        # Should include packages volume mount
        packages_mounts = [m for m in mounts if m.name.endswith("-packages")]
        assert len(packages_mounts) == 1
        assert packages_mounts[0].mount_path == "/opt/kaspr/packages"
        assert packages_mounts[0].read_only is True


class TestCachedProperties:
    """Tests for cached properties."""
    
    def test_packages_pvc_cached_property(self, kasprapp_with_packages):
        """Test python_packages_pvc cached property."""
        # First call should create PVC
        pvc1 = kasprapp_with_packages.python_packages_pvc
        assert pvc1 is not None
        
        # Second call should return cached PVC
        pvc2 = kasprapp_with_packages.python_packages_pvc
        assert pvc1 is pvc2
    
    def test_packages_init_container_cached_property(self, kasprapp_with_packages):
        """Test packages_init_container cached property."""
        # First call should create container
        container1 = kasprapp_with_packages.packages_init_container
        assert container1 is not None
        
        # Second call should return cached value
        container2 = kasprapp_with_packages.packages_init_container
        assert container1 is container2
    
    def test_packages_pvc_cached_property_none(self, kasprapp_without_packages):
        """Test python_packages_pvc returns None when not configured."""
        pvc = kasprapp_without_packages.python_packages_pvc
        assert pvc is None
    
    def test_packages_init_container_cached_property_none(self, kasprapp_cache_disabled):
        """Test packages_init_container returns None when cache disabled."""
        container = kasprapp_cache_disabled.packages_init_container
        assert container is None


class TestFromSpec:
    """Tests for from_spec method parsing python_packages."""
    
    def test_from_spec_with_packages(self, base_spec):
        """Test that from_spec parses python_packages from spec."""
        packages_spec = PythonPackagesSpec(
            packages=["pandas"],
            cache=PythonPackagesCache(enabled=True),
        )
        base_spec.python_packages = packages_spec
        
        app = KasprApp.from_spec(
            name="test-app",
            kind="KasprApp",
            namespace="test-namespace",
            spec=base_spec,
        )
        
        assert app.python_packages is not None
        assert app.python_packages.packages == ["pandas"]
    
    def test_from_spec_without_packages(self, base_spec):
        """Test that from_spec handles missing python_packages."""
        base_spec.python_packages = None
        
        app = KasprApp.from_spec(
            name="test-app",
            kind="KasprApp",
            namespace="test-namespace",
            spec=base_spec,
        )
        
        assert app.python_packages is None
