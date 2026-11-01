# SPDX-License-Identifier: GPL-2.0
"""Data models validated from type annotations, in Python with no compiled code.

Espalier implements the part of the pydantic 2 API that typed
configuration and wire formats need: BaseModel, Field, ConfigDict,
validators, serializers, computed fields and TypeAdapter. Code written
against that part runs with ``from espalier import ...`` in place of
``from pydantic import ...``. Models and adapters also read and write
YAML and XML.
"""

from .alias_generators import to_camel, to_pascal, to_snake
from .config import ConfigDict
from .errors import ValidationError
from .fields import Field, FieldInfo, computed_field
from .functional import (
    AfterValidator,
    BeforeValidator,
    ModelWrapValidatorHandler,
    PlainSerializer,
    PlainValidator,
    SerializationInfo,
    ValidationInfo,
    field_validator,
    model_validator,
)
from .main import BaseModel
from .type_adapter import TypeAdapter

__version__ = "1.1.0"

__all__ = [
    "AfterValidator",
    "BaseModel",
    "BeforeValidator",
    "ConfigDict",
    "Field",
    "FieldInfo",
    "ModelWrapValidatorHandler",
    "PlainSerializer",
    "PlainValidator",
    "SerializationInfo",
    "TypeAdapter",
    "ValidationError",
    "ValidationInfo",
    "__version__",
    "computed_field",
    "field_validator",
    "model_validator",
    "to_camel",
    "to_pascal",
    "to_snake",
]
