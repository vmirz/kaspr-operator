# Design: Definitions Bundles

> **Status:** Accepted, in implementation (`feature/definitions-bundle`)
> **Date:** 2026-11-03
> **Scope:** kaspr-operator. No Kaspr runtime change; no CRD change.

---

## Table of Contents

1. [Summary](#summary)
2. [How definitions reach a pod today](#how-definitions-reach-a-pod-today)
3. [Goals and non-goals](#goals-and-non-goals)
4. [Terms](#terms)
5. [Design](#design)
6. [Migration](#migration)
7. [Failure modes](#failure-modes)
8. [Compatibility](#compatibility)
9. [Testing and validation](#testing-and-validation)
10. [Alternatives considered](#alternatives-considered)

---

## Summary

Today the operator gives every component (agent, webview, table, task) its own ConfigMap, its own pod
volume and its own `subPath` mount. An app with 94 components runs 94 definition ConfigMaps, 94 volumes and
94 bind mounts per pod, and its pod template is five times the size of a two-component app's.

This design adds a second **delivery mode**, `bundle`. The KasprApp reconciliation writes all of an app's
components into one YAML document, stored in an **immutable, content-addressed ConfigMap** owned by the
KasprApp. The pod mounts that one file. Large apps spill into a few shards.

- An app opts in per KasprApp with the annotation `kaspr.io/definitions-delivery: bundle`.
- An operator setting chooses the default for apps without the annotation: `components` in this release.
  A change of the default never restarts an app by itself. Apps without the annotation switch at their
  next rollout.
- The operator deletes the definitions ConfigMaps an app no longer mounts, once no pod can need them.
- KasprJoins are delivered in bundles; this also makes them work for the first time (see
  [KasprJoin](#kasprjoin)).

---

## How definitions reach a pod today

```
Kaspr<Component> CR ──handler──▶ ConfigMap <name>-<kind>   (key <name>-<kind>.yaml, owned by the CR)
        │                                ▲
        └──event──▶ KasprApp reconcile ──┘ re-syncs every component ConfigMap (second writer)
                          │
                          ▼
             StatefulSet: per component one configMap volume
                          + one subPath mount /var/lib/data/definitions/<name>-<kind>.yaml
             env AGENTS_HASH / WEBVIEWS_HASH / TABLES_HASH / TASKS_HASH
                          │
                          ▼
             Kaspr AppBuilder: rglob("*.yaml") under the definitions dir, one AppSpec per file
```

- Any added, removed or changed component changes a hash env var, which rolls every pod. `subPath` files
  never update in place, so the rollout is what delivers the change. This stays.
- A definitions file may hold any number of components of every kind (`agents`, `webviews`, `tables`,
  `joins`, `tasks` lists).
- Measured on an app with 94 components (74 webviews, 8 agents, 4 tables, 8 tasks):

| | 94 components | 2 components |
|---|---|---|
| Definition ConfigMaps | 94 | 2 |
| Template volumes / container mounts | 95 / 96 (94 `subPath`) | 3 / 4 |
| Mounts in the container | 124 | 32 |
| Pod template | 53.7 KiB | 10.2 KiB |
| 6 ControllerRevisions | 325 KiB | 68 KiB |
| Definitions | 185 KiB | 3.4 KiB |

- Volume setup time does not grow measurably (under 1 s at 97 volumes). The cost is linear sprawl: objects,
  pod spec and revision size, one kubelet watch per ConfigMap per node, one bind mount per component.

### Constraints verified before this design

- **A whole-directory ConfigMap mount breaks Kaspr.** The kubelet writes the files into a hidden
  `..<timestamp>/` directory and links them from the volume root. `AppBuilder._files` (`rglob`) finds every
  file twice (Python 3.12 and 3.14), so the second copy of a webview fails the startup with
  `ValueError` (duplicate method). Single files mounted with `subPath` avoid this.
- **One merged document loads identically.** Kaspr 0.11.31's `AppSpecSchema` loads one 188 KB document to
  the same 8 agents, 74 webviews, 4 tables and 8 tasks as the 94 separate files.
- **Build order is per file.** `AppBuilder.build()` builds, per file, tables → joins → tasks → agents;
  files come in directory order; webviews register after every file is built. A join reads
  `app.tables[...]` (`KeyError` when its table is not built yet), and an agent reading a join's channel
  silently gets a fresh in-memory channel when the join is not built yet.
- **A ConfigMap holds at most 1 MiB** of data (`1048576` bytes).
- **A new spec field would be pruned** by a cluster whose CRDs were not re-applied (`helm` never upgrades
  `crds/`). Annotations and status (`x-kubernetes-preserve-unknown-fields`) are not.

---

## Goals and non-goals

**Goals**

- One definitions volume and one mount per app (per shard), and one definitions ConfigMap per app (per
  shard), for any number of components.
- Each pod revision mounts exactly the definitions it was rolled for.
- No orphaned ConfigMaps: whatever the operator stops mounting is deleted once nothing can mount it, and
  everything it creates is owned so that Kubernetes collects it when the owner goes.
- Apps that do not opt in are untouched: identical StatefulSets and status, byte for byte. Their component
  ConfigMaps keep their data; only their hash annotation changes once (see Compatibility).
- Migration in both directions with one rollout, safe against operator restarts at any step.
- KasprJoins delivered to the app's pods.

**Non-goals**

- Applying definition changes without a restart. A changed component still rolls the app.
- Fewer component CRs. Components stay one CR each, with their own status and events.
- Kaspr runtime changes.

---

## Terms

| Term | Meaning |
|---|---|
| Component | A KasprAgent, KasprWebView, KasprTable, KasprTask or KasprJoin labelled `kaspr.io/app=<app>` |
| Delivery mode | How an app's components reach its pods: `components` (one ConfigMap each, today) or `bundle` |
| Bundle | The YAML document holding an app's components; stored in one or more **shards** |
| Shard | One immutable ConfigMap holding one bundle document, mounted as one file |
| Deployed mode | The mode the app's StatefulSet template currently uses, read from its volumes |
| Target mode | The mode this reconciliation renders |
| Definitions ConfigMap | A shard, or a per-component ConfigMap the operator created for a component |

---

## Design

### 1. Choosing an app's mode

Inputs: the annotation `kaspr.io/definitions-delivery` on the KasprApp, the operator setting
`DEFINITIONS_DELIVERY_DEFAULT`, and the app's StatefulSet.

| Annotation | StatefulSet | Target mode |
|---|---|---|
| `bundle` or `components` | any | the annotation's mode, at once |
| absent (or invalid: warning event) | none yet | the default |
| absent | deployed mode = default | the default |
| absent | deployed mode ≠ default, pod template unchanged otherwise | the deployed mode (no restart) |
| absent | deployed mode ≠ default, pod template changing anyway | the default, in that same rollout |

- **Deployed mode**: `bundle` when the template has a volume named `kaspr-definitions-<i>`, otherwise
  `components`. An app with no components renders the same template in both modes.
- **"Changing anyway"**: the template rendered in the deployed mode differs from the live one in a field the
  operator renders verbatim and the API server never rewrites: container and init container images, the
  `*_HASH` env values, the sorted volume names, the sorted mount `name:mountPath` pairs, the service account
  name. A change elsewhere (resources, probes, pod template) is not detected; the switch then happens at a
  later rollout. Never at the cost of an extra one.
- Removing the annotation therefore does not switch an app back by itself: it falls under the default rule.
  `components` switches back at once.
- An app whose definitions outgrew the bundle it runs (rendering it in the deployed mode fails with
  `DefinitionsTooLarge`) counts as changing anyway, so without the annotation it takes the default.

### 2. Bundle document

- The same component specs as the per-component files (`KasprAppComponentsSchema` dump), in one document:
  `{agents: [...], joins: [...], tables: [...], tasks: [...], webviews: [...]}`, only non-empty kinds,
  each kind sorted by component name. Same input, same bytes.
- **Shard 0 holds every table, join, task and agent**, plus webviews by name while the shard is within the
  budget. Kaspr builds tables → joins → tasks → agents within one file, so a join always finds its tables
  and an agent always finds a join's channel. Further shards hold webviews only (they register after all
  files are built, so their file does not matter).
- **Budget**: `DEFINITIONS_BUNDLE_SHARD_BYTES` (default 512 KiB) of YAML per shard. Shard 0 may exceed it
  to keep the non-webview components together. A shard over the hard limit (1,000,000 bytes, under the
  1 MiB ConfigMap limit) fails the reconciliation with `DefinitionsTooLarge`; nothing else changes.
- The operator parses each shard back and compares it with what it dumped before writing it.

### 3. Shard ConfigMaps

| Field | Value |
|---|---|
| `metadata.name` | `<app>-app-definitions-<first 10 hex of sha256(document)>` |
| `immutable` | `true` |
| `data` | `definitions.yaml: <document>` |
| labels | the app's labels, `kaspr.io/app: <app>`, `kaspr.io/component: definitions` |
| annotations | `kaspr.io/definitions-shard: "<i>"`, `kaspr.io/definitions-components: "<n>"` |
| `ownerReferences` | the KasprApp (`controller: true`, `blockOwnerDeletion: true`) |

- Content-addressed: a changed document is a new ConfigMap; an unchanged one keeps its name. Creating an
  existing name is a no-op once the operator has checked the existing object is this app's shard with the
  same data. Any other object under that name fails the reconciliation; nothing is overwritten.
- Immutable: the kubelet does not watch it, and it can never change under a pod.

### 4. Pod template in `bundle` mode

```yaml
volumes:
  - name: kaspr-definitions-0
    configMap:
      name: <app>-app-definitions-3f9a1c2b7d
      items: [{key: definitions.yaml, path: definitions.yaml}]
containers:
  - name: kaspr
    volumeMounts:
      - name: kaspr-definitions-0
        mountPath: /var/lib/data/definitions/kaspr-definitions-0.yaml
        subPath: definitions.yaml
        readOnly: true
    env:   # unchanged values, plus JOINS_HASH when the app has joins
      - {name: AGENTS_HASH, value: ...}
      - {name: WEBVIEWS_HASH, value: ...}
```

- No per-component volumes or mounts. The `*_HASH` values are computed exactly as in `components` mode, so
  a switch changes nothing else, and component hashes in `status.linkedResources` do not move.
- In `components` mode the template is today's, byte for byte. Joins are never mounted in that mode.

### 5. Reconciliation sequence

```
1. List agents, webviews, tables, tasks, joins (no KasprJoin CRD, or no permission to read
   KasprJoins, lists as no joins)
2. Read the StatefulSet (moved up from sync_stateful_set; still one read)
3. Resolve the target mode (§1)
4. Write the definitions for the target mode
      components: today's sync_component_config_maps (create/patch per-component ConfigMaps)
      bundle:     create missing shards (never patch one)
5. synchronize(): services, …, StatefulSet patch rendered in the target mode → rollout
6. Clean up (§6)
7. Status: linkedResources (with the delivered joins); component statuses
```

A failure at any step stops the reconciliation before the next one; it is retried (`RETRY`). Steps 4–6 are
idempotent, so a retry, or an operator restart, continues from the cluster's state.

**Other writers of the pod template.** The create/resume handler and the `spec.replicas`,
`spec.storage.size` and `spec.template.pod` handlers write the whole pod template. They now attach the
components, resolve the mode and write missing shards first, exactly like steps 1–4. Before, they
rendered the template without the components, so each briefly wrote a template without definitions
until the next reconciliation restored it, and an operator restart would have rolled a bundle app back
to per-component ConfigMaps. The other field handlers send a strategic merge patch, which keeps the
definitions volumes, mounts and env of the live template.

### 6. Cleanup

**Invariant**: once an app's rollout has completed, its definitions ConfigMaps are exactly those its pod
template mounts.

**Candidates** (labelled `kaspr.io/app=<app>`):

| Deployed mode | Candidates |
|---|---|
| `bundle` | shards (`kaspr.io/component: definitions`) the template does not mount; every per-component ConfigMap (owned by a `kaspr.io` component, named `<owner>-<kind>`) |
| `components` | every shard |

Nothing else is ever a candidate: not the app's settings ConfigMap, not ConfigMaps the user mounts through
templates, not per-component ConfigMaps of a `components`-mode app.

**A candidate is deleted only when all hold:**

1. The StatefulSet exists and its template is in the target mode (this reconciliation's patch landed).
2. `status.observedGeneration == metadata.generation`.
3. `status.currentRevision == status.updateRevision` and `status.updatedReplicas == status.replicas`.
   While a rollout runs, the StatefulSet controller recreates a lost old pod from the *current* revision,
   which still mounts the old ConfigMaps.
4. No pod of the app (by the StatefulSet's selector, terminating pods included) mounts it.

- Deleted with `preconditions.uid` of the listed object; `404` counts as deleted, `409` is retried next pass.
- **When**: after every full reconciliation, and on every status refresh (30 s) while candidates wait for a
  rollout. Every full reconciliation lists the app's ConfigMaps (reusing the definitions sync's listing), so
  the candidates come from the cluster, never from a status; after an operator restart the next full
  reconciliation finds them again. A `components`-mode app with no shards left makes no other call.
- **Ownership backs it up**: shards are owned by the KasprApp, per-component ConfigMaps by their component,
  so deleting either owner removes them even if the operator never runs again.

### 7. Components

**Agents, webviews, tables, tasks.** The component handler checks its app:

- App delivers bundles: no per-component ConfigMap is written, and `configMap` is removed from the
  component's status (`app` and `hash` as before). The app's annotation decides; without a valid one, the
  app's StatefulSet (`bundle` when it mounts shards), read only then; without a StatefulSet, the default.
- Otherwise, or when the app does not exist: today's behaviour and today's status, unchanged.

A per-component ConfigMap written in a race with a switch is a cleanup candidate (§6).

When an app's mode changes, the KasprApp removes or restores its components' `configMap`, so they do not
wait for their own next event. Components whose status already matches are not patched.

**KasprJoin.**

- Before this change the operator never loaded the KasprJoin handlers (`kaspr/__init__.py` did not import
  them), the KasprApp did not list joins, and the StatefulSet mounted none: a KasprJoin did nothing.
- After this change:
  - The handler uses the shared component path (`reconcile_component`, `notify_app`). It never writes a
    ConfigMap. Its status reports `app`, `leftTable`, `rightTable` (found when a KasprTable of that name
    belongs to the same app) and `hash`. A join whose spec does not load is left out of the app with a
    warning; the join's own handler reports the error.
  - `bundle` mode: joins go into shard 0 (§2), `JOINS_HASH` joins the env, and a change to the set of joins
    or their tables marks `rebalanceRequired`. A join consumes internal topics Faust names after the app and
    both tables (`<app>-app-<left>-<right>-subscription-registration`, `-subscription-response`,
    `-subscriptions-changelog`, `-previous-fk-changelog`). They count among the app's subscriptions: static
    members keep the assignment they had, so without a rebalance no member is assigned them and the join
    stays inert.
  - `components` mode: joins are not delivered, and the pods are not touched. Each join gets a
    `NotDelivered` warning on every reconciliation of its own and when its app switches away from bundles;
    the app's `DefinitionsDeliveryChanged` event names them.

### 8. Status and events

No status field or condition on the KasprApp reports the delivery. `components` mode is transitional
(dropped in a later major release, see Migration); once every app delivers bundles such a field says
nothing, and until then the cluster answers every question it would:

| Question | Where |
|---|---|
| Which mode does the app run? | Its StatefulSet: volumes `kaspr-definitions-<i>` in `bundle` mode |
| Which bundle, how many components? | `kubectl get configmap -l kaspr.io/app=<app>,kaspr.io/component=definitions`; each shard's `kaspr.io/definitions-components` annotation |
| What waits to be deleted? | Definitions ConfigMaps of the app its StatefulSet does not mount; they go once its rollout completes (§6) |

The only new status is the delivered joins in `status.linkedResources`, where they decide rebalances
(§7). Components of a `bundle` app lose their `configMap`.

| Event (KasprApp) | Type | When |
|---|---|---|
| `DefinitionsDeliveryChanged` | Normal | The target mode differs from the deployed mode; says why (annotation, default) and names the joins a switch to `components` leaves out |
| `DefinitionsBundleCreated` | Normal | Shards created: names, components, bytes |
| `DefinitionsCleanedUp` | Normal | ConfigMaps deleted |
| `DefinitionsTooLarge` | Warning | A shard exceeds the hard limit |
| `DefinitionsConflict` | Warning | A shard's name is taken by an object that is not this app's shard |
| `InvalidDefinitionsDelivery` | Warning | The annotation has another value |

Errors (`DefinitionsTooLarge`, a foreign object under a shard name) go through the existing reconciliation
error path: `Progressing=False`, `Ready=False` with the message. The pods keep running what they have.

### 9. Settings

| Environment variable | Default | Meaning |
|---|---|---|
| `DEFINITIONS_DELIVERY_DEFAULT` | `components` | Mode of apps without the annotation (§1). Another value logs an error and keeps `components` |
| `DEFINITIONS_BUNDLE_SHARD_BYTES` | `524288` | YAML bytes per shard before webviews spill into the next one; clamped to 64 KiB–1,000,000 |

---

## Migration

### One app, by annotation

| Step | What happens | Restarts |
|---|---|---|
| 1. Upgrade the operator | `components` apps render byte-identical StatefulSets | none |
| 2. Annotate `kaspr.io/definitions-delivery: bundle` | Shards created; StatefulSet patched | one rollout |
| 3. Rollout completes | Per-component ConfigMaps deleted (§6) | none |
| Back out: annotate `components` | Per-component ConfigMaps recreated first; StatefulSet patched; shards deleted after the rollout | one rollout |

### Changing the default

- `DEFINITIONS_DELIVERY_DEFAULT=bundle` changes nothing at once. New apps start in `bundle` mode; existing apps
  without the annotation switch within their next rollout (§1). Flipping it back works the same way.
- A later release makes `bundle` the default value, then a major release drops `components`.

### Downgrading the operator

An older operator ignores the annotation and the shards. It recreates the per-component ConfigMaps
(`sync_component_config_maps` creates missing ones) and rolls the app back to them. The shards then stay
until the KasprApp is deleted, or until this operator returns and cleans them up; to remove them by hand:
`kubectl delete configmap -l kaspr.io/app=<app>,kaspr.io/component=definitions`.

---

## Failure modes

| Scenario | Behaviour | Recovery |
|---|---|---|
| Operator stops after creating shards, before the StatefulSet patch | Shards exist, unmounted; pods unchanged | Next reconciliation reuses them (same names) or, if the definitions changed, cleans them up |
| Operator stops after the patch, before cleanup | Old ConfigMaps stay | Next full reconciliation or status refresh deletes them once §6 holds |
| Operator stops during cleanup | Some deleted | Next pass deletes the rest; deletions are idempotent |
| New pods fail (bad definition) | Rollout never completes; old ConfigMaps kept, so old pods can still be recreated | Fix forward: the next change is a new shard and a new rollout |
| Old pod lost mid-rollout | Recreated from the current revision, whose ConfigMaps still exist | None needed |
| Definitions over the hard limit | Reconciliation fails before any write; `DefinitionsTooLarge` | Reduce definitions, or stay in `components` mode |
| Shard name taken by a foreign object | Reconciliation fails; nothing overwritten | Delete or rename the foreign object |
| Shard deleted by hand while mounted | Running pods keep their file | Next reconciliation recreates it |
| KasprApp deleted mid-migration | Kubernetes deletes the shards (owner) and the StatefulSet | None needed |
| Component deleted | Its per-component ConfigMap goes with it (owner); the next shard omits it | None needed |
| ConfigMap quota reached | Shard creation fails; no patch; retried | Raise the quota by the shard count |
| Operator downgraded | See [Downgrading](#downgrading-the-operator) | Manual label-selected delete |

---

## Compatibility

- **Kaspr**: no change. Shards use the per-kind keys Kaspr has always read. Joins need Kaspr ≥ 0.9.1
  (`JoinSpecSchema`); older versions ignore the `joins` key.
- **CRDs**: no change. The mode is an annotation; the delivered joins in `status.linkedResources` fall under
  `x-kubernetes-preserve-unknown-fields`.
- **RBAC**: no change. ConfigMaps (create, delete, list), pods (list) and StatefulSets are already granted.
- **Kubernetes**: immutable ConfigMaps are GA since 1.21.
- **`components`-mode apps**: same StatefulSet, ConfigMap data and status. API calls: one KasprJoin list
  per full reconciliation; a component's reconciliation reads its app's StatefulSet unless the app is
  annotated; an app without components lists its ConfigMaps once per full reconciliation.
- **Component ConfigMaps' hash annotation**: it used to be computed before the annotation existed and never
  matched the component's hash (its status, its app's `*_HASH` env). It now does. On upgrade each component
  ConfigMap gets one metadata patch; component hashes, and so pod templates, do not change.

---

## Testing and validation

**Unit tests** (`tests/unit/test_definitions*.py`, `legacy_rendering.py`)

- Golden renderings of every example app, and of one app holding every example component, made by
  v0.19.8's code: StatefulSets (with their `kaspr.io/resource-hash`) are byte-identical on this branch,
  KasprJoin attached included; component ConfigMaps differ only in their hash annotation, which now
  equals the component's hash.
- Shards: one document holds each component as its own ConfigMap does; sorted; content-addressed names;
  core kinds in shard 0, webviews spilling; hard limit.
- Mode resolution: every row of §1, the template-change detector, definitions outgrowing a bundle.
- Writing shards against a fake API: created immutable and owned, left alone when present, a create race,
  a missing owner added, foreign objects refused.
- Cleanup: candidates per mode, each precondition, pods mounting, a replaced or vanished ConfigMap, and
  which apps pay an API call for it.
- Component and join handlers in both modes, the mode read from the annotation, the StatefulSet or the
  default; KasprJoin CRD or permission missing; an invalid join.
- Nothing about definitions in the app's status; components' `configMap` removed and restored on a
  switch; joins warned when they stop being delivered; joins as linked resources and their topics as
  subscriptions.
- The full-template handlers render the components first; scaling no longer patches a template without
  definitions (the test fails with the fix removed).

**Cluster validation** (k3s 1.34, Kaspr 0.11.31; the branch replaced the operator)

| Check | Result |
|---|---|
| Offline: every live app rendered by the branch vs its StatefulSet hash, fingerprint and ConfigMaps (13 apps) | identical |
| Branch operator over existing apps: startup, a full reconcile cycle, a restart | no StatefulSet, revision, pod, ConfigMap or status change |
| Probe app (tables, a join and its consumer, agents, webviews, a task) to `bundle` | shard created before the patch, one rollout, 7 ConfigMaps deleted 11 s after it |
| Edits, additions, deletions in `bundle` mode | new shard, one rollout, previous shard deleted after it; unchanged content reuses its name |
| Join in `bundle` mode | built, rebalance requested and verified by the operator, joined records emitted |
| Operator killed right after a StatefulSet patch | rollout completes; the restarted operator deletes the old shard |
| Leftover shard; mounted shard deleted by hand | leftover deleted; mounted one recreated under its name; no pod restart |
| ConfigMap quota blocking a shard | reconcile fails before the patch, pods keep serving; converges once lifted |
| Old-revision pod lost mid-rollout | recreated and started; old shard kept until the rollout completed |
| 611 KB of definitions | two shards, two mounts; every webview answers; the join still works |
| Back to `components`; annotation removed | ConfigMaps recreated before the patch; shards deleted; no rollout on removal |
| App deleted in `bundle` mode | shards and StatefulSet collected by their owner |
| Components created before an app born in `bundle` mode | their ConfigMaps deleted once the first pod was ready |
| 94-component app to `bundle` and back | 95 → 2 ConfigMaps, 124 → 31 mounts, template 53.7 → 15.1 KiB; all 53 routes served; back to the original revision, ConfigMaps and statuses |
| Operator default flipped to `bundle`, then back to `components` | nothing restarted over a full cycle either way; an unannotated app switched within its next rollout, each way |
| Component ConfigMaps' hash annotation (247 ConfigMaps) | one metadata patch each, data unchanged, nothing else changed; every annotation equals its component's hash; stable a cycle later |
| No delivery status: existing apps over startup, a full cycle and an operator kill | no StatefulSet, revision, pod, component or app status change; no `definitions` status, `JoinsDelivered` condition or `delivery` field anywhere |
| No delivery status: probe to `bundle` and back, with a join | components lost and regained `configMap`; old ConfigMaps deleted 4–26 s after each rollout; the join named and warned when left out; the rebalance after its delivery took effect |
| Unannotated app running `bundle`, every component reconciled | each read the StatefulSet and wrote no ConfigMap |
| `components`-mode app left with a shard and no components, operator killed right after the patch | the restarted operator's first reconciliation listed and deleted the shard |
| App without components annotated `bundle` | no `DefinitionsDeliveryChanged` over a full cycle |

## Alternatives considered

| Option | Why not |
|---|---|
| Projected volume over the per-component ConfigMaps | Keeps one ConfigMap and one kubelet watch per component; a directory mount needs a Kaspr change (duplicate loads) |
| Mutable bundle patched in place | During a rollout, a restarted old pod would load the new definitions under the old pod spec |
| Pods read definitions from the API at start | Gives every app pod read access to Kaspr CRs, ties each start to the API server, unpins the revision |
| A CRD holding many components | Targets CR count, not attachment; loses per-component status and events |
| Directory mount with files in a subfolder | Kaspr finds each file once only by accident of `rglob`'s symlink handling, and races the kubelet's swap |
