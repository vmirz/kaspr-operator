"""Prometheus monitoring backend for Kaspr operator.

This module provides PrometheusMonitor, which collects operator lifecycle events
and exposes them as Prometheus metrics. It implements the three critical metric
categories identified in the design:

1. Reconciliation Loop Health - Duration, queue depth, throughput, errors
2. Rebalance & Member Health - Rebalance tracking, hung members, state transitions
3. Kubernetes Resource Sync - Operation counts, latency, drift detection

All metrics include labels for multi-dimensional analysis (app_name, namespace, etc.).
"""

from typing import Dict, Optional, Any
import time
import logging

from prometheus_client import Counter, Histogram, Gauge

from kaspr.sensors.base import OperatorSensor

logger = logging.getLogger(__name__)


class PrometheusMonitor(OperatorSensor):
    """Prometheus metrics monitor for Kaspr operator.
    
    Exposes metrics via prometheus_client that can be scraped by Prometheus.
    All metrics include consistent labels for filtering and aggregation.
    
    Metrics are organized into three categories matching the design:
    - kaspr_reconcile_* - Reconciliation loop metrics
    - kaspr_rebalance_* / kaspr_member_* - Member and rebalance metrics  
    - kaspr_resource_* - Kubernetes resource sync metrics
    
    Example:
        monitor = PrometheusMonitor()
        
        # Reconciliation
        state = monitor.on_reconcile_start("my-app", "default", 5, "timer")
        monitor.on_reconcile_complete("my-app", "default", state, True)
        
        # Metrics are automatically recorded and exposed via /metrics endpoint
    """

    def __init__(self):
        """Initialize Prometheus metrics."""
        super().__init__()
        
        # =============================================================================
        # Reconciliation Loop Metrics
        # =============================================================================
        
        self.reconcile_duration = Histogram(
            'kasprop_reconcile_duration_seconds',
            'Time spent in reconciliation loop',
            labelnames=['app_name', 'component_name', 'namespace', 'trigger_source', 'result'],
            buckets=[0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0],
        )
        
        self.reconcile_total = Counter(
            'kasprop_reconcile_total',
            'Total number of reconciliation attempts',
            labelnames=['app_name', 'component_name', 'namespace', 'trigger_source', 'result'],
        )
        
        self.reconcile_errors = Counter(
            'kasprop_reconcile_errors_total',
            'Total number of reconciliation errors',
            labelnames=['app_name', 'component_name', 'namespace', 'error_type'],
        )
        
        self.reconcile_queue_depth = Gauge(
            'kasprop_reconcile_queue_depth',
            'Current reconciliation queue depth per resource',
            labelnames=['app_name', 'component_name', 'namespace'],
        )
        
        self.reconcile_queue_wait_seconds = Histogram(
            'kasprop_reconcile_queue_wait_seconds',
            'Time spent waiting in reconciliation queue',
            labelnames=['app_name', 'component_name', 'namespace'],
            buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 10.0, 30.0],
        )
        
        # =============================================================================
        # Rebalance & Member Health Metrics
        # =============================================================================
        
        self.rebalance_duration = Histogram(
            'kasprop_rebalance_duration_seconds',
            'Time spent in rebalancing',
            labelnames=['app_name', 'namespace', 'trigger_reason', 'result'],
            buckets=[1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0],
        )
        
        self.rebalance_total = Counter(
            'kasprop_rebalance_total',
            'Total number of rebalance attempts',
            labelnames=['app_name', 'namespace', 'trigger_reason', 'result'],
        )
        
        self.member_state_transitions = Counter(
            'kasprop_member_state_transitions_total',
            'Total number of member state transitions',
            labelnames=['app_name', 'namespace', 'member_id', 'from_state', 'to_state'],
        )
        
        self.hung_members_detected = Counter(
            'kasprop_hung_members_detected_total',
            'Total number of hung member detections',
            labelnames=['app_name', 'namespace', 'member_id'],
        )
        
        self.hung_member_consecutive_detections = Gauge(
            'kasprop_hung_member_consecutive_detections',
            'Current consecutive hung detection count (3-strike system)',
            labelnames=['app_name', 'namespace', 'member_id'],
        )
        
        self.hung_member_duration_seconds = Gauge(
            'kasprop_hung_member_duration_seconds',
            'Time member has been in hung state',
            labelnames=['app_name', 'namespace', 'member_id'],
        )
        
        self.member_terminations = Counter(
            'kasprop_member_terminations_total',
            'Total number of member pod terminations',
            labelnames=['app_name', 'namespace', 'member_id', 'reason'],
        )
        
        # =============================================================================
        # Kubernetes Resource Sync Metrics
        # =============================================================================
        
        self.resource_sync_duration = Histogram(
            'kasprop_resource_sync_duration_seconds',
            'Time spent syncing Kubernetes resources',
            labelnames=['app_name', 'component_name', 'resource_name', 'namespace', 'resource_type', 'operation', 'result'],
            buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 2.5, 5.0, 10.0],
        )
        
        self.resource_sync_total = Counter(
            'kasprop_resource_sync_total',
            'Total number of resource sync operations',
            labelnames=['app_name', 'component_name', 'resource_name', 'namespace', 'resource_type', 'operation', 'result'],
        )
        
        self.resource_sync_errors = Counter(
            'kasprop_resource_sync_errors_total',
            'Total number of resource sync errors',
            labelnames=['app_name', 'component_name', 'resource_name', 'namespace', 'resource_type', 'error_type'],
        )
        
        self.resource_drift_detected = Counter(
            'kasprop_resource_drift_detected_total',
            'Total number of resource drift detections',
            labelnames=['app_name', 'component_name', 'resource_name', 'namespace', 'resource_type', 'drift_field'],
        )
        
        # =============================================================================
        # Status Update Metrics
        # =============================================================================
        
        self.status_updates = Counter(
            'kasprop_status_updates_total',
            'Total number of status updates',
            labelnames=['app_name', 'namespace', 'update_field'],
        )
        
        # =============================================================================
        # Python Package Installation Metrics
        # =============================================================================
        
        self.package_install_duration_seconds = Histogram(
            'kasprop_package_install_duration_seconds',
            'Time taken to install Python packages',
            labelnames=['app_name', 'namespace'],
            buckets=[1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0],
        )
        
        self.package_install_total = Counter(
            'kasprop_package_install_total',
            'Total number of package installations',
            labelnames=['app_name', 'namespace', 'result'],  # result: success/failure
        )
        
        self.package_install_errors_total = Counter(
            'kasprop_package_install_errors_total',
            'Total number of package installation errors',
            labelnames=['app_name', 'namespace', 'error_type'],
        )
        
        # Phase 2: Authentication metrics
        self.package_auth_enabled = Gauge(
            'kasprop_package_auth_enabled',
            'Whether PyPI authentication is configured (1=enabled, 0=disabled)',
            labelnames=['app_name', 'namespace'],
        )
        
        # Phase 2: Custom index metrics
        self.package_custom_index_enabled = Gauge(
            'kasprop_package_custom_index_enabled',
            'Whether custom PyPI index is configured (1=enabled, 0=disabled)',
            labelnames=['app_name', 'namespace'],
        )
        
        # Phase 2: Cache usage metrics
        self.package_cache_usage_bytes = Gauge(
            'kasprop_package_cache_usage_bytes',
            'Python package cache disk usage in bytes',
            labelnames=['app_name', 'namespace', 'type'],  # type: total|used|available
        )
        
        self.package_cache_usage_percent = Gauge(
            'kasprop_package_cache_usage_percent',
            'Python package cache disk usage percentage',
            labelnames=['app_name', 'namespace'],
        )
        
        # Phase 2: Install policy metrics
        self.package_install_retries_total = Counter(
            'kasprop_package_install_retries_total',
            'Total number of package installation retries',
            labelnames=['app_name', 'namespace'],
        )
        
        self.package_install_timeouts_total = Counter(
            'kasprop_package_install_timeouts_total',
            'Total number of package installation timeouts',
            labelnames=['app_name', 'namespace'],
        )
        
        logger.info("PrometheusMonitor initialized with all metrics")

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
    ) -> Optional[Dict[str, Any]]:
        """Record reconciliation start time."""
        return {
            'start_time': time.time(),
            'trigger_source': trigger_source,
        }

    def on_reconcile_complete(
        self,
        app_name: str,
        component_name: str,
        namespace: str,
        state: Optional[Dict[str, Any]],
        success: bool,
        error: Optional[Exception] = None,
    ) -> None:
        """Record reconciliation duration and result."""
        if state:
            duration = time.time() - state['start_time']
            trigger_source = state['trigger_source']
            result = 'success' if success else 'failure'
            
            self.reconcile_duration.labels(
                app_name=app_name,
                component_name=component_name,
                namespace=namespace,
                trigger_source=trigger_source,
                result=result,
            ).observe(duration)
            
            self.reconcile_total.labels(
                app_name=app_name,
                component_name=component_name,
                namespace=namespace,
                trigger_source=trigger_source,
                result=result,
            ).inc()
            
            if error:
                error_type = error.__class__.__name__
                self.reconcile_errors.labels(
                    app_name=app_name,
                    component_name=component_name,
                    namespace=namespace,
                    error_type=error_type,
                ).inc()

    def on_reconcile_queued(
        self,
        app_name: str,
        component_name: str,
        namespace: str,
        queue_depth: int,
    ) -> None:
        """Record reconciliation queue depth."""
        self.reconcile_queue_depth.labels(
            app_name=app_name,
            component_name=component_name,
            namespace=namespace,
        ).set(queue_depth)

    def on_reconcile_dequeued(
        self,
        app_name: str,
        component_name: str,
        namespace: str,
        wait_time: float,
    ) -> None:
        """Record time spent waiting in queue."""
        self.reconcile_queue_wait_seconds.labels(
            app_name=app_name,
            component_name=component_name,
            namespace=namespace,
        ).observe(wait_time)

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
    ) -> Optional[Dict[str, Any]]:
        """Record resource sync start time."""
        return {
            'start_time': time.time(),
            'resource_type': resource_type,
            'resource_name': resource_name,
        }

    def on_resource_sync_complete(
        self,
        app_name: str,
        component_name: str,
        resource_name: str,
        namespace: str,
        resource_type: str,
        state: Optional[Dict[str, Any]],
        operation: str,
        success: bool,
        error: Optional[Exception] = None,
    ) -> None:
        """Record resource sync duration and result."""
        if state:
            duration = time.time() - state['start_time']
            result = 'success' if success else 'failure'
            
            self.resource_sync_duration.labels(
                app_name=app_name,
                component_name=component_name,
                resource_name=resource_name,
                namespace=namespace,
                resource_type=resource_type,
                operation=operation,
                result=result,
            ).observe(duration)
            
            self.resource_sync_total.labels(
                app_name=app_name,
                component_name=component_name,
                resource_name=resource_name,
                namespace=namespace,
                resource_type=resource_type,
                operation=operation,
                result=result,
            ).inc()
            
            if error:
                error_type = error.__class__.__name__
                self.resource_sync_errors.labels(
                    app_name=app_name,
                    component_name=component_name,
                    resource_name=resource_name,
                    namespace=namespace,
                    resource_type=resource_type,
                    error_type=error_type,
                ).inc()

    def on_resource_drift_detected(
        self,
        app_name: str,
        component_name: str,
        resource_name: str,
        namespace: str,
        resource_type: str,
        drift_fields: list[str],
    ) -> None:
        """Record resource drift detection."""
        for field in drift_fields:
            self.resource_drift_detected.labels(
                app_name=app_name,
                component_name=component_name,
                resource_name=resource_name,
                namespace=namespace,
                resource_type=resource_type,
                drift_field=field,
            ).inc()

    # =============================================================================
    # Member Management Hooks
    # =============================================================================

    def on_rebalance_triggered(
        self,
        name: str,
        namespace: str,
        trigger_reason: str,
    ) -> Optional[Dict[str, Any]]:
        """Record rebalance start time."""
        return {
            'start_time': time.time(),
            'trigger_reason': trigger_reason,
        }

    def on_rebalance_complete(
        self,
        name: str,
        namespace: str,
        state: Optional[Dict[str, Any]],
        success: bool,
        duration: Optional[float] = None,
    ) -> None:
        """Record rebalance duration and result."""
        if state:
            # Use provided duration or calculate from state
            actual_duration = duration if duration is not None else (time.time() - state['start_time'])
            trigger_reason = state['trigger_reason']
            result = 'success' if success else 'failure'
            
            self.rebalance_duration.labels(
                app_name=name,
                namespace=namespace,
                trigger_reason=trigger_reason,
                result=result,
            ).observe(actual_duration)
            
            self.rebalance_total.labels(
                app_name=name,
                namespace=namespace,
                trigger_reason=trigger_reason,
                result=result,
            ).inc()

    def on_member_state_change(
        self,
        name: str,
        namespace: str,
        member_id: int,
        old_state: str,
        new_state: str,
    ) -> None:
        """Record member state transition."""
        self.member_state_transitions.labels(
            app_name=name,
            namespace=namespace,
            member_id=str(member_id),
            from_state=old_state,
            to_state=new_state,
        ).inc()

    def on_hung_member_detected(
        self,
        name: str,
        namespace: str,
        member_id: int,
        consecutive_detections: int,
        hung_duration: float,
    ) -> None:
        """Record hung member detection."""
        member_id_str = str(member_id)
        
        self.hung_members_detected.labels(
            app_name=name,
            namespace=namespace,
            member_id=member_id_str,
        ).inc()
        
        self.hung_member_consecutive_detections.labels(
            app_name=name,
            namespace=namespace,
            member_id=member_id_str,
        ).set(consecutive_detections)
        
        self.hung_member_duration_seconds.labels(
            app_name=name,
            namespace=namespace,
            member_id=member_id_str,
        ).set(hung_duration)

    def on_member_terminated(
        self,
        name: str,
        namespace: str,
        member_id: int,
        reason: str,
    ) -> None:
        """Record member termination."""
        member_id_str = str(member_id)
        
        self.member_terminations.labels(
            app_name=name,
            namespace=namespace,
            member_id=member_id_str,
            reason=reason,
        ).inc()
        
        # Clear hung member gauges when terminated
        self.hung_member_consecutive_detections.labels(
            app_name=name,
            namespace=namespace,
            member_id=member_id_str,
        ).set(0)
        
        self.hung_member_duration_seconds.labels(
            app_name=name,
            namespace=namespace,
            member_id=member_id_str,
        ).set(0)

    # =============================================================================
    # Status Update Hooks
    # =============================================================================

    def on_package_install_start(
        self,
        app_name: str,
        namespace: str,
    ) -> Optional[Dict[str, Any]]:
        """Record package installation start time."""
        return {'start_time': time.time()}
    
    def on_package_install_complete(
        self,
        app_name: str,
        namespace: str,
        state: Optional[Dict[str, Any]],
        success: bool,
        error_type: Optional[str] = None,
        retries: int = 0,
    ) -> None:
        """Record package installation completion with metrics.
        
        Args:
            app_name: KasprApp name
            namespace: Kubernetes namespace
            state: State dict from on_package_install_start
            success: Whether installation succeeded
            error_type: Type of error if installation failed (e.g., 'timeout', 'network', 'invalid_package')
            retries: Number of retry attempts that occurred during installation
        """
        if state:
            duration = time.time() - state.get('start_time', time.time())
            
            # Record duration
            self.package_install_duration_seconds.labels(
                app_name=app_name,
                namespace=namespace,
            ).observe(duration)
        
        # Record result
        result = "success" if success else "failure"
        self.package_install_total.labels(
            app_name=app_name,
            namespace=namespace,
            result=result,
        ).inc()
        
        # Record error if failed
        if not success and error_type:
            self.package_install_errors_total.labels(
                app_name=app_name,
                namespace=namespace,
                error_type=error_type,
            ).inc()
        
        # Record retries
        if retries > 0:
            self.package_install_retries_total.labels(
                app_name=app_name,
                namespace=namespace,
            ).inc(retries)
        
        # Record timeout
        if error_type == 'timeout':
            self.package_install_timeouts_total.labels(
                app_name=app_name,
                namespace=namespace,
            ).inc()

    def on_package_config_updated(
        self,
        app_name: str,
        namespace: str,
        auth_enabled: bool,
        custom_index_enabled: bool,
    ) -> None:
        """Record package configuration state.
        
        Args:
            app_name: KasprApp name
            namespace: Kubernetes namespace
            auth_enabled: Whether PyPI authentication is configured
            custom_index_enabled: Whether a custom PyPI index is configured
        """
        self.package_auth_enabled.labels(
            app_name=app_name,
            namespace=namespace,
        ).set(1 if auth_enabled else 0)
        
        self.package_custom_index_enabled.labels(
            app_name=app_name,
            namespace=namespace,
        ).set(1 if custom_index_enabled else 0)

    def on_package_cache_usage_updated(
        self,
        app_name: str,
        namespace: str,
        total_bytes: int,
        used_bytes: int,
        available_bytes: int,
        usage_percent: float,
    ) -> None:
        """Record package cache disk usage.
        
        Args:
            app_name: KasprApp name
            namespace: Kubernetes namespace
            total_bytes: Total cache capacity in bytes
            used_bytes: Used cache space in bytes
            available_bytes: Available cache space in bytes
            usage_percent: Cache usage as a percentage (0-100)
        """
        self.package_cache_usage_bytes.labels(
            app_name=app_name,
            namespace=namespace,
            type='total',
        ).set(total_bytes)
        
        self.package_cache_usage_bytes.labels(
            app_name=app_name,
            namespace=namespace,
            type='used',
        ).set(used_bytes)
        
        self.package_cache_usage_bytes.labels(
            app_name=app_name,
            namespace=namespace,
            type='available',
        ).set(available_bytes)
        
        self.package_cache_usage_percent.labels(
            app_name=app_name,
            namespace=namespace,
        ).set(usage_percent)

    def on_status_update(
        self,
        app_name: str,
        namespace: str,
        update_fields: list[str],
    ) -> None:
        """Record status update."""
        for field in update_fields:
            self.status_updates.labels(
                app_name=app_name,
                namespace=namespace,
                update_field=field,
            ).inc()
