from kubernetes.client import V1Probe

class Probe(V1Probe):

    failure_threshold: int
    initial_delay_seconds: int
    period_seconds: int
    success_threshold: int
    timeout_seconds: int
