from typing import (
    Any,
    Callable,
    Generic,
    Optional,
    Type,
    TypeVar,
    cast,
)

RT = TypeVar("RT")

class cached_property(Generic[RT]):
    """Cached property.

    A property descriptor that caches the return value
    of the get function.

    Examples:
        .. sourcecode:: python

            @cached_property
            def connection(self):
                return Connection()

            @connection.setter  # Prepares stored value
            def connection(self, value):
                if value is None:
                    raise TypeError('Connection must be a connection')
                return value

            @connection.deleter
            def connection(self, value):
                # Additional action to do at del(self.attr)
                if value is not None:
                    print(f'Connection {value!r} deleted')
    """

    def __init__(
        self,
        fget: Callable[[Any], RT],
        fset: Callable[[Any, RT], RT] = None,
        fdel: Callable[[Any, RT], None] = None,
        doc: str = None,
        class_attribute: str = None,
    ) -> None:
        self.__get: Callable[[Any], RT] = fget
        self.__set: Optional[Callable[[Any, RT], RT]] = fset
        self.__del: Optional[Callable[[Any, RT], None]] = fdel
        self.__doc__ = doc or fget.__doc__
        self.__name__ = fget.__name__
        self.__module__ = fget.__module__
        self.class_attribute: Optional[str] = class_attribute

    def is_set(self, obj: Any) -> bool:
        return self.__name__ in obj.__dict__

    def __get__(self, obj: Any, type: Type = None) -> RT:
        if obj is None:
            if type is not None and self.class_attribute:
                return cast(RT, getattr(type, self.class_attribute))
            return cast(RT, self)  # just have to cast this :-(
        try:
            return cast(RT, obj.__dict__[self.__name__])
        except KeyError:
            value = obj.__dict__[self.__name__] = self.__get(obj)
            return value

    def __set__(self, obj: Any, value: RT) -> None:
        if self.__set is not None:
            value = self.__set(obj, value)
        obj.__dict__[self.__name__] = value

    def __delete__(self, obj: Any, _sentinel: Any = object()) -> None:
        value = obj.__dict__.pop(self.__name__, _sentinel)
        if self.__del is not None and value is not _sentinel:
            self.__del(obj, value)

    def setter(self, fset: Callable[[Any, RT], RT]) -> "cached_property":
        return self.__class__(self.__get, fset, self.__del)

    def deleter(self, fdel: Callable[[Any, RT], None]) -> "cached_property":
        return self.__class__(self.__get, self.__set, fdel)