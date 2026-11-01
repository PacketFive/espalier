# SPDX-License-Identifier: GPL-2.0
"""Making aliases from field names."""

from __future__ import annotations

import re


def to_pascal(snake: str) -> str:
    """Return ``snake_case`` as ``SnakeCase``."""
    camel = snake.title()
    return re.sub(r"([0-9A-Za-z])_(?=[0-9A-Z])", lambda match: match.group(1), camel)


def to_camel(snake: str) -> str:
    """Return ``snake_case`` as ``snakeCase``; a name already in that form is kept."""
    if re.match(r"^[a-z]+[A-Za-z0-9]*$", snake) and not re.search(r"\d[a-z]", snake):
        return snake
    camel = to_pascal(snake)
    return re.sub(r"(^_*[A-Z])", lambda match: match.group(1).lower(), camel)


def to_snake(camel: str) -> str:
    """Return ``camelCase`` or ``PascalCase`` as ``camel_case``."""
    snake = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", camel)
    snake = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", snake)
    return snake.replace("-", "_").lower()
