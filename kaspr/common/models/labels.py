from typing import Dict

class ResourceLabels:
    KASPR_DOMAIN: str = "kaspr.io/"

    KASPR_KIND_LABEL = KASPR_DOMAIN + "kind"

    KASPR_CLUSTER_LABEL = KASPR_DOMAIN + "cluster"

    KASPR_COMPONENT_TYPE_LABEL = KASPR_DOMAIN + "component-type"

    KASPR_NAME_LABEL = KASPR_DOMAIN + "name"


class Labels(ResourceLabels):
    KUBERNETES_DOMAIN = "app.kubernetes.io/"

    KUBERNETES_NAME_LABEL = KUBERNETES_DOMAIN + "name"

    KUBERNETES_INSTANCE_LABEL = KUBERNETES_DOMAIN + "instance"

    KUBERNETES_PART_OF_LABEL = KUBERNETES_DOMAIN + "part-of"

    APPLICATION_NAME = "kaspr"

    KUBERNETES_MANAGED_BY_LABEL = KUBERNETES_DOMAIN + "managed-by"

    KUBERNETES_STATEFULSET_POD_LABEL = "statefulset.kubernetes.io/pod-name"

    _labels: Dict[str, str]

    def __init__(self, labels: Dict[str, str] = None) -> None:
        self._labels = labels if labels else dict()

    def update(self, labels: Dict[str, str]) -> "Labels":
        self._labels.update(labels.copy())
        return self

    def as_dict(self) -> Dict[str, str]:
        """Return labels are dictionary."""
        return self._labels.copy()

    def as_str(self):
        """Return labels as comma separated string."""
        return ",".join([f"{k}={v}" for k, v in self._labels.items()])

    def include(self, label: str, value: str) -> "Labels":
        self.update({label: value})
        return self

    def include_kaspr_kind(self, kind) -> "Labels":
        return self.include(self.KASPR_KIND_LABEL, kind)

    def include_kaspr_cluster(self, cluster: str) -> "Labels":
        return self.include(self.KASPR_CLUSTER_LABEL, cluster)

    def include_kubernetes_name(self, name: str) -> "Labels":
        return self.include(self.KUBERNETES_NAME_LABEL, name)

    def include_kubernetes_instance(self, instance_name: str) -> "Labels":
        return self.include(self.KUBERNETES_INSTANCE_LABEL, instance_name)

    def include_kubernetes_part_of(self, instance_name: str) -> "Labels":
        return self.include(
            self.KUBERNETES_PART_OF_LABEL,
            self.get_or_valid_instance_label_value(
                f"{self.APPLICATION_NAME}-{instance_name}"
            ),
        )

    def get_or_valid_instance_label_value(self, instance: str):
        """Validates the instance name and if needed modifies it to make it a valid Label value:
        * (([A-Za-z0-9][-A-Za-z0-9_.]*)?[A-Za-z0-9])?
        * 63 characters max
        """

        if not instance:
            return ""

        i = min(len(instance), 63)
        while i > 0:
            last_char = instance[len(instance) - 1 :]
            if last_char in [".", "-", "_"]:
                i = -1
            else:
                break
        return instance[:i]

    def include_kubernetes_managed_by(self, operator_name: str) -> "Labels":
        return self.include(self.KUBERNETES_MANAGED_BY_LABEL, operator_name)

    def include_kaspr_name(self, name: str) -> "Labels":
        return self.include(self.KASPR_NAME_LABEL, name)

    def include_kaspr_component_type(self, type: str) -> "Labels":
        return self.include(self.KASPR_COMPONENT_TYPE_LABEL, type)

    def contains(self, other: "Labels"):
        """Returns True if all labels in `other` are contained."""
        return all(
            key in self._labels and self._labels[key] == value
            for key, value in other.as_dict().items()
        )

    def kasper_label_selectors(self):
        kaspr_selector_labels = [
            self.KASPR_CLUSTER_LABEL,
            self.KASPR_NAME_LABEL,
            self.KASPR_KIND_LABEL,
        ]
        return Labels(
            {
                key: self._labels[key]
                for key in kaspr_selector_labels
                if key in self._labels
            }
        )

    def __str__(self):
        return f"Labels<{self._labels}>"

    @classmethod
    def empty(cls) -> "Labels":
        return Labels({})

    @classmethod
    def generate_default_labels(
        cls,
        resource_name: str,
        resource_kind: str,
        kaspr_component_name: str,
        kaspr_component_type,
        managed_by: str,
    ) -> "Labels":
        labels = Labels()
        return (
            labels.include_kaspr_kind(resource_kind)
            .include_kaspr_name(kaspr_component_name)
            .include_kaspr_cluster(resource_name)
            .include_kaspr_component_type(kaspr_component_type)
            .include_kubernetes_name(kaspr_component_type)
            .include_kubernetes_instance(resource_name)
            .include_kubernetes_part_of(resource_name)
            .include_kubernetes_managed_by(managed_by)
        )
