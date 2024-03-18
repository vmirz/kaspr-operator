# TODO

## Helm

- Helm chart to deploy operator and CRs

## Admission validation

- Validate CR spec via admission webhooks

## Probes

- Add default readiness & liveness probes

## Resource Customization

Often we need to customize underlying k8s resouces owned by a CR.

- Add "templates" to spec. See strimzi for inspiration/guidance. [Strimzi] (https://strimzi.io/docs/operators/latest/configuring.html#type-KafkaConnectTemplate-reference)


### Documentation

-   Immutable configurations
