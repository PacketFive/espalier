# pyrixos-espalier

Data models validated from type annotations, in Python with no compiled
code and no dependencies. Espalier implements the part of the pydantic 2
API that typed configuration files and wire formats use, so code written
against that part runs with `from espalier import ...` in place of
`from pydantic import ...`.

PyrixOS uses it in Lattice, Cloche and Trellis, so that its build tools
install without Rust or C extensions.

```sh
pip install pyrixos-espalier
```

```python
from typing import Annotated, Literal

from espalier import BaseModel, ConfigDict, Field, ValidationError


class Mount(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    source: str = Field(min_length=1)
    target: str
    mode: Literal["ro", "rw"] = "ro"
    size: Annotated[int, Field(ge=0)] = 0


mount = Mount.model_validate_json('{"source": "/a", "target": "/b"}')
print(mount.model_dump_json())  # {"source":"/a","target":"/b","mode":"ro","size":0}

try:
    Mount(source="", target="/b", size=-1)
except ValidationError as error:
    print(error)
```

## What it supports

- `BaseModel` with `model_validate`, `model_validate_json`,
  `model_dump`, `model_dump_json`, `model_copy`, `model_construct`,
  `model_rebuild`, `model_fields`, `model_fields_set`, `model_extra`
  and `model_computed_fields`. Models compare equal by class and fields,
  frozen models hash, and models copy and pickle.
- `ConfigDict` keys `frozen`, `extra` (`ignore`, `forbid`, `allow`),
  `strict`, `alias_generator`, `populate_by_name`, `validate_by_name`,
  `validate_by_alias`, `serialize_by_alias`, `arbitrary_types_allowed`
  and `title`. A subclass's config is merged over its bases'.
- `Field` with defaults, default factories, aliases, `exclude`, `repr`,
  `strict`, `discriminator` and the constraints `gt`, `ge`, `lt`, `le`,
  `multiple_of`, `min_length`, `max_length` and `pattern`, as a default
  or inside `Annotated`.
- `field_validator` (`before`, `after`, `plain`), `model_validator`
  (`before`, `after`, `wrap`), `BeforeValidator`, `AfterValidator`,
  `PlainValidator`, `PlainSerializer` and `computed_field`. Validators
  may take a `ValidationInfo` with `mode`, `field_name` and `data`.
- `TypeAdapter` for any supported type, with `validate_python`,
  `validate_json`, `dump_python` and `dump_json`.
- The types `int`, `float`, `str`, `bool`, `bytes`, `None`, `Any`,
  enums, `Literal`, unions, `Optional`, discriminated unions,
  `datetime.datetime`, `datetime.date`, `pathlib` paths, `list`,
  `tuple` (fixed and variable length), `set`, `frozenset`, `dict`,
  `Mapping`, `type[...]`, `NewType`, `type` aliases, nested and
  recursive models and forward references. Other classes are checked
  with `isinstance`.
- Strict and lax modes with pydantic's conversion rules, including JSON
  input in strict mode giving lists for tuples and sets, and strings for
  enums and datetimes. `strict=` on a validate call replaces the
  `strict` of the model's config and of the models in it.
- `ValidationError`, a `ValueError`, with pydantic's error types,
  locations and messages and the same text layout.

## Differences from pydantic

- No JSON Schema generation, no `BaseSettings`, no dataclass support,
  no generic models, and no `context` passed to validators.
- The error for invalid JSON quotes Python's `json` module, and other
  parse errors (datetime, date) quote the standard library's message.
- Error text has no documentation link lines.
- A UTC datetime read from JSON has `datetime.timezone.utc` as tzinfo.
- An instance given where a model is expected is used as it is, not
  revalidated, as with pydantic's default `revalidate_instances`.
- Validation runs in Python. Validating or dumping a model is about 5
  to 7 times slower than with pydantic-core; for configuration files
  and protocol messages this is well under a millisecond each.

## Migrating from pydantic

Replace `pydantic` with `espalier` in imports, and
`pydantic.alias_generators` with `espalier.alias_generators`. Code that
sets `__pydantic_*__` attributes or calls pydantic-core directly needs
changes; Espalier never calls a nested model's `__init__`, so a model
that overrides `__init__` is validated by its outer model without it.

## Development

```sh
pip install --group dev
pip install -e .
pybootstrap check
```

The tests record the types and messages pydantic gives for the same
input.

## License

GPL-2.0-only. See [LICENSE](LICENSE).
