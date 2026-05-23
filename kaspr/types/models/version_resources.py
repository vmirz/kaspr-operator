from pathlib import Path
from typing import List, NamedTuple, Optional, Tuple

import yaml


class VersionInfo(NamedTuple):
    major: int
    minor: int
    micro: int
    releaselevel: str
    serial: str


class KasprVersion(NamedTuple):
    operator_version: str
    version: str
    image: str
    supported: bool
    default: bool

    def __repr__(self) -> str:
        return f"{self.version}"


class KasprVersionResources:
    """Version mappings loaded from a static YAML config file."""

    _CONFIG_PATH = (
        Path(__file__).resolve().parent.parent / "config" / "kaspr_versions.yaml"
    )
    _VERSIONS: Tuple[KasprVersion, ...] = tuple()
    _LOADED = False

    @classmethod
    def _load_versions(cls) -> Tuple[KasprVersion, ...]:
        if cls._LOADED:
            return cls._VERSIONS

        if not cls._CONFIG_PATH.exists():
            raise RuntimeError(
                f"Kaspr versions config file was not found: {cls._CONFIG_PATH}"
            )

        with cls._CONFIG_PATH.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}

        if not isinstance(data, dict):
            raise RuntimeError("Kaspr versions config must be a YAML object.")

        versions_data = data.get("versions")
        if not isinstance(versions_data, list):
            raise RuntimeError(
                "Kaspr versions config must contain a 'versions' list."
            )

        versions: List[KasprVersion] = []
        for idx, item in enumerate(versions_data):
            if not isinstance(item, dict):
                raise RuntimeError(
                    f"Invalid version entry at index {idx}: expected object."
                )

            missing = {
                key
                for key in (
                    "operator_version",
                    "version",
                    "image",
                    "supported",
                    "default",
                )
                if key not in item
            }
            if missing:
                missing_str = ", ".join(sorted(missing))
                raise RuntimeError(
                    f"Invalid version entry at index {idx}: missing {missing_str}."
                )

            version = KasprVersion(
                operator_version=str(item["operator_version"]),
                version=str(item["version"]),
                image=str(item["image"]),
                supported=bool(item["supported"]),
                default=bool(item["default"]),
            )
            versions.append(version)

        defaults = [version for version in versions if version.default]
        if not defaults:
            raise RuntimeError("A default kaspr version is not configured.")
        if len(defaults) > 1:
            raise RuntimeError("Only one default kaspr version is allowed.")

        cls._VERSIONS = tuple(versions)
        cls._LOADED = True
        return cls._VERSIONS

    @classmethod
    def default_version(cls) -> KasprVersion:
        """Returns the default kaspr image version for the current operator version."""
        versions = cls._load_versions()
        default = [version for version in versions if version.default]
        return default[0]

    @classmethod
    def is_supported_version(cls, version: str) -> bool:
        versions = cls._load_versions()
        kv: List[KasprVersion] = [
            v for v in versions if v.version == version and v.supported
        ]
        if kv:
            return True
        return False

    @classmethod
    def from_version(cls, version: str) -> Optional[KasprVersion]:
        """Returns version information from a kaspr version string"""
        versions = cls._load_versions()
        kv: List[KasprVersion] = [v for v in versions if v.version == version]
        if kv:
            return kv[0]
        return None
