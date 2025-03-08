import kopf
from kaspr.types.schemas.kasprscheduler_spec import (
    KasprSchedulerSpecSchema,
)
from kaspr.types.models.kasprscheduler_spec import KasprSchedulerSpec
from kaspr.resources.kasprscheduler import KasprScheduler

KIND = "KasprScheduler"


@kopf.on.resume(kind=KIND)
@kopf.on.create(kind=KIND)
def on_create(spec, name, namespace, logger, **kwargs):
    """Creates KasprScheduler resources."""
    spec_model: KasprSchedulerSpec = KasprSchedulerSpecSchema().load(spec)
    kms = KasprScheduler.from_spec(name, KIND, namespace, spec_model)
    kms.create()


@kopf.on.update(kind=KIND, field="spec.image")
@kopf.on.update(kind=KIND, field="spec.version")
def on_version_update(old, new, diff, spec, name, status, namespace, logger, **kwargs):
    spec_model: KasprSchedulerSpec = KasprSchedulerSpecSchema().load(spec)
    kms = KasprScheduler.from_spec(name, KIND, namespace, spec_model)
    kms.patch_version()


@kopf.on.update(kind=KIND, field="spec.replicas")
def on_replicas_update(old, new, diff, spec, name, status, namespace, logger, **kwargs):
    spec_model: KasprSchedulerSpec = KasprSchedulerSpecSchema().load(spec)
    kms = KasprScheduler.from_spec(name, KIND, namespace, spec_model)
    kms.patch_replicas()


@kopf.on.update(kind=KIND, field="spec.bootstrapServers")
@kopf.on.update(kind=KIND, field="spec.tls")
@kopf.on.update(kind=KIND, field="spec.authentication")
def on_kafka_credentials_update(
    old, new, diff, spec, name, status, namespace, logger, **kwargs
):
    spec_model: KasprSchedulerSpec = KasprSchedulerSpecSchema().load(spec)
    kms = KasprScheduler.from_spec(name, KIND, namespace, spec_model)
    kms.patch_kafka_credentials()


@kopf.on.update(kind=KIND, field="spec.resources")
def on_resource_requirements_update(
    old, new, diff, spec, name, status, namespace, logger, **kwargs
):
    spec_model: KasprSchedulerSpec = KasprSchedulerSpecSchema().load(spec)
    kms = KasprScheduler.from_spec(name, KIND, namespace, spec_model)
    kms.patch_resource_requirements()


@kopf.on.update(kind=KIND, field="spec.config.web_port")
def on_web_port_update(old, new, diff, spec, name, status, namespace, logger, **kwargs):
    spec_model: KasprSchedulerSpec = KasprSchedulerSpecSchema().load(spec)
    kms = KasprScheduler.from_spec(name, KIND, namespace, spec_model)
    kms.patch_web_port()


@kopf.on.update(kind=KIND, field="spec.storage.deleteClaim")
def on_storage_delete_claim_update(
    old, new, diff, spec, name, status, namespace, logger, **kwargs
):
    spec_model: KasprSchedulerSpec = KasprSchedulerSpecSchema().load(spec)
    kms = KasprScheduler.from_spec(name, KIND, namespace, spec_model)
    kms.patch_storage_retention_policy()


@kopf.on.update(kind=KIND, field="spec.storage.size")
def on_storage_size_update(
    old, new, diff, spec, name, status, namespace, logger, **kwargs
):
    spec_model: KasprSchedulerSpec = KasprSchedulerSpecSchema().load(spec)
    kms = KasprScheduler.from_spec(name, KIND, namespace, spec_model)
    kms.patch_storage_size()


# @kopf.on.update(kind=KIND, field="spec.config.kms_topic_partitions")
@kopf.on.update(kind=KIND, field="spec.config.topic_partitions")
def immutable_config_updated_00(**kwargs):
    raise kopf.PermanentError(
        "Field 'spec.config.topic_partitions' can't change after creation."
    )

@kopf.on.update(kind=KIND, field="spec.config.kms_topic_partitions")
def immutable_config_updated_01(**kwargs):
    raise kopf.PermanentError(
        "Field 'spec.config.kms_topic_partitions' can't change after creation."
    )



# @kopf.on.validate(kind=KMS_KIND, field="spec.storage.deleteClaim")
# def say_hello(warnings: list[str], **_):
#     warnings.append("Verified with the operator's hook.")

# @kopf.on.validate(kind=KMS_KIND)
# def validate_storage_class_change(spec, old, **kwargs):
#     if 'storage' in spec and 'storage' in old:
#         if spec['storage'].get('class') != old['storage'].get('class'):
#             raise kopf.AdmissionError("Changing the storage.class field is not allowed.")
