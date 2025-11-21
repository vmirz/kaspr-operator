"""Kaspr Operator Sensor Framework.

This module provides a monitoring and observability framework for the Kaspr operator,
inspired by Faust's sensor architecture. It enables non-invasive instrumentation of
operator lifecycle events through a hook-based pattern.

Key components:
- OperatorSensor: Base class defining lifecycle hooks for operator events
- SensorDelegate: Fan-out pattern for routing events to multiple sensor backends
- PrometheusMonitor: (future) Prometheus metrics exporter

Usage:
    from kaspr.sensors import OperatorSensor, SensorDelegate
    
    # Create custom sensor
    class CustomSensor(OperatorSensor):
        def on_reconcile_complete(self, name: str, namespace: str, state: Dict) -> None:
            duration = state.get('duration', 0)
            print(f"Reconciled {name} in {duration}s")
    
    # Use delegate for multiple backends
    delegate = SensorDelegate()
    delegate.add(CustomSensor())
    delegate.add(PrometheusMonitor())
"""

from kaspr.sensors.base import OperatorSensor
from kaspr.sensors.delegate import SensorDelegate
from kaspr.sensors.prometheus import PrometheusMonitor
from kaspr.sensors.server import init_metrics_server

__all__ = [
    'OperatorSensor',
    'SensorDelegate',
    'PrometheusMonitor',
    'init_metrics_server',
]
