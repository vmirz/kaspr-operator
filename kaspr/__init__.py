try:
    import os
    from dotenv import load_dotenv, find_dotenv

    env_file = os.environ.get("ENV_FILE", ".env")
    path = find_dotenv(filename=env_file, raise_error_if_not_found=True)
    print(f"Loading environment variables from {path}")
    load_dotenv(dotenv_path=path)

except Exception:
    # No file to set environment variables
    pass

# Now safe to import handlers (which import kopf)  # noqa: E402
from kaspr.handlers import (  # noqa: E402
    kaspragent,
    kasprwebview,
    kasprtable,
    probes, 
    kasprapp,
    kasprtask,
)

__all__ = [
    "probes",
    "kasprapp",
    "kaspragent",
    "kasprwebview",
    "kasprtable",
    "kasprtask",
]

__version__ = "0.18.55"
    