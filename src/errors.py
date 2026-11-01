# SPDX-License-Identifier: GPL-2.0
"""The error a failed validation raises, and the internal form of its line errors."""

from __future__ import annotations

from typing import Any


class ValidationError(ValueError):
    """Input that does not validate against a model or type.

    ``errors()`` returns one dict per problem with the keys ``type``, a
    short machine name such as ``missing``; ``loc``, a tuple of field
    names and item indexes leading to the value; ``msg``, the message;
    and ``input``, the value that failed.
    """

    def __init__(self, title: str, line_errors: list[dict[str, Any]]) -> None:
        """Hold the errors ``line_errors`` found validating ``title``."""
        self.title = title
        self._errors = line_errors
        super().__init__(self._render())

    def errors(
        self, *, include_input: bool = True, include_context: bool = True
    ) -> list[dict[str, Any]]:
        """Return a list of the errors, as fresh dicts."""
        result = []
        for error in self._errors:
            item = dict(error)
            if not include_input:
                item.pop("input", None)
            if not include_context:
                item.pop("ctx", None)
            result.append(item)
        return result

    def error_count(self) -> int:
        """Return the number of errors."""
        return len(self._errors)

    def _render(self) -> str:
        count = len(self._errors)
        lines = [f"{count} validation error{'' if count == 1 else 's'} for {self.title}"]
        for error in self._errors:
            if error["loc"]:
                lines.append(".".join(str(part) for part in error["loc"]))
            value = error.get("input")
            shown = repr(value)
            if len(shown) > 100:
                shown = shown[:49] + "..." + shown[-48:]
            lines.append(
                f"  {error['msg']} [type={error['type']}, input_value={shown}, "
                f"input_type={type(value).__name__}]"
            )
        return "\n".join(lines)

    def __str__(self) -> str:
        """Return the errors as text, one per entry, each under its location."""
        return self._render()


class Invalid(Exception):  # noqa: N818
    """Raised inside validation with line errors whose ``loc`` is relative."""

    def __init__(self, errors: list[dict[str, Any]]) -> None:
        """Hold ``errors``."""
        super().__init__(errors)
        self.errors = errors

    def prefixed(self, *loc: str | int) -> list[dict[str, Any]]:
        """Return the errors with ``loc`` put in front of each location."""
        return [{**error, "loc": (*loc, *error["loc"])} for error in self.errors]


def invalid(kind: str, msg: str, value: object, **ctx: object) -> Invalid:
    """Return an Invalid with one error at the current location."""
    error: dict[str, Any] = {"type": kind, "loc": (), "msg": msg, "input": value}
    if ctx:
        error["ctx"] = ctx
    return Invalid([error])


def from_exception(error: Exception, value: object) -> Invalid:
    """Turn an exception a validator raised into line errors.

    A ValidationError keeps its errors. A ValueError becomes a
    ``value_error`` and an AssertionError an ``assertion_error``. Other
    exceptions are not caught by the callers, so they reach the program.
    """
    if isinstance(error, ValidationError):
        return Invalid(error.errors())
    if isinstance(error, AssertionError):
        return invalid("assertion_error", f"Assertion failed, {error}", value, error=error)
    return invalid("value_error", f"Value error, {error}", value, error=error)
