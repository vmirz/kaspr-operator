# Vertical pod autoscaling

A KasprApp can ask the operator for a
[VerticalPodAutoscaler](https://github.com/kubernetes/autoscaler/tree/master/vertical-pod-autoscaler)
(VPA), which sets the resources of the app's `kaspr` container from their observed usage. It is
opt-in: the operator creates nothing unless `spec.verticalPodAutoscaler.enabled` is `true`.

```yaml
apiVersion: kaspr.io/v1alpha1
kind: KasprApp
metadata:
  name: orders
spec:
  replicas: 3
  resources:                 # what pods start with; the CPU limit is the ceiling
    requests: {cpu: 500m, memory: 1Gi}
    limits: {cpu: "2", memory: 2Gi}
  verticalPodAutoscaler:
    enabled: true
    minAllowed: {cpu: 100m}
    maxAllowed: {cpu: "1500m"}
  # ...
```

The operator then manages a VerticalPodAutoscaler named `<app>-app-vpa`, owned by the app (it is
deleted with it, or when `enabled` is turned off):

```yaml
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: orders-app-vpa
spec:
  targetRef: {apiVersion: kaspr.io/v1alpha1, kind: KasprApp, name: orders}
  updatePolicy: {updateMode: InPlaceOrRecreate}
  resourcePolicy:
    containerPolicies:
    - containerName: kaspr
      mode: Auto
      controlledResources: [cpu]
      controlledValues: RequestsOnly
      minAllowed: {cpu: 100m}
      maxAllowed: {cpu: 1500m}
    - containerName: "*"
      mode: "Off"
```

## Settings

| Field | Default | Meaning |
|---|---|---|
| `enabled` | `false` | Create and manage the VerticalPodAutoscaler. Nothing else in the block has any effect without it. |
| `updateMode` | `InPlaceOrRecreate` | How recommendations are applied (see below). |
| `controlledResources` | `[cpu]` | `cpu`, `memory`, or both. |
| `controlledValues` | `RequestsOnly` | `RequestsOnly` sets requests and keeps the limits in `spec.resources` as ceilings; `RequestsAndLimits` sets both, keeping their ratio. |
| `minAllowed`, `maxAllowed` | none | Bounds of the requests the VPA may set, as `{cpu, memory}` quantities. |
| `minReplicas` | the VPA updater's `--min-replicas` (2) | Fewest running pods that allow the VPA to evict one. |

## What the VerticalPodAutoscaler changes

The VPA never edits the KasprApp or its StatefulSet: `spec.resources` stays what pods start with.
It changes pods: its admission webhook sets the recommended requests on every pod as it is created,
and its updater changes running pods when their requests drift out of the recommended range (or
by more than 10% on pods older than 12 hours, or after an out-of-memory kill).

| `updateMode` | Running pods |
|---|---|
| `Off` | Left alone; the VPA only computes recommendations (`kubectl describe vpa <app>-app-vpa`). |
| `Initial` | Left alone; pods get the recommendation whenever they are created for another reason. |
| `Recreate` (`Auto` is a deprecated alias) | Evicted, at most half of the app's pods at a time, and recreated with the new requests. Each eviction is a pod restart: Python packages are installed again, and the member rejoins its consumer group. |
| `InPlaceOrRecreate` | Resized in place, without a restart. Evicted only when that is impossible: the node cannot fit the new requests, the resize stays pending for 5 minutes or in progress for an hour, or the pod's QoS class would change. Needs Kubernetes 1.33+ and VPA 1.4+. |
| `InPlace` | Resized in place only, never evicted. Needs the VPA's `InPlace` feature gate (alpha in VPA 1.7). |

Editing `spec.resources` itself is different: the operator renders it into the StatefulSet's pod
template, so every pod is restarted, one at a time. That is why the VPA, not the operator, applies
recommendations.

Things to know:

* **Apps with one replica** are below the VPA updater's default `--min-replicas` of 2, so the VPA
  never evicts their only pod. Where the updater runs with `--in-place-skip-disruption-budget`,
  `InPlaceOrRecreate` still resizes them in place; otherwise they are only updated when their pod
  is created. `minReplicas: 1` lets the VPA update them either way, evicting the app's single
  member when an in-place resize is impossible.
* **Apps without requests** (`spec.resources` unset) start BestEffort pods, and a resize cannot add
  requests to a running BestEffort pod. Each pod is recreated once to get its first requests, and is
  resized in place from then on. The `VerticalPodAutoscalerReady` condition mentions it.
* **CPU beyond one core** helps a Kaspr worker less than it may seem. Its agents, serialization and
  Kafka client all run in one asyncio event loop holding Python's GIL, so they use at most about one
  core; more only serves work that runs outside it, such as RocksDB's background threads, native
  libraries that release the GIL, and child processes. Set `maxAllowed` near what the app can use,
  and add replicas (up to the partition count) for more throughput.
* **Throttling hides demand.** The VPA only sees the CPU a container gets, so a tight CPU limit keeps
  its recommendation from rising above it. With `RequestsOnly` the limit in `spec.resources` stays
  fixed and the VPA never sets a request above it; with `RequestsAndLimits` a falling recommendation
  lowers the limit as well.
* **The operator's HPA** keeps scaling the StatefulSet to `spec.replicas` (it only staggers how many
  pods start at once). Its target is an absolute memory value, not a share of requests, so the VPA's
  advice against combining it with an HPA on the same resource does not apply.
* **Pausing reconciliation** (`kaspr.io/pause-reconciliation`) leaves the VerticalPodAutoscaler as
  it is, like everything else the operator manages.

## Memory

Kaspr sizes its RocksDB block cache once, when it starts: a third of the container's memory limit
(or of the node's memory without a limit), unless `STORE_ROCKSDB_BLOCK_CACHE_SIZE` is set. A memory
limit changed in place would go unnoticed until the next restart, and a lowered one would leave the
cache sized for the old limit. Memory is therefore not autoscaled by default.

With `memory` in `controlledResources`, the operator sets the kaspr container's
`resizePolicy` to restart the container (not the pod) on a memory resize, and to apply CPU resizes
as they are:

```yaml
resizePolicy:
- {resourceName: cpu, restartPolicy: NotRequired}
- {resourceName: memory, restartPolicy: RestartContainer}
```

Adding or removing `memory` changes the pod template, which restarts the app's pods once. Because
the container then restarts on resizes, the VPA updater applies its disruption limits even to
in-place updates.

## Status

While vertical autoscaling is enabled, the app reports its VerticalPodAutoscaler in the
`VerticalPodAutoscalerReady` condition, updated on every reconciliation:

| Status | Reason | Meaning |
|---|---|---|
| `True` | `Configured` | The VerticalPodAutoscaler exists and matches the spec. Its recommendations are in `kubectl describe vpa <app>-app-vpa`. |
| `False` | `NotInstalled` | The cluster does not serve `autoscaling.k8s.io/v1`. |
| `False` | `Forbidden` | The operator may not manage `verticalpodautoscalers.autoscaling.k8s.io`. |
| `False` | `Invalid` | The API server rejected the VerticalPodAutoscaler, e.g. an `updateMode` the installed VPA version does not know. |
| `False` | `Conflict` | A VerticalPodAutoscaler named `<app>-app-vpa` exists that the app does not own; it is left alone. |
| `False` | `ConfigUnsupported` | The VPA reports that it cannot use its configuration. |
| `False` | `Error` | Any other failure. |

None of these affect the rest of the app, which is reconciled and reported (`Ready`,
`Progressing`) as usual. A change of the condition is also posted as an event on the app
(`VerticalPodAutoscaler<Reason>`, a Warning for problems).

## Clusters without the Vertical Pod Autoscaler

The operator does not assume the VPA is installed. It discovers the `autoscaling.k8s.io/v1` API
once a minute: apps that enable vertical autoscaling get the `NotInstalled` condition and run with
`spec.resources`, and once the VPA is installed their VerticalPodAutoscalers are created at the next
reconciliation. Apps that do not enable it make no VPA requests beyond looking, while the API
exists, for a VerticalPodAutoscaler of theirs to delete.

The operator's RBAC (the Helm chart's `kaspr-operator-namespaced` ClusterRole) needs `get`,
`create`, `patch` and `delete` on `verticalpodautoscalers` in the `autoscaling.k8s.io` group; the
rule grants nothing where the VPA is not installed.

## The scale subresource

KasprApp has a scale subresource. It reads `spec.replicas`, the app's pod count
(`status.replicas`) and its pod selector (`status.selector`), which the operator reports on every
status refresh. That makes `kubectl scale kasprapp <app> --replicas=N` work, and lets other
autoscalers target a KasprApp. A VerticalPodAutoscaler you write yourself must target the KasprApp,
not its StatefulSet: a VPA only accepts the top-most owner of its pods that is scalable, and with
the scale subresource that is the KasprApp.

The operator's own VerticalPodAutoscaler targets the KasprApp through it. In a cluster whose
KasprApp CRD predates the subresource (Helm does not upgrade CRDs), it targets the StatefulSet
instead, and switches once the CRD is updated.

## HPAs left behind by older operators

Operators before this release created an app's HPA without an owner reference when the app was
scaled up from zero, so deleting the app left its HPA behind (failing with `FailedGetScale`). The
operator now adds the owner reference to the HPA of every app it reconciles. HPAs of apps deleted
before the upgrade have no app left to repair them; this lists them, for deletion with
`kubectl delete hpa -n <namespace> <name>`:

```bash
kubectl get hpa -A -o json | jq -r '.items[]
  | select((.metadata.ownerReferences // []) == [] and (.metadata.name | endswith("-app-hpa"))
           and .spec.scaleTargetRef.kind == "StatefulSet")
  | "\(.metadata.namespace) \(.metadata.name)"' |
while read -r ns name; do
  kubectl get kasprapp -n "$ns" "${name%-app-hpa}" >/dev/null 2>&1 || echo "$ns $name"
done
```
