"""Maps of named settings whose values reach the app as strings.

Kafka topic configurations, a table's RocksDB options and HTTP response headers are each a map of
names to values the app passes on as text. A manifest may write a value unquoted -
`retention.ms: 86400000`, `preallocate: true` - and the CRDs keep it as YAML read it, so the value
is turned into the string Kafka itself would write here: `"86400000"`, `"true"`.
"""

from typing import Any

from marshmallow import ValidationError, fields


def setting_string(value: Any) -> str:
    """A setting's value as text: a string as it is, a boolean `true`/`false`, a number as written."""
    # A bool is an int too, and Kafka's booleans are lower case.
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)):
        return str(value)
    raise ValidationError(f"Not a string, number or boolean: {value!r}.")


class SettingValue(fields.Field):
    """One setting's value: a string, number or boolean, kept as its string."""

    def _deserialize(self, value: Any, attr: Any, data: Any, **kwargs: Any) -> str:
        return setting_string(value)

    def _serialize(self, value: Any, attr: Any, obj: Any, **kwargs: Any) -> Any:
        return None if value is None else setting_string(value)


def setting_map(data_key: str, **kwargs: Any) -> fields.Mapping:
    """A map of setting names to their values as strings, read from `data_key`."""
    return fields.Mapping(keys=fields.Str(required=True), values=SettingValue(required=True), data_key=data_key, **kwargs)
