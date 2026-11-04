# Definitions delivery

A KasprApp's components (agents, webviews, tables, tasks and joins) reach its pods as YAML files in
the definitions directory (`/var/lib/data/definitions`), which Kaspr reads when it starts. The
operator delivers them in one of two ways:

| Mode | ConfigMaps | Pod volumes and mounts | Joins |
|---|---|---|---|
| `components` (default) | one per component, owned by the component | one per component | not delivered |
| `bundle` | one per shard (usually one), immutable, owned by the KasprApp | one per shard | delivered |

Either way, any change to a component rolls the app's pods: that is how a change takes effect.

## When to use bundles

Use `bundle` for an app with many components. An app with 94 components needs 94 ConfigMaps,
94 volumes and 94 mounts in `components` mode, against one of each in `bundle` mode, and its pod
template shrinks from about 54 KiB to about 10 KiB. KasprJoins need `bundle`.

## Choosing the mode

Annotate the KasprApp:

```yaml
apiVersion: kaspr.io/v1alpha1
kind: KasprApp
metadata:
  name: orders
  annotations:
    kaspr.io/definitions-delivery: bundle   # or: components
```

- The annotation applies at once: the operator writes the bundle, then rolls the pods once.
- Without the annotation, an app keeps the mode its pods run until its pod template changes for
  another reason (a component, the image, the config); that rollout applies the operator default.
  A new app starts with the default.
- The default is the operator setting `DEFINITIONS_DELIVERY_DEFAULT` (Helm:
  `operator.env.definitionsDeliveryDefault`), `components` unless set. Changing it restarts no app.
- Removing the annotation therefore does not switch an app back by itself; set it to `components`.

## What the operator does in `bundle` mode

1. Writes every component into one YAML document, sorted by kind and name, and stores it in a
   ConfigMap named `<app>-app-definitions-<digest>`: immutable, labelled `kaspr.io/app: <app>` and
   `kaspr.io/component: definitions`, owned by the KasprApp. A changed component is a new ConfigMap.
2. Mounts it as one file, `kaspr-definitions-<shard>.yaml`, and rolls the pods.
3. Once the rollout has completed and no pod mounts them, deletes the definitions ConfigMaps the
   pods no longer use: earlier bundles, and the per-component ConfigMaps of `components` mode.

Tables, joins, tasks and agents always share the first shard, so a join finds its tables and an agent
finds a join's channel when Kaspr builds them. Webviews fill further shards when an app's definitions
exceed `DEFINITIONS_BUNDLE_SHARD_BYTES` (512 KiB by default). A shard over 1,000,000 bytes fails the
reconciliation with `DefinitionsTooLarge`, and the pods keep running what they have.

## Status

```yaml
status:
  definitions:
    delivery: bundle
    configMaps: [orders-app-definitions-3f9a1c2b7d]
    components: 94
    bytes: 188287
    pendingDeletion: 94     # waiting for the rollout; omitted when 0
```

- Components of a bundle app report `delivery: bundle` and no `configMap`.
- An app with KasprJoins has the condition `JoinsDelivered`: `True` in `bundle` mode, `False`
  (reason `RequiresBundleDelivery`) in `components` mode, where its joins are not delivered.
- Events on the KasprApp: `DefinitionsDeliveryChanged`, `DefinitionsBundleCreated`,
  `DefinitionsCleanedUp`, and the warnings `DefinitionsTooLarge`, `DefinitionsConflict`,
  `InvalidDefinitionsDelivery`, `JoinsNotDelivered`.

## Going back

Annotate `kaspr.io/definitions-delivery: components`. The operator recreates the per-component
ConfigMaps, rolls the pods, then deletes the bundles once the rollout has completed.

An operator from before bundles ignores the annotation and rolls the app back to per-component
ConfigMaps, leaving its bundles until the KasprApp is deleted. To remove them by hand:

```sh
kubectl delete configmap -l kaspr.io/app=<app>,kaspr.io/component=definitions
```

Design: [definitions bundles](../design/definitions-bundle.md).
