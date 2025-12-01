"""Base sensor classes for operator monitoring.

This module defines the base OperatorSensor class that provides lifecycle hooks
for monitoring various operator events. All hooks are no-ops by default, allowing
subclasses to override only the events they care about.

The hook pattern follows Faust's sensor design:
- Hooks come in pairs: on_X_start() and on_X_complete()
- Start hooks return an optional state dict for tracking multi-phase operations
- Complete hooks receive the state dict from their corresponding start hook
- All hooks are optional - sensors only implement what they need
"""

from typing import Dict, Optional, Any
import logging

logger = logging.getLogger(__name__)


class OperatorSensor:
    """Base sensor class for Kaspr operator monitoring.
    
    This class defines lifecycle hooks for three main categories:
    1. Reconciliation lifecycle (full reconciliation loop)
    2. Resource operations (K8s resource sync)
    3. Member management (Kaspr member state and rebalancing)
    
    All methods are no-ops by default. Subclasses override only the hooks
    they need to monitor.
    
    Example:
        class LoggingSensor(OperatorSensor):
            def on_reconcile_start(self, name: str, namespace: str) -> Dict:
                return {'start_time': time.time()}
            
            def on_reconcile_complete(self, name: str, namespace: str, state: Dict) -> None:
                duration = time.time() - state['start_time']
                logger.info(f"Reconciled {name} in {duration}s")
    """

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
        """Called when reconciliation loop begins.
        
        Args:
            app_name: Parent KasprApp resource name
            component_name: Component instance name (agent/table/task/webview)
            namespace: Kubernetes namespace
            generation: Resource generation number
            trigger_source: What triggered reconciliation (field_change, timer, daemon, etc.)
            
        Returns:
            Optional state dict passed to on_reconcile_complete
        """
        pass

    def on_reconcile_complete(
        self,
        app_name: str,
        component_name: str,
        namespace: str,
        state: Optional[Dict[str, Any]],
        success: bool,
        error: Optional[Exception] = None,
    ) -> None:
        """Called when reconciliation loop completes.
        
        Args:
            app_name: Parent KasprApp resource name
            component_name: Component instance name (agent/table/task/webview)
            namespace: Kubernetes namespace
            state: State dict returned from on_reconcile_start
            success: Whether reconciliation succeeded
            error: Exception if reconciliation failed
        """
        pass

    def on_reconcile_queued(
        self,
        app_name: str,
        component_name: str,
        namespace: str,
        queue_depth: int,
    ) -> None:
        """Called when reconciliation request is queued.
        
        Args:
            app_name: Parent KasprApp resource name
            component_name: Component instance name (agent/table/task/webview)
            namespace: Kubernetes namespace
            queue_depth: Current queue depth for this resource
        """
        pass

    def on_reconcile_dequeued(
        self,
        app_name: str,
        component_name: str,
        namespace: str,
        wait_time: float,
    ) -> None:
        """Called when reconciliation request is dequeued.
        
        Args:
            app_name: Parent KasprApp resource name
            component_name: Component instance name (agent/table/task/webview)
            namespace: Kubernetes namespace
            wait_time: Time spent in queue (seconds)
        """
        pass

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
        """Called when K8s resource sync begins.
        
        Args:
            app_name: Parent KasprApp resource name
            component_name: Component instance name (agent/table/task/webview)
            resource_name: Actual K8s resource name being synced
            namespace: Kubernetes namespace
            resource_type: Type of resource (StatefulSet, Service, ConfigMap, etc.)
            
        Returns:
            Optional state dict passed to on_resource_sync_complete
        """
        pass

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
        """Called when K8s resource sync completes.
        
        Args:
            app_name: Parent KasprApp resource name
            component_name: Component instance name (agent/table/task/webview)
            resource_name: Actual K8s resource name being synced
            namespace: Kubernetes namespace
            resource_type: Type of resource
            state: State dict returned from on_resource_sync_start
            operation: Operation performed (created, updated, deleted, no-op)
            success: Whether operation succeeded
            error: Exception if operation failed
        """
        pass

    def on_resource_drift_detected(
        self,
        app_name: str,
        component_name: str,
        resource_name: str,
        namespace: str,
        resource_type: str,
        drift_fields: list[str],
    ) -> None:
        """Called when resource drift is detected during periodic check.
        
        Args:
            app_name: Parent KasprApp resource name
            component_name: Component instance name (agent/table/task/webview)
            resource_name: Actual K8s resource name with drift
            namespace: Kubernetes namespace
            resource_type: Type of resource with drift
            drift_fields: List of fields that drifted from desired state
        """
        pass

    # =============================================================================
    # Member Management Hooks
    # =============================================================================

    def on_rebalance_triggered(
        self,
        name: str,
        namespace: str,
        trigger_reason: str,
    ) -> Optional[Dict[str, Any]]:
        """Called when rebalance is triggered.
        
        Args:
            name: KasprApp resource name
            namespace: Kubernetes namespace
            trigger_reason: Why rebalance was triggered (manual, topology_change, etc.)
            
        Returns:
            Optional state dict passed to on_rebalance_complete
        """
        pass

    def on_rebalance_complete(
        self,
        name: str,
        namespace: str,
        state: Optional[Dict[str, Any]],
        success: bool,
        duration: Optional[float] = None,
    ) -> None:
        """Called when rebalance completes.
        
        Args:
            name: KasprApp resource name
            namespace: Kubernetes namespace
            state: State dict returned from on_rebalance_triggered
            success: Whether rebalance succeeded
            duration: Time taken for rebalance (seconds)
        """
        pass

    def on_member_state_change(
        self,
        name: str,
        namespace: str,
        member_id: int,
        old_state: str,
        new_state: str,
    ) -> None:
        """Called when member transitions between states.
        
        Args:
            name: KasprApp resource name
            namespace: Kubernetes namespace
            member_id: Member ID (0-indexed pod number)
            old_state: Previous state (RUNNING, REBALANCING, CRASHED, etc.)
            new_state: New state
        """
        pass

    def on_hung_member_detected(
        self,
        name: str,
        namespace: str,
        member_id: int,
        consecutive_detections: int,
        hung_duration: float,
    ) -> None:
        """Called when member is detected as hung.
        
        Args:
            name: KasprApp resource name
            namespace: Kubernetes namespace
            member_id: Member ID that is hung
            consecutive_detections: Number of consecutive hung detections (1-3)
            hung_duration: Time member has been in hung state (seconds)
        """
        pass

    def on_member_terminated(
        self,
        name: str,
        namespace: str,
        member_id: int,
        reason: str,
    ) -> None:
        """Called when member pod is forcibly terminated.
        
        Args:
            name: KasprApp resource name
            namespace: Kubernetes namespace
            member_id: Member ID that was terminated
            reason: Reason for termination (hung, manual, etc.)
        """
        pass

    # =============================================================================
    # Package Installation Hooks
    # =============================================================================
    
    def on_package_install_start(
        self,
        app_name: str,
        namespace: str,
    ) -> Optional[Dict[str, Any]]:
        """Called when Python package installation begins.
        
        Args:
            app_name: KasprApp name
            namespace: Kubernetes namespace
            
        Returns:
            Optional state dict passed to on_package_install_complete
        """
        pass
    
    def on_package_install_complete(
        self,
        app_name: str,
        namespace: str,
        state: Optional[Dict[str, Any]],
        success: bool,
        error_type: Optional[str] = None,
    ) -> None:
        """Called when Python package installation completes.
        
        Args:
            app_name: KasprApp name
            namespace: Kubernetes namespace
            state: State dict returned from on_package_install_start
            success: Whether installation succeeded
            error_type: Type of error if installation failed
        """
        pass

    # =============================================================================
    # Status Update Hooks
    # =============================================================================

    def on_status_update(
        self,
        name: str,
        namespace: str,
        update_fields: list[str],
    ) -> None:
        """Called when status is updated.
        
        Args:
            name: KasprApp resource name
            namespace: Kubernetes namespace
            update_fields: List of status fields that were updated
        """
        pass

    # =============================================================================
    # Utility Methods
    # =============================================================================

    def asdict(self) -> Dict[str, Any]:
        """Return sensor state as dictionary.
        
        This method should be overridden by sensors that maintain state
        (like Monitor classes with counters and metrics).
        
        Returns:
            Dictionary representation of sensor state
        """
        return {}
