# Changelog

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