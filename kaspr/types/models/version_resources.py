from typing import NamedTuple, List

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
    default: True

    def __repr__(self) -> str:
        return f"{self.version}"


class KasprVersionResources:
    #: Mapping of operator version to kaspr application version
    # TODO: This should be moved to a configuration file
    _VERSIONS = (        
        KasprVersion(
            operator_version="0.5.11",
            version="0.5.11",
            image="kasprio/kaspr:0.5.11-alpha",
            supported=True,
            default=True,
        ),        
        KasprVersion(
            operator_version="0.5.8",
            version="0.5.10",
            image="kasprio/kaspr:0.5.10-alpha",
            supported=True,
            default=False,
        ),
        KasprVersion(
            operator_version="0.5.5",
            version="0.5.9",
            image="kasprio/kaspr:0.5.9-alpha",
            supported=True,
            default=False,
        ),        
        KasprVersion(
            operator_version="0.4.1",
            version="0.5.8",
            image="kasprio/kaspr:0.5.8-alpha",
            supported=True,
            default=False,
        ),
        KasprVersion(
            operator_version="0.4.0",
            version="0.5.6",
            image="kasprio/kaspr:0.5.6-alpha",
            supported=True,
            default=False,
        ),           
        KasprVersion(
            operator_version="0.3.9",
            version="0.5.4",
            image="kasprio/kaspr:0.5.4-alpha",
            supported=True,
            default=False,
        ),           
        KasprVersion(
            operator_version="0.3.7",
            version="0.5.2",
            image="kasprio/kaspr:0.5.2-alpha",
            supported=True,
            default=False,
        ),           
        KasprVersion(
            operator_version="0.3.2",
            version="0.5.1",
            image="kasprio/kaspr:0.5.1-alpha",
            supported=True,
            default=False,
        ),          
        KasprVersion(
            operator_version="0.3.1",
            version="0.5.1",
            image="kasprio/kaspr:0.5.1-alpha",
            supported=True,
            default=False,
        ),        
        KasprVersion(
            operator_version="0.3.0",
            version="0.4.4",
            image="kasprio/kaspr:0.4.4-alpha",
            supported=True,
            default=False,
        ),
        KasprVersion(
            operator_version="0.2.0",
            version="0.3.0-dev1",
            image="kasprio/kaspr:0.3.0-dev1",
            supported=True,
            default=False,
        ),  
        KasprVersion(
            operator_version="0.1.10",
            version="0.2.2-alpha",
            image="kasprio/kaspr:0.2.2-alpha",
            supported=False,
            default=False,
        ),  
        KasprVersion(
            operator_version="0.1.10",
            version="0.1.2",
            image="kasprio/kaspr:0.1.2",
            supported=False,
            default=False,
        ),        
        KasprVersion(
            operator_version="0.1.10",
            version="0.1.1",
            image="kasprio/kaspr:0.1.1",
            supported=False,
            default=False,
        ),
        KasprVersion(
            operator_version="0.1.0",
            version="0.1.0",
            image="kasprio/kaspr:0.1.0",
            supported=True,
            default=False,
        ),
    )

    @classmethod
    def default_version(self) -> KasprVersion:
        """Returns the default kaspr image version for the current operator version."""
        default = [version for version in self._VERSIONS if version.default]
        if not default:
            raise RuntimeError("A default kaspr version is not configured.")
        if len(default) > 1:
            raise RecursionError("Only one default kaspr version is allowed.")
        return default[0]

    @classmethod
    def is_supported_version(cls, version: str):
        kv: List[KasprVersion] = [
            v for v in cls._VERSIONS if v.version == version and v.supported
        ]
        if kv:
            return True
        return False
    
    @classmethod
    def from_version(self, version: str) -> KasprVersion:
        """Returns version information from a kaspr version string"""
        kv: List[KasprVersion] = [
            v for v in self._VERSIONS if v.version == version
        ]
        if kv:
            return kv[0]
