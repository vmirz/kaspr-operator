# Changelog

## 0.14.2
--
### Changed
* **Python Packages - Ephemeral Storage by Default**: Changed default to `cache.enabled: false` for easier adoption
  * Uses ephemeral emptyDir storage by default (works on any Kubernetes cluster)
  * Status reports cache mode as "persistent" or "ephemeral" for clarity
  * Users can enable persistent cache with `cache.enabled: true` if ReadWriteMany storage is available

## 0.14.1
--
### Added
* **Python Packages - emptyDir Support**: Added ephemeral storage mode when shared cache is unavailable
  * New emptyDir mode (cache disabled) eliminates ReadWriteMany storage requirement
  * Packages reinstalled per pod start in ephemeral mode
  * Automatic fallback when cache disabled or RWX storage unavailable

### Fixed
* **Python Packages - ReadWriteOnce Removed**: Removed unsupported ReadWriteOnce access mode
  * Only ReadWriteMany supported for shared package cache
  * Added storage class validation with warnings for non-RWX provisioners
  * Default access mode set to ReadWriteMany with enum validation

## 0.14.0
--
### Added
* **Python Packages Management**: Declarative Python package installation in KasprApp CRD
  * Install packages via `pythonPackages.packages` list (e.g., `pandas>=2.0.0`)
  * Optional persistent cache using PVC with ReadWriteMany access mode
  * Configurable installation policies (retries, timeout, failure handling)
  * Package hash-based change detection triggers pod rollouts
  * Status reporting with installation details and errors

## 0.13.3
--
### Changed
* **Hung Member Detection**: Removed assignment requirement from hung member detection logic
  * Members with any assignment state (including zero assignments) are now eligible for hung detection
  * Previously, members without active or standby assignments were skipped during hung detection
  * Info log entry is now created when a member has no assignments but still meets other hung criteria
  * All other hung detection criteria remain unchanged:
    - Member must be in rebalancing state (`rebalancing=true` and `recovering=false`)
    - Must exceed configured threshold (default 300s, configurable via `kaspr.io/hung-rebalancing-threshold-seconds`)
    - App's rollout must be complete (Progressing condition is False)
    - Must be detected for 3 consecutive checks before termination

### Technical Notes
* Updated `_detect_hung_members()` function to remove assignment filtering
* Docstring updated to reflect that zero-assignment members are now eligible for hung detection
* Info logging added: `"Member {member_id} has no assignments but meets other hung criteria"`

## 0.13.2
--
### Fixed
* **False Positive Subscription Change Detection**: Fixed issue where failed resource fetches would trigger incorrect rebalance requests
  * Added success tracking to `fetch_app_related_resources()` to detect when any resource fetch fails
  * Subscription change evaluation now only occurs when all related resources (agents, tables, webviews, tasks) are successfully fetched
  * Prevents false positives from empty resource lists when Kubernetes API calls fail
  * Logs warning message when skipping subscription detection due to fetch failures

### Technical Notes
* `fetch_app_related_resources()` now returns a `success` boolean alongside resource lists
* `_update_linked_resources_status()` checks fetch success before comparing resource states
* Error handling maintains partial results for non-subscription operations while safely skipping subscription change logic

## 0.13.1
--
### Added
* **Comprehensive Grafana Dashboard**: New production-ready dashboard at `grafana-dashboards/kaspr-operator.json` with complete operator metrics visualization
  * **29 Panels** organized into 3 sections: Reconciliation Health, Kubernetes Resource Sync, and Rebalance & Member Health
  * **Reconciliation Health Section** (8 panels):
    - Reconciliation rate by result (success/failure) with color-coded time series
    - Error rate gauge with threshold alerts (green <5%, yellow 5-10%, orange 10-25%, red >25%)
    - Total reconciliations counter with success/failure breakdown
    - Duration percentiles (P50/P95/P99) for performance tracking
    - Average duration stat with color-coded thresholds
    - Reconciliations by trigger source (stacked area chart)
    - Errors by type breakdown
    - Top 10 most active resources (pie chart)
  * **Kubernetes Resource Sync Section** (9 panels):
    - Sync rate by operation (create/patch/delete) with success/failure tracking
    - Sync rate by resource type (stacked area)
    - Duration percentiles for sync operations
    - Total operations counter and error rate gauge
    - Resource drift detection rate and top 10 drifted fields
    - Errors by type and detailed per-resource table with success rate gauges
  * **Rebalance & Member Health Section** (12 panels):
    - Rebalance rate by result and trigger reason
    - Total rebalances counter and duration percentiles
    - Average rebalance duration with color-coded thresholds (green <60s, yellow 60-120s, orange 120-300s, red >300s)
    - Member state transitions tracking
    - Hung member detection rate and strike count gauge (3-strike system visualization)
    - Hung member duration and terminations by reason
    - Total terminations counter
    - Status updates by field (stacked area)
  * **Dashboard Features**:
    - Template variables: datasource (Prometheus), namespace, and app_name with "All" support
    - 1-hour default time range with 30-second auto-refresh
    - Compatible with Grafana v12.2.0, schema version 39
    - All panels use rate calculations and histogram quantiles for accurate metrics
    - Consistent color coding: green=success/healthy, red=failure/error, yellow/orange=warning states

### Changed
* **Improved Dashboard Organization**: Replaced simple scheduler dashboard with comprehensive operator monitoring dashboard
  * Moved from `grafana/kaspr-operator-dashboard.json` to `grafana-dashboards/kaspr-operator.json`
  * Added collapsible row sections for better organization
  * Enhanced metric queries using histogram_quantile for percentile calculations
  * Improved visualizations with appropriate chart types (time series, gauges, stats, tables, pie charts)

### Technical Notes
* All dashboard panels use the `kasprop_` metric prefix matching the Prometheus sensor implementation
* Queries use `$__rate_interval` for optimal rate calculations based on dashboard time range
* Table panel includes success rate calculations with LCD gauge visualization
* Hung member strike count gauge shows 0-3 range with color gradients for visual clarity

## 0.13.0
--
### Added
* **Operator Observability Framework**: Comprehensive sensor-based monitoring system for operator health and performance
  * **Sensor Architecture**: Hook-based event system with 15 lifecycle methods covering reconciliation, resources, and member operations
  * **SensorDelegate Pattern**: Fan-out delegation to multiple monitoring backends with isolated error handling
  * **Prometheus Integration**: Complete metrics collection backend with 15+ metrics across 3 categories:
    - **Reconciliation Loop Health** (5 metrics): duration, total operations, errors, queue depth, queue wait time
    - **Rebalance & Member Health** (7 metrics): rebalance duration/total, state transitions, hung member detection/tracking/duration, terminations
    - **Resource Sync & Status** (5 metrics): sync duration/total/errors, drift detection, status updates
  * **Metrics HTTP Server**: Standalone Prometheus endpoint on port 8000 (configurable via `METRICS_PORT`)
  * **Rich Label Dimensions**: All metrics include `app_name` and `namespace` with context-specific labels (trigger_source, result, member_id, resource_type, etc.)
  * **Histogram Buckets**: Carefully tuned for expected ranges (reconciliation: 0.1-120s, resource sync: 0.01-10s, rebalance: 1-600s)
* **Grafana Dashboard**: Production-ready dashboard with 18 panels organized into 3 collapsible rows
  * Template variables for datasource, app name, and namespace filtering
  * Time series visualizations with percentile calculations (p50/p95/p99)
  * Stat panels with color-coded thresholds for queue depth and hung members
  * Auto-refresh every 30 seconds, 1-hour default time range
  * Located at `grafana/kaspr-operator-dashboard.json`

### Changed
* **Instrumented Reconciliation Loop**: Added sensor hooks throughout core operator flow
  * `reconcile()`: Tracks full reconciliation duration and success/failure
  * `request_reconciliation()`: Records queue operations and depth
  * `process_reconciliation_requests()`: Measures queue wait time
  * `update_status()`: Tracks status field updates
  * `_detect_hung_members()`: Records detection count, consecutive attempts, and duration
  * `_terminate_hung_members()`: Logs termination events with member ID and reason
  * `_attempt_auto_rebalance()`: Measures rebalance duration and outcome
* **Sensor Access Pattern**: Centralized sensor access via `KasprApp.sensor` class attribute and `get_sensor()` helper
* **Startup Initialization**: Sensor system initialized in `kaspr/app.py` setup() function alongside other global resources

### Dependencies
* Added `prometheus-client==0.21.0` for metrics exposition

### Technical Notes
* Sensor hooks are non-invasive - failures in monitoring don't affect operator control flow
* State dictionary pattern enables multi-phase operation tracking (start/complete hooks)
* Metrics server runs in daemon thread to avoid blocking operator
* All hooks gracefully handle missing sensor instance for backwards compatibility
* Dashboard compatible with Grafana v12.2.0

## 0.12.0
--
### Added
* **Hung Member Detection & Recovery**: Automatic detection and recovery of members stuck in rebalancing state
  * Detects members meeting all criteria: `rebalancing=true`, `recovering=false`, has assignments, exceeds time threshold
  * Only triggers when rollout is complete (Progressing condition = False)
  * Configurable via `HUNG_MEMBER_DETECTION_ENABLED` environment variable (default: true)
  * Default threshold: 300 seconds (5 minutes) via `HUNG_REBALANCING_THRESHOLD_SECONDS`
  * Per-app overrides via annotations:
    - `kaspr.io/hung-member-detection-enabled: "true|false"`
    - `kaspr.io/hung-rebalancing-threshold-seconds: "600"`
  * Automatic pod termination with 10-second grace period
  * Parallel termination with 15-second timeout for multiple hung members
  * Status condition `Ready=False` with reason `HungMembers` when detected
* **Pod Deletion Support**: Added `delete_pod()` method to `BaseResource` for controlled pod termination
* **Member Termination**: Added `terminate_member(member_id)` method to `KasprApp` for targeted pod deletion

### Changed
* **Enhanced Member Status Tracking**: Member objects now include only essential fields (id, leader, rebalancing, recovering, lastTransitionTime)
  * Removed unnecessary fields from status to reduce noise
  * Detailed logging of specific state changes (leader, rebalancing, recovering transitions)
* **Improved Status Update Flow**: Detection and termination of hung members integrated into `update_status()` workflow
  * Detection happens before condition updates
  * Termination happens after all status updates complete
  * Prevents status rollback on termination errors

### Technical Notes
* Hung member detection uses `lastTransitionTime` to determine how long a member has been in rebalancing state
* Members without assignments (empty actives and standbys) are never considered hung
* Detection is skipped during rollouts to avoid false positives during normal scaling operations
* Uses distributed systems terminology "hung" instead of "stuck" for processes that have stopped making progress

## 0.11.2
--
### Added
* **Member State Tracking**: Added `lastTransitionTime` to member objects to track when state changes occur (leader, rebalancing, recovering)
* **Rebalancing Visibility**: Added `rebalancingMembers` status field showing count in "X/Y" format (e.g., "1/3" = 1 rebalancing out of 3 available members)
  * Displayed in `kubectl get kasprapp` output for quick visibility
  * Aggregated from individual member rebalancing status

### Changed
* **Improved Subscription Change Detection**: Enhanced logic to compare topic-level subscriptions rather than agent counts
  * Handles comma-separated topic names correctly
  * Multiple agents can subscribe to same topics without triggering false rebalance
  * Only actual topic subscription changes trigger rebalance
* **Migration Safety**: First-time initialization of `linkedResources` tracking doesn't trigger rebalance on existing apps
  * Prevents unnecessary rebalances when operator is upgraded
  * Graceful transition for existing deployments

### Fixed
* **False Positive Rebalances**: Agent/table count changes no longer trigger rebalance unless actual topic subscriptions change

## 0.11.0
--
### Added
* **Automatic Rebalance on Subscription Changes**: Operator now automatically triggers rebalance when Kafka subscriptions change due to agent or table modifications
  * Surgical change detection: only monitors subscription-affecting fields (agent topic names/patterns, table names)
  * Configurable via `AUTO_REBALANCE_ENABLED` environment variable (default: true)
  * Per-app override via `kaspr.io/auto-rebalance` annotation
  * Natural retry mechanism via `rebalanceRequired` status flag
* **Enhanced Status Tracking**: KasprApp status now includes `linkedResources` field tracking agents, tables, webviews, and tasks with subscription-relevant metadata
  * Agents: tracks `topicName` and `topicPattern` from input spec
  * Tables: tracks `tableName` which determines changelog topic
  * Enables precise detection of subscription changes
* **Improved Error Handling**: Added `convert_api_exception()` utility to transform Kubernetes API exceptions into Kopf-compatible errors

### Changed
* **Refactored `update_status()`**: Extracted monolithic function into focused, modular helpers for better readability and maintainability
* **Enhanced Configuration Support**: Added in-cluster config loading with fallback to local kubeconfig for GKE/production deployments
* **Simplified CLI**: Streamlined `run_operator.py` to pass through all kopf CLI arguments directly

### Fixed
* **Agent Topic Field**: Corrected from `input.topic.names` (plural) to `input.topic.name` (singular, comma-separated)

### Technical Notes
* Automatic rebalance uses direct call to `app.request_rebalance()` rather than annotation mechanism for better performance and simpler control flow
* Manual rebalances via `kaspr.io/rebalance` annotation remain separate path for user-initiated operations

## 0.5.28
--
* New: support pausing KasprApp reconciliation via annotation: `kaspr.io/pause-reconciliation`
* New: upgrade application's kaspr version upon new operator default.

## 0.4.2
--
* Improvements to how resource `status` is updated
* Improvements to reconciliation

* 
## 0.4.0
--
* Support KasprTable CRD
* Use camelCase to define app configuration keys
* Removed `topic_prefix` app setting
* Removed `KasprScheduler` CRD

## 0.3.8
--
* Rename KasprApp resources with `-app` suffix

## 0.3.5
---

## 0.3.2
---
* Minor improvements

## 0.3.1
---
* Deprecated `KasprScheduler` CRD

## 0.3.0
---
* Add support for webview