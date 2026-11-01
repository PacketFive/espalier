# SPDX-License-Identifier: GPL-2.0
"""Validators and serializers attached to types and models."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, Protocol


class ValidationInfo:
    """What a validator may know about the validation that calls it.

    ``mode`` is ``"python"`` or ``"json"``, ``field_name`` the field being
    validated or None, and ``data`` the fields of the model validated so
    far, by name. ``strict`` is the ``strict`` argument of the call that
    started the validation, None if it gave none.
    """

    __slots__ = ("context", "data", "field_name", "mode", "strict")

    def __init__(self, mode: Literal["python", "json"], strict: bool | None = None) -> None:
        """Start a validation in ``mode``."""
        self.mode: Literal["python", "json"] = mode
        self.strict = strict
        self.field_name: str | None = None
        self.data: dict[str, Any] = {}
        self.context: Any = None


class SerializationInfo:
    """What a serializer may know about the dump that calls it."""

    __slots__ = ("by_alias", "mode")

    def __init__(self, mode: Literal["python", "json"], by_alias: bool = False) -> None:
        """Start a dump in ``mode``."""
        self.mode = mode
        self.by_alias = by_alias

    def mode_is_json(self) -> bool:
        """Return whether the dump makes values for JSON."""
        return self.mode == "json"


class ModelWrapValidatorHandler[T](Protocol):
    """The callable a wrap model validator calls to validate as usual."""

    def __call__(self, value: Any, /) -> T:
        """Validate ``value`` and return the model."""
        ...


def wants_info(function: Callable[..., Any], fixed: int) -> bool:
    """Return whether ``function`` takes an info argument after ``fixed`` others."""
    try:
        parameters = inspect.signature(function).parameters.values()
    except (TypeError, ValueError):
        return False
    positional = [
        p
        for p in parameters
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD) and p.default is p.empty
    ]
    return len(positional) > fixed or any(p.kind == p.VAR_POSITIONAL for p in parameters)


@dataclass(frozen=True)
class AfterValidator:
    """In ``Annotated``, call ``func(value)`` or ``func(value, info)`` after type checks.

    A ValueError it raises becomes a validation error; its result
    replaces the value.
    """

    func: Callable[..., Any]


@dataclass(frozen=True)
class BeforeValidator:
    """In ``Annotated``, call ``func`` on the input before the type checks."""

    func: Callable[..., Any]


@dataclass(frozen=True)
class PlainValidator:
    """In ``Annotated``, call ``func`` instead of the type checks."""

    func: Callable[..., Any]


@dataclass(frozen=True)
class PlainSerializer:
    """In ``Annotated``, dump a field's value with ``func(value)`` or ``func(value, info)``."""

    func: Callable[..., Any]
    return_type: Any = None
    when_used: Literal["always", "json"] = "always"


class Decorated:
    """A validator method, marked for the model that defines it."""

    def __init__(self, function: Any, kind: str, mode: str, fields: tuple[str, ...]) -> None:
        """Mark ``function``, a function or classmethod."""
        self.function = function
        self.kind = kind
        self.mode = mode
        self.fields = fields

    def __get__(self, instance: object, owner: type | None = None) -> Any:
        """Behave as the method itself."""
        return self.function.__get__(instance, owner)

    def bound(self, owner: type) -> Callable[..., Any]:
        """Return the function bound to ``owner`` if it is a classmethod."""
        return self.function.__get__(None, owner)

    def raw(self) -> Callable[..., Any]:
        """Return the plain function under any classmethod."""
        return getattr(self.function, "__func__", self.function)


def field_validator(
    *fields: str, mode: Literal["after", "before", "plain"] = "after"
) -> Callable[[Any], Any]:
    """Run the decorated classmethod on the named fields after their type checks.

    It receives the value, and the ValidationInfo if it takes a second
    argument, and returns the value to keep.
    """
    if not fields or not all(isinstance(name, str) for name in fields):
        raise TypeError("field_validator takes the names of the fields it checks")

    def decorate(function: Any) -> Any:
        return Decorated(function, "field", mode, fields)

    return decorate


def model_validator(*, mode: Literal["after", "before", "wrap"]) -> Callable[[Any], Any]:
    """Run the decorated method on the whole model.

    ``after``: a method called with the new instance, which it returns.
    ``before``: a classmethod given the input, which it returns changed.
    ``wrap``: a classmethod given the input and a handler that validates
    it as usual and returns the instance.
    """

    def decorate(function: Any) -> Any:
        return Decorated(function, "model", mode, ())

    return decorate
