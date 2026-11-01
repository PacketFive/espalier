# SPDX-License-Identifier: GPL-2.0
"""Model configuration."""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal, TypedDict


class ConfigDict(TypedDict, total=False):
    """The settings of a model, given as its ``model_config`` class attribute.

    A subclass's settings are merged over those of its bases.

    ``frozen``: instances refuse attribute assignment and are hashable.
    ``extra``: what happens to input keys that are not fields;
    ``"ignore"`` (the default) drops them, ``"forbid"`` refuses them and
    ``"allow"`` keeps them as attributes.
    ``strict``: no conversion between types, so ``"1"`` is not an int
    and, from Python, a list is not a tuple. Input decoded from JSON may
    still give a list for a tuple, a string for an enum or a datetime.
    ``arbitrary_types_allowed``: fields of other classes are checked with
    ``isinstance``. Espalier always does this; the key is accepted so
    configurations written for pydantic keep working.
    ``alias_generator``: makes the alias of every field without one.
    ``populate_by_name`` and ``validate_by_name``: a field with an alias
    may also be given by its name. ``validate_by_alias`` (default True):
    a field may be given by its alias. ``serialize_by_alias``: dumps use
    aliases unless ``by_alias=False`` is passed.
    """

    frozen: bool
    extra: Literal["ignore", "forbid", "allow"]
    strict: bool
    arbitrary_types_allowed: bool
    alias_generator: Callable[[str], str] | None
    populate_by_name: bool
    validate_by_name: bool
    validate_by_alias: bool
    serialize_by_alias: bool
    title: str
