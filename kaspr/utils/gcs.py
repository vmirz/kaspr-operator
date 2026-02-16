"""GCS utility functions for Python packages cache."""

import re


# K8s-style size suffixes to bytes multipliers
_SIZE_SUFFIXES = {
    "": 1,
    "k": 1000,
    "m": 1000**2,
    "g": 1000**3,
    "t": 1000**4,
    "Ki": 1024,
    "Mi": 1024**2,
    "Gi": 1024**3,
    "Ti": 1024**4,
}

_SIZE_PATTERN = re.compile(r'^(\d+(?:\.\d+)?)\s*([A-Za-z]*)$')


def build_gcs_object_key(prefix: str, app_name: str, packages_hash: str) -> str:
    """Build the GCS object key for a packages archive.
    
    Args:
        prefix: Key prefix (e.g., "kaspr-packages/")
        app_name: Application name
        packages_hash: Hash of the packages spec
        
    Returns:
        Object key string, e.g. "kaspr-packages/my-app/a1b2c3d4e5f6g7h8.tar.gz"
    """
    # Ensure prefix ends with /
    if prefix and not prefix.endswith("/"):
        prefix = prefix + "/"
    return f"{prefix}{app_name}/{packages_hash}.tar.gz"


def parse_size_to_bytes(size_str: str) -> int:
    """Parse a K8s-style size string to bytes.
    
    Supports suffixes: k, M, G, T (SI) and Ki, Mi, Gi, Ti (binary).
    
    Args:
        size_str: Size string (e.g., "1Gi", "500Mi", "256")
        
    Returns:
        Size in bytes
        
    Raises:
        ValueError: If the size string is invalid
    """
    if not size_str:
        raise ValueError("Size string cannot be empty")
    
    match = _SIZE_PATTERN.match(size_str.strip())
    if not match:
        raise ValueError(f"Invalid size string: {size_str}")
    
    value = float(match.group(1))
    suffix = match.group(2)
    
    if suffix not in _SIZE_SUFFIXES:
        raise ValueError(f"Unknown size suffix: {suffix}")
    
    return int(value * _SIZE_SUFFIXES[suffix])


def generate_gcs_auth_python_script(sa_key_path: str = "/var/run/secrets/gcs/sa.json") -> str:
    """Generate inline Python code for GCS authentication.
    
    The generated code:
    1. Reads SA key from mounted file
    2. Creates JWT (header + payload)
    3. Signs JWT using openssl CLI (subprocess)
    4. Exchanges JWT for access token via oauth2.googleapis.com
    5. Returns the access token string
    
    Args:
        sa_key_path: Path to mounted SA key JSON file
        
    Returns:
        Python code as string that defines a get_access_token() function
    """
    return f'''
import json, base64, time, subprocess, os
import urllib.request, urllib.parse, urllib.error

def _b64url(data):
    """Base64url encode without padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=")

def get_access_token():
    """Authenticate with GCS using mounted service account key."""
    with open("{sa_key_path}") as f:
        sa = json.load(f)

    # Build JWT header and payload
    header = _b64url(json.dumps({{"alg": "RS256", "typ": "JWT"}}).encode())
    now = int(time.time())
    payload = _b64url(json.dumps({{
        "iss": sa["client_email"],
        "scope": "https://www.googleapis.com/auth/devstorage.read_write",
        "aud": "https://oauth2.googleapis.com/token",
        "iat": now,
        "exp": now + 3600,
    }}).encode())

    signing_input = header + b"." + payload

    # Write private key to temp file for openssl
    pk_path = "/tmp/.gcs_pk.pem"
    with open(pk_path, "w") as f:
        f.write(sa["private_key"])
    try:
        sig = subprocess.check_output(
            ["openssl", "dgst", "-sha256", "-sign", pk_path, "-binary"],
            input=signing_input,
            stderr=subprocess.DEVNULL,
        )
    finally:
        os.remove(pk_path)

    jwt_token = (header + b"." + payload + b"." + _b64url(sig)).decode()

    # Exchange JWT for access token
    data = urllib.parse.urlencode({{
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": jwt_token,
    }}).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data)
    resp = json.loads(urllib.request.urlopen(req).read())
    return resp["access_token"]
'''


def generate_gcs_download_python_script(sa_key_path: str = "/var/run/secrets/gcs/sa.json") -> str:
    """Generate inline Python code for downloading an archive from GCS.
    
    The script reads GCS_BUCKET and GCS_OBJECT_KEY from environment variables.
    Returns exit code 0 on success (cache hit), 1 on 404 (cache miss).
    
    Args:
        sa_key_path: Path to mounted SA key JSON file
        
    Returns:
        Complete Python script as string
    """
    auth_script = generate_gcs_auth_python_script(sa_key_path)
    return f'''{auth_script}

import sys

bucket = os.environ["GCS_BUCKET"]
object_key = os.environ["GCS_OBJECT_KEY"]
_safe = ""

try:
    token = get_access_token()
except Exception as e:
    print(f"GCS auth failed: {{e}}")
    sys.exit(1)

url = f"https://storage.googleapis.com/storage/v1/b/{{urllib.parse.quote(bucket, safe=_safe)}}/o/{{urllib.parse.quote(object_key, safe=_safe)}}?alt=media"
req = urllib.request.Request(url, headers={{"Authorization": f"Bearer {{token}}"}})
try:
    with urllib.request.urlopen(req) as r, open("/tmp/packages.tar.gz", "wb") as f:
        while True:
            chunk = r.read(65536)
            if not chunk:
                break
            f.write(chunk)
    print("Cache hit - downloaded archive from GCS")
    sys.exit(0)
except urllib.error.HTTPError as e:
    if e.code == 404:
        print("Cache miss - archive not found in GCS")
        sys.exit(1)
    print(f"GCS download failed (HTTP {{e.code}}): {{e.reason}}")
    sys.exit(1)
except Exception as e:
    print(f"GCS download failed: {{e}}")
    sys.exit(1)
'''


def generate_gcs_upload_python_script(
    sa_key_path: str = "/var/run/secrets/gcs/sa.json",
    archive_path: str = "/tmp/packages.tar.gz",
) -> str:
    """Generate inline Python code for uploading an archive to GCS.
    
    The script reads GCS_BUCKET and GCS_OBJECT_KEY from environment variables.
    Non-fatal: logs errors but always exits 0.
    
    Args:
        sa_key_path: Path to mounted SA key JSON file
        archive_path: Path to the archive file to upload
        
    Returns:
        Complete Python script as string
    """
    auth_script = generate_gcs_auth_python_script(sa_key_path)
    return f'''{auth_script}

bucket = os.environ["GCS_BUCKET"]
object_key = os.environ["GCS_OBJECT_KEY"]
_safe = ""

try:
    token = get_access_token()
    
    with open("{archive_path}", "rb") as f:
        file_data = f.read()
    
    upload_url = (
        f"https://storage.googleapis.com/upload/storage/v1/b/"
        f"{{urllib.parse.quote(bucket, safe=_safe)}}/o"
        f"?uploadType=media&name={{urllib.parse.quote(object_key, safe=_safe)}}"
    )
    req = urllib.request.Request(
        upload_url,
        data=file_data,
        method="POST",
        headers={{
            "Authorization": f"Bearer {{token}}",
            "Content-Type": "application/gzip",
        }},
    )
    urllib.request.urlopen(req)
    print("Uploaded packages archive to GCS cache")
except Exception as e:
    print(f"GCS upload failed (non-fatal): {{e}}")
'''
