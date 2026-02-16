"""Sensor delegation for fan-out pattern.

This module provides SensorDelegate, which implements the delegation pattern
for routing sensor events to multiple monitoring backends simultaneously.
Each backend receives the same events and can maintain independent state.

This follows Faust's SensorDelegate design, enabling scenarios like:
- Prometheus metrics + structured logging simultaneously
- Multiple Prometheus instances with different label sets
- Development (logging) vs production (metrics) backends
"""

from typing import Set, Dict, Optional, Any
import logging

from kaspr.sensors.base import OperatorSensor

logger = logging.getLogger(__name__)


class SensorDelegate(OperatorSensor):
    """Delegate sensor that fans out events to multiple backends.
    
    This class maintains a set of child sensors and forwards all lifecycle
    events to each one. State tracking is handled per-sensor, so each backend
    receives its own state dict from start/complete hook pairs.
    
    Example:
        # Create delegate with multiple backends
        delegate = SensorDelegate()
        delegate.add(LoggingSensor())
        delegate.add(PrometheusMonitor())
        
        # Use delegate like a normal sensor
        state = delegate.on_reconcile_start("my-app", "default", 5, "timer")
        delegate.on_reconcile_complete("my-app", "default", state, True)
        
        # Both LoggingSensor and PrometheusMonitor receive the events
    """

    def __init__(self) -> None:
        """Initialize empty sensor delegate."""
        self._sensors: Set[OperatorSensor] = set()

    def add(self, sensor: OperatorSensor) -> None:
        """Add a sensor to the delegate.
        
        Args:
            sensor: Sensor instance to add
        """
        logger.info(f"Adding sensor: {sensor.__class__.__name__}")
        self._sensors.add(sensor)

    def remove(self, sensor: OperatorSensor) -> None:
        """Remove a sensor from the delegate.
        
        Args:
            sensor: Sensor instance to remove
        """
        logger.info(f"Removing sensor: {sensor.__class__.__name__}")
        self._sensors.discard(sensor)

    def clear(self) -> None:
        """Remove all sensors from the delegate."""
        logger.info(f"Clearing {len(self._sensors)} sensors")
        self._sensors.clear()

    # =============================================================================
    # Reconciliation Lifecycle Hooks
    # =============================================================================

    def on_reconcile_start(
        self,
        app_name: str,
        component_name: str,
        namespace: str,
        generation: int,
        trigger_source: str,
    ) -> Optional[Dict[OperatorSensor, Any]]:
        """Delegate reconcile_start to all sensors.
        
        Returns:
            Dict mapping each sensor to its returned state, or None if no sensors
        """
        if not self._sensors:
            return None
        
        states = {}
        for sensor in self._sensors:
            try:
                state = sensor.on_reconcile_start(app_name, component_name, namespace, generation, trigger_source)
                if state is not None:
                    states[sensor] = state
            except Exception as e:
                logger.error(
                    f"Error in {sensor.__class__.__name__}.on_reconcile_start: {e}",
                    exc_info=True,
                )
        
        return states if states else None

    def on_reconcile_complete(
        self,
        app_name: str,
        component_name: str,
        namespace: str,
        state: Optional[Dict[OperatorSensor, Any]],
        success: bool,
        error: Optional[Exception] = None,
    ) -> None:
        """Delegate reconcile_complete to all sensors with their specific state."""
        for sensor in self._sensors:
            try:
                sensor_state = state.get(sensor) if state else None
                sensor.on_reconcile_complete(app_name, component_name, namespace, sensor_state, success, error)
            except Exception as e:
                logger.error(
                    f"Error in {sensor.__class__.__name__}.on_reconcile_complete: {e}",
                    exc_info=True,
                )

    def on_reconcile_queued(
        self,
        app_name: str,
        component_name: str,
        namespace: str,
        queue_depth: int,
    ) -> None:
        """Delegate reconcile_queued to all sensors."""
        for sensor in self._sensors:
            try:
                sensor.on_reconcile_queued(app_name, component_name, namespace, queue_depth)
            except Exception as e:
                logger.error(
                    f"Error in {sensor.__class__.__name__}.on_reconcile_queued: {e}",
                    exc_info=True,
                )

    def on_reconcile_dequeued(
        self,
        app_name: str,
        component_name: str,
        namespace: str,
        wait_time: float,
    ) -> None:
        """Delegate reconcile_dequeued to all sensors."""
        for sensor in self._sensors:
            try:
                sensor.on_reconcile_dequeued(app_name, component_name, namespace, wait_time)
            except Exception as e:
                logger.error(
                    f"Error in {sensor.__class__.__name__}.on_reconcile_dequeued: {e}",
                    exc_info=True,
                )

    # =============================================================================
    # Resource Operation Hooks
    # =============================================================================

    def on_resource_sync_start(
        self,
        app_name: str,
        component_name: str,
        resource_name: str,
        namespace: str,
        resource_type: str,
    ) -> Optional[Dict[OperatorSensor, Any]]:
        """Delegate resource_sync_start to all sensors."""
        if not self._sensors:
            return None
        
        states = {}
        for sensor in self._sensors:
            try:
                state = sensor.on_resource_sync_start(app_name, component_name, resource_name, namespace, resource_type)
                if state is not None:
                    states[sensor] = state
            except Exception as e:
                logger.error(
                    f"Error in {sensor.__class__.__name__}.on_resource_sync_start: {e}",
                    exc_info=True,
                )
        
        return states if states else None

    def on_resource_sync_complete(
        self,
        app_name: str,
        component_name: str,
        resource_name: str,
        namespace: str,
        resource_type: str,
        state: Optional[Dict[OperatorSensor, Any]],
        operation: str,
        success: bool,
        error: Optional[Exception] = None,
    ) -> None:
        """Delegate resource_sync_complete to all sensors with their specific state."""
        for sensor in self._sensors:
            try:
                sensor_state = state.get(sensor) if state else None
                sensor.on_resource_sync_complete(
                    app_name, component_name, resource_name, namespace, resource_type, sensor_state, operation, success, error
                )
            except Exception as e:
                logger.error(
                    f"Error in {sensor.__class__.__name__}.on_resource_sync_complete: {e}",
                    exc_info=True,
                )

    def on_resource_drift_detected(
        self,
        app_name: str,
        component_name: str,
        resource_name: str,
        namespace: str,
        resource_type: str,
        drift_fields: list[str],
    ) -> None:
        """Delegate resource_drift_detected to all sensors."""
        for sensor in self._sensors:
            try:
                sensor.on_resource_drift_detected(app_name, component_name, resource_name, namespace, resource_type, drift_fields)
            except Exception as e:
                logger.error(
                    f"Error in {sensor.__class__.__name__}.on_resource_drift_detected: {e}",
                    exc_info=True,
                )

    # =============================================================================
    # Member Management Hooks
    # =============================================================================

    def on_rebalance_triggered(
        self,
        name: str,
        namespace: str,
        trigger_reason: str,
    ) -> Optional[Dict[OperatorSensor, Any]]:
        """Delegate rebalance_triggered to all sensors."""
        if not self._sensors:
            return None
        
        states = {}
        for sensor in self._sensors:
            try:
                state = sensor.on_rebalance_triggered(name, namespace, trigger_reason)
                if state is not None:
                    states[sensor] = state
            except Exception as e:
                logger.error(
                    f"Error in {sensor.__class__.__name__}.on_rebalance_triggered: {e}",
                    exc_info=True,
                )
        
        return states if states else None

    def on_rebalance_complete(
        self,
        name: str,
        namespace: str,
        state: Optional[Dict[OperatorSensor, Any]],
        success: bool,
        duration: Optional[float] = None,
    ) -> None:
        """Delegate rebalance_complete to all sensors with their specific state."""
        for sensor in self._sensors:
            try:
                sensor_state = state.get(sensor) if state else None
                sensor.on_rebalance_complete(name, namespace, sensor_state, success, duration)
            except Exception as e:
                logger.error(
                    f"Error in {sensor.__class__.__name__}.on_rebalance_complete: {e}",
                    exc_info=True,
                )

    def on_member_state_change(
        self,
        name: str,
        namespace: str,
        member_id: int,
        old_state: str,
        new_state: str,
    ) -> None:
        """Delegate member_state_change to all sensors."""
        for sensor in self._sensors:
            try:
                sensor.on_member_state_change(name, namespace, member_id, old_state, new_state)
            except Exception as e:
                logger.error(
                    f"Error in {sensor.__class__.__name__}.on_member_state_change: {e}",
                    exc_info=True,
                )

    def on_hung_member_detected(
        self,
        name: str,
        namespace: str,
        member_id: int,
        consecutive_detections: int,
        hung_duration: float,
    ) -> None:
        """Delegate hung_member_detected to all sensors."""
        for sensor in self._sensors:
            try:
                sensor.on_hung_member_detected(
                    name, namespace, member_id, consecutive_detections, hung_duration
                )
            except Exception as e:
                logger.error(
                    f"Error in {sensor.__class__.__name__}.on_hung_member_detected: {e}",
                    exc_info=True,
                )

    def on_member_terminated(
        self,
        name: str,
        namespace: str,
        member_id: int,
        reason: str,
    ) -> None:
        """Delegate member_terminated to all sensors."""
        for sensor in self._sensors:
            try:
                sensor.on_member_terminated(name, namespace, member_id, reason)
            except Exception as e:
                logger.error(
                    f"Error in {sensor.__class__.__name__}.on_member_terminated: {e}",
                    exc_info=True,
                )

    # =============================================================================
    # Status Update Hooks
    # =============================================================================

    def on_package_install_start(
        self,
        app_name: str,
        namespace: str,
    ) -> Optional[Dict[OperatorSensor, Any]]:
        """Delegate package_install_start to all sensors."""
        if not self._sensors:
            return None
        
        states = {}
        for sensor in self._sensors:
            try:
                state = sensor.on_package_install_start(app_name, namespace)
                if state is not None:
                    states[sensor] = state
            except Exception as e:
                logger.error(
                    f"Error in {sensor.__class__.__name__}.on_package_install_start: {e}",
                    exc_info=True,
                )
        
        return states if states else None
    
    def on_package_install_complete(
        self,
        app_name: str,
        namespace: str,
        state: Optional[Dict[OperatorSensor, Any]],
        success: bool,
        error_type: Optional[str] = None,
        retries: int = 0,
    ) -> None:
        """Delegate package_install_complete to all sensors with their specific state."""
        for sensor in self._sensors:
            try:
                sensor_state = state.get(sensor) if state else None
                sensor.on_package_install_complete(app_name, namespace, sensor_state, success, error_type, retries)
            except Exception as e:
                logger.error(
                    f"Error in {sensor.__class__.__name__}.on_package_install_complete: {e}",
                    exc_info=True,
                )

    def on_package_config_updated(
        self,
        app_name: str,
        namespace: str,
        auth_enabled: bool,
        custom_index_enabled: bool,
    ) -> None:
        """Delegate package_config_updated to all sensors."""
        for sensor in self._sensors:
            try:
                sensor.on_package_config_updated(app_name, namespace, auth_enabled, custom_index_enabled)
            except Exception as e:
                logger.error(
                    f"Error in {sensor.__class__.__name__}.on_package_config_updated: {e}",
                    exc_info=True,
                )

    def on_package_cache_usage_updated(
        self,
        app_name: str,
        namespace: str,
        total_bytes: int,
        used_bytes: int,
        available_bytes: int,
        usage_percent: float,
    ) -> None:
        """Delegate package_cache_usage_updated to all sensors."""
        for sensor in self._sensors:
            try:
                sensor.on_package_cache_usage_updated(
                    app_name, namespace, total_bytes, used_bytes, available_bytes, usage_percent
                )
            except Exception as e:
                logger.error(
                    f"Error in {sensor.__class__.__name__}.on_package_cache_usage_updated: {e}",
                    exc_info=True,
                )

    # =============================================================================
    # Status Update Hooks
    # =============================================================================

    def on_status_update(
        self,
        app_name: str,
        namespace: str,
        update_fields: list[str],
    ) -> None:
        """Delegate status_update to all sensors."""
        for sensor in self._sensors:
            try:
                sensor.on_status_update(app_name, namespace, update_fields)
            except Exception as e:
                logger.error(
                    f"Error in {sensor.__class__.__name__}.on_status_update: {e}",
                    exc_info=True,
                )

    # =============================================================================
    # Utility Methods
    # =============================================================================

    def asdict(self) -> Dict[str, Any]:
        """Return aggregated state from all sensors.
        
        Returns:
            Dict mapping sensor class name to its state dict
        """
        return {
            sensor.__class__.__name__: sensor.asdict()
            for sensor in self._sensors
        }
