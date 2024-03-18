import re
from typing import NamedTuple


class VersionInfo(NamedTuple):
    major: int
    minor: int
    micro: int
    releaselevel: str
    serial: str


class Version:
    _version: str
    
    info: VersionInfo

    def __init__(self, version: str, version_info: VersionInfo = None) -> None:
        self._version = version
        if version_info is None:
            version_info = Version.from_str(self._version)
        self.info = version_info

    @classmethod
    def from_str(self, version: str) -> VersionInfo:
        """Parse a version string."""
        _match = re.match(r"(\d+)\.(\d+).(\d+)(.+)?", version)
        if _match is None:
            raise RuntimeError("THIS IS A BROKEN RELEASE!")
        _temp = _match.groups()
        _version_info = VersionInfo(
            int(_temp[0]), int(_temp[1]), int(_temp[2]), _temp[3] or "", ""
        )
        _version = version
        return Version(_version, _version_info)


        
