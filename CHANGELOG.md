# Changelog

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