# SPDX-License-Identifier: GPL-2.0
"""Field descriptions and computed fields."""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any


class _Missing:
    __slots__ = ()

    def __repr__(self) -> str:
        return "MISSING"

    def __reduce__(self) -> str:
        return "MISSING"


MISSING: Any = _Missing()
"""The default of a field that has none, so the field is required."""

CONSTRAINTS = ("gt", "ge", "lt", "le", "multiple_of", "min_length", "max_length", "pattern")


class FieldInfo:
    """What Field() returned, merged with the field's annotation.

    ``annotation`` is the field's type once the model is set up.
    """

    __slots__ = (
        "alias",
        "annotation",
        "default",
        "default_factory",
        "description",
        "discriminator",
        "exclude",
        "gt",
        "ge",
        "le",
        "lt",
        "max_length",
        "min_length",
        "multiple_of",
        "pattern",
        "repr",
        "serialization_alias",
        "strict",
        "title",
        "validation_alias",
    )

    def __init__(self, **kwargs: Any) -> None:
        """Hold the keyword arguments of Field(); every other attribute is None."""
        for name in self.__slots__:
            setattr(self, name, None)
        self.default = MISSING
        self.repr = True
        self.annotation = None
        for name, value in kwargs.items():
            setattr(self, name, value)

    def merge(self, other: FieldInfo) -> FieldInfo:
        """Return a FieldInfo with the attributes ``other`` sets laid over these."""
        merged = FieldInfo()
        for name in self.__slots__:
            setattr(merged, name, getattr(self, name))
        for name in self.__slots__:
            value = getattr(other, name)
            if name == "default":
                if value is not MISSING:
                    merged.default = value
            elif name == "repr":
                merged.repr = merged.repr and value
            elif value is not None:
                setattr(merged, name, value)
        return merged

    def constraints(self) -> dict[str, Any]:
        """Return the value constraints that are set, such as ``ge``."""
        return {
            name: getattr(self, name) for name in CONSTRAINTS if getattr(self, name) is not None
        }

    def is_required(self) -> bool:
        """Return whether the field has neither a default nor a default factory."""
        return self.default is MISSING and self.default_factory is None

    def get_default(self) -> Any:
        """Return the default, a fresh copy if it is mutable."""
        if self.default_factory is not None:
            return self.default_factory()
        value = self.default
        try:
            hash(value)
        except TypeError:
            return copy.deepcopy(value)
        return value

    def __repr__(self) -> str:
        """Show the attributes that are set."""
        shown = ", ".join(
            f"{name}={getattr(self, name)!r}"
            for name in self.__slots__
            if getattr(self, name) not in (None, MISSING) and name != "repr"
        )
        return f"FieldInfo({shown})"


def Field(  # noqa: N802
    default: Any = MISSING,
    *,
    default_factory: Callable[[], Any] | None = None,
    alias: str | None = None,
    validation_alias: str | None = None,
    serialization_alias: str | None = None,
    title: str | None = None,
    description: str | None = None,
    discriminator: str | None = None,
    exclude: bool | None = None,
    repr: bool = True,  # noqa: A002
    strict: bool | None = None,
    gt: float | None = None,
    ge: float | None = None,
    lt: float | None = None,
    le: float | None = None,
    multiple_of: float | None = None,
    min_length: int | None = None,
    max_length: int | None = None,
    pattern: str | None = None,
) -> Any:
    """Describe a field: its default, alias and constraints.

    Use it as the default of a field, ``size: int = Field(ge=0)``, or in
    its annotation, ``Annotated[int, Field(ge=0)]``. ``gt``, ``ge``,
    ``lt`` and ``le`` bound numbers; ``min_length`` and ``max_length``
    bound strings and collections; ``pattern`` is a regular expression a
    string must contain a match of. ``discriminator`` names the field
    whose value picks the member of a union of models.
    """
    if default is not MISSING and default_factory is not None:
        raise TypeError("cannot give both default and default_factory")
    return FieldInfo(
        default=default,
        default_factory=default_factory,
        alias=alias,
        validation_alias=validation_alias,
        serialization_alias=serialization_alias,
        title=title,
        description=description,
        discriminator=discriminator,
        exclude=exclude,
        repr=repr,
        strict=strict,
        gt=gt,
        ge=ge,
        lt=lt,
        le=le,
        multiple_of=multiple_of,
        min_length=min_length,
        max_length=max_length,
        pattern=pattern,
    )


class ComputedField:
    """A property or cached_property whose value model dumps include."""

    def __init__(self, wrapped: Any) -> None:
        """Wrap the descriptor ``wrapped``."""
        self.wrapped = wrapped
        self.__doc__ = getattr(wrapped, "__doc__", None)

    def __set_name__(self, owner: type, name: str) -> None:
        """Pass the name to the wrapped descriptor, which cached_property needs."""
        self.name = name
        set_name = getattr(self.wrapped, "__set_name__", None)
        if set_name is not None:
            set_name(owner, name)

    def __get__(self, instance: object, owner: type | None = None) -> Any:
        """Return the wrapped descriptor's value."""
        if instance is None:
            return self
        return self.wrapped.__get__(instance, owner)


def computed_field[T](function: T) -> T:
    """Include a property or cached_property in model dumps, after the fields."""
    return ComputedField(function)  # type: ignore[return-value]
