"""Unit tests for GCS utility functions."""

import pytest
from kaspr.utils.gcs import (
    build_gcs_object_key,
    parse_size_to_bytes,
    generate_gcs_auth_python_script,
    generate_gcs_download_python_script,
    generate_gcs_upload_python_script,
)


class TestBuildGcsObjectKey:
    """Tests for build_gcs_object_key()."""

    def test_basic_key(self):
        key = build_gcs_object_key("kaspr-packages/", "my-app", "a1b2c3d4e5f6g7h8")
        assert key == "kaspr-packages/my-app/a1b2c3d4e5f6g7h8.tar.gz"

    def test_prefix_without_trailing_slash(self):
        key = build_gcs_object_key("kaspr-packages", "my-app", "abcdef1234567890")
        assert key == "kaspr-packages/my-app/abcdef1234567890.tar.gz"

    def test_empty_prefix(self):
        key = build_gcs_object_key("", "my-app", "hash123")
        assert key == "my-app/hash123.tar.gz"

    def test_nested_prefix(self):
        key = build_gcs_object_key("org/team/cache/", "app", "h")
        assert key == "org/team/cache/app/h.tar.gz"


class TestParseSizeToBytes:
    """Tests for parse_size_to_bytes()."""

    def test_gi_suffix(self):
        assert parse_size_to_bytes("1Gi") == 1024**3

    def test_mi_suffix(self):
        assert parse_size_to_bytes("256Mi") == 256 * 1024**2

    def test_ki_suffix(self):
        assert parse_size_to_bytes("512Ki") == 512 * 1024

    def test_ti_suffix(self):
        assert parse_size_to_bytes("1Ti") == 1024**4

    def test_si_g_suffix(self):
        assert parse_size_to_bytes("1g") == 1000**3

    def test_si_m_suffix(self):
        assert parse_size_to_bytes("500m") == 500 * 1000**2

    def test_no_suffix(self):
        assert parse_size_to_bytes("1024") == 1024

    def test_fractional(self):
        assert parse_size_to_bytes("0.5Gi") == int(0.5 * 1024**3)

    def test_empty_string_raises(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            parse_size_to_bytes("")

    def test_invalid_string_raises(self):
        with pytest.raises(ValueError):
            parse_size_to_bytes("abc")

    def test_unknown_suffix_raises(self):
        with pytest.raises(ValueError, match="Unknown size suffix"):
            parse_size_to_bytes("100XX")


class TestGenerateGcsAuthPythonScript:
    """Tests for generate_gcs_auth_python_script()."""

    def test_contains_get_access_token_function(self):
        script = generate_gcs_auth_python_script()
        assert "def get_access_token():" in script

    def test_uses_default_sa_key_path(self):
        script = generate_gcs_auth_python_script()
        assert "/var/run/secrets/gcs/sa.json" in script

    def test_custom_sa_key_path(self):
        script = generate_gcs_auth_python_script("/custom/path/key.json")
        assert "/custom/path/key.json" in script
        assert "/var/run/secrets/gcs/sa.json" not in script

    def test_uses_openssl_for_signing(self):
        script = generate_gcs_auth_python_script()
        assert "openssl" in script

    def test_uses_jwt_exchange(self):
        script = generate_gcs_auth_python_script()
        assert "oauth2.googleapis.com/token" in script

    def test_reads_sa_json_fields(self):
        script = generate_gcs_auth_python_script()
        assert 'sa["client_email"]' in script
        assert 'sa["private_key"]' in script

    def test_is_valid_python_syntax(self):
        """Verify the generated script is syntactically valid Python."""
        script = generate_gcs_auth_python_script()
        compile(script, "<test>", "exec")  # Raises SyntaxError if invalid


class TestGenerateGcsDownloadPythonScript:
    """Tests for generate_gcs_download_python_script()."""

    def test_contains_auth_code(self):
        script = generate_gcs_download_python_script()
        assert "def get_access_token():" in script

    def test_reads_env_vars(self):
        script = generate_gcs_download_python_script()
        assert 'os.environ["GCS_BUCKET"]' in script
        assert 'os.environ["GCS_OBJECT_KEY"]' in script

    def test_handles_404_cache_miss(self):
        script = generate_gcs_download_python_script()
        assert "404" in script
        assert "Cache miss" in script

    def test_handles_cache_hit(self):
        script = generate_gcs_download_python_script()
        assert "Cache hit" in script

    def test_writes_to_tmp(self):
        script = generate_gcs_download_python_script()
        assert "/tmp/packages.tar.gz" in script

    def test_uses_storage_api(self):
        script = generate_gcs_download_python_script()
        assert "storage.googleapis.com" in script

    def test_is_valid_python_syntax(self):
        script = generate_gcs_download_python_script()
        compile(script, "<test>", "exec")

    def test_custom_sa_key_path(self):
        script = generate_gcs_download_python_script("/custom/sa.json")
        assert "/custom/sa.json" in script


class TestGenerateGcsUploadPythonScript:
    """Tests for generate_gcs_upload_python_script()."""

    def test_contains_auth_code(self):
        script = generate_gcs_upload_python_script()
        assert "def get_access_token():" in script

    def test_reads_env_vars(self):
        script = generate_gcs_upload_python_script()
        assert 'os.environ["GCS_BUCKET"]' in script
        assert 'os.environ["GCS_OBJECT_KEY"]' in script

    def test_non_fatal_errors(self):
        """Upload errors should be caught and logged, not raised."""
        script = generate_gcs_upload_python_script()
        assert "non-fatal" in script

    def test_uses_upload_api(self):
        script = generate_gcs_upload_python_script()
        assert "upload/storage/v1" in script

    def test_default_archive_path(self):
        script = generate_gcs_upload_python_script()
        assert "/tmp/packages.tar.gz" in script

    def test_custom_archive_path(self):
        script = generate_gcs_upload_python_script(archive_path="/data/pkg.tar.gz")
        assert "/data/pkg.tar.gz" in script

    def test_is_valid_python_syntax(self):
        script = generate_gcs_upload_python_script()
        compile(script, "<test>", "exec")

    def test_sets_content_type(self):
        script = generate_gcs_upload_python_script()
        assert "application/gzip" in script
