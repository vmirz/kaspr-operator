from types import SimpleNamespace
from typing import Any, Dict, Mapping, Optional
from marshmallow import INCLUDE, EXCLUDE, Schema, post_load

EXCLUDE = EXCLUDE
JSON = Dict[str, Any]
MAX_REPR_LEN = 50

def _process_dict_values(model: Any, key: str, value: Any) -> Any:
    """Process a returned from a JSON response.
    Args:
        value: A dict, list, or value returned from a JSON response.
    Returns:
        Either an UnknownModel, a List of processed values, or the original value \
            passed through.
    """
    if isinstance(value, list):
        return [_process_dict_values(model, key, v) for v in value]
    else:
        return value

class BaseModel(SimpleNamespace):
    """BaseModel that all models should inherit from.
    Note:
        If a passed parameter is a nested dictionary, then it is created with the
        `UnknownModel` class. If it is a list, then it is created with
    Args:
        **kwargs: All passed parameters as converted to instance attributes.
    """

    __related__: Mapping = dict()

    def __init__(self, **kwargs: Any) -> None:
        kwargs = {k: _process_dict_values(self, k, v) for k, v in kwargs.items()}

        self.__dict__.update(kwargs)

    def __repr__(self) -> str:
        """Return a default repr of any Model.
        Returns:
            The string model parameters up to a `MAX_REPR_LEN`.
        """
        repr_ = super().__repr__()
        if len(repr_) > MAX_REPR_LEN:
            return repr_[:MAX_REPR_LEN] + " ...)"
        else:
            return repr_
        
    def as_dict(self) -> Dict[str, Any]:
        result = {}
        for key, value in self.__dict__.items():
            if isinstance(value, BaseModel):
                result[key] = value.as_dict()
            elif isinstance(value, list):
                result[key] = [
                    item.as_dict() if isinstance(item, BaseModel) else item
                    for item in value
                ]
            else:
                result[key] = value
        return result   

class UnknownModel(BaseModel):
    """A convenience class that inherits from `BaseModel`."""

    def keys(self):
        return self.__dict__.keys()
    
    def values(self):
        return self.__dict__.values()

    def items(self):
        return self.__dict__.items()

class BaseSchema(Schema):
    """The default schema for all models."""

    __model__: Any = UnknownModel
    """Determine the object that is created when the load method is called."""
    __first__: Optional[str] = None
    """Determine if `make_object` will try to get the first element the input key."""

    class Meta:
        unknown = INCLUDE
        ordered = True   

    @post_load
    def make_object(self, data: JSON, **kwargs: Any) -> "__model__":
        """Build model for the given `__model__` class attribute.
        Args:
            data: The JSON diction to use to build the model.
            **kwargs: Unused but required to match signature of `Schema.make_object`
        Returns:
            An instance of the `__model__` class.
        """
        if self.__first__ is not None:
            data_list = data.get("objects", [{}])
            # guard against empty return list of a valid results return
            data = data_list[0] if len(data_list) != 0 else {}
        return self.__model__(**data)
