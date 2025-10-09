import re
import os
from typing import Any

_TRUE, _FALSE = {"True", "true"}, {"False", "false"}


def _getenv(name: str, *default: Any) -> Any:
    try:
        v = os.environ[name]
        if v in _TRUE:
            return True
        elif v in _FALSE:
            return False
        else:
            return v
    except KeyError:
        pass
    if default:
        return default[0]
    raise KeyError(name)


def _subenv(input: str):
    """
    Substitutes dynamic variables found in input with environment variable(s).

    For example, my-app-{APP_NAME} converts to my-app-0 if ORDINAL_NUM
    is a defined variable.
    """
    environ = os.environ
    found = re.findall(r"{([^{}]*?)}", input)
    for v in found:
        if v in environ:
            input = input.replace(f"{{{v}}}", str(environ[v]))
    return input


# ------------------------------------------------
# ---- Defaults and environment variables ----
# ------------------------------------------------

#: Maximum starting number of worker pods to create when starting from 0 replicas
INITIAL_MAX_REPLICAS = int(_getenv("INITIAL_MAX_REPLICAS", 1))

#: Maximum number of pods to scale up at each scale up step
HPA_SCALE_UP_POLICY_PODS_PER_STEP = int(_getenv("HPA_SCALE_UP_POLICY_PODS_PER_STEP", 4))

#: Seconds to wait between each scale up step when scaling from INITIAL_MAX_REPLICAS to desired replicas
HPA_SCALE_UP_POLICY_PERIOD_SECONDS = int(
    _getenv("HPA_SCALE_UP_POLICY_PERIOD_SECONDS", 60)
)

#: Seconds to wait for statefulset deletion to complete prior to resizing disk
STATEFULSET_DELETION_TIMEOUT_SECONDS = int(
    _getenv("STATEFULSET_DELETION_TIMEOUT_SECONDS", 5)
)

#: Seconds to wait for statefulset deletion to complete prior to resizing disk
CLIENT_STATUS_CHECK_ENABLED = bool(
    _getenv("CLIENT_STATUS_CHECK_ENABLED", True)
)

class Settings:
    """Operator settings"""

    initial_max_replicas: int = INITIAL_MAX_REPLICAS
    hpa_scale_up_policy_pods_per_step: int = HPA_SCALE_UP_POLICY_PODS_PER_STEP
    hpa_scale_up_policy_period_seconds: int = HPA_SCALE_UP_POLICY_PERIOD_SECONDS
    statefulset_deletion_timeout_seconds: int = STATEFULSET_DELETION_TIMEOUT_SECONDS
    client_status_check_enabled: bool = CLIENT_STATUS_CHECK_ENABLED

    def __init__(
        self,
        *args,
        initial_max_replicas: int = None,
        hpa_scale_up_policy_pods_per_step: int = None,
        hpa_scale_up_policy_period_seconds: int = None,
        statefulset_deletion_timeout_seconds: int = None,
        client_status_check_enabled: bool = None,
        **kwargs,
    ):
        if initial_max_replicas is not None:
            self.initial_max_replicas = initial_max_replicas

        if hpa_scale_up_policy_pods_per_step is not None:
            self.hpa_scale_up_policy_pods_per_step = hpa_scale_up_policy_pods_per_step

        if hpa_scale_up_policy_period_seconds is not None:
            self.hpa_scale_up_policy_period_seconds = hpa_scale_up_policy_period_seconds

        if statefulset_deletion_timeout_seconds is not None:
            self.statefulset_deletion_timeout_seconds = (
                statefulset_deletion_timeout_seconds
            )
        if client_status_check_enabled is not None:
            self.client_status_check_enabled = client_status_check_enabled
