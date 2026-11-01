# pyrixos-espalier

Data models validated from type annotations, in Python with no compiled
code and no dependencies. Espalier implements the part of the pydantic 2
API that typed configuration files and wire formats use, so code written
against that part runs with `from espalier import ...` in place of
`from pydantic import ...`. Models also read and write YAML and XML, with
readers written for this package and the standard library's XML parser.

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
  `model_validate_yaml`, `model_validate_xml`, `model_dump`,
  `model_dump_json`, `model_dump_yaml`, `model_dump_xml`, `model_copy`,
  `model_construct`,
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
  `validate_json`, `validate_yaml`, `validate_xml`, `dump_python`,
  `dump_json`, `dump_yaml` and `dump_xml`.
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

## YAML

`model_validate_yaml` reads a YAML document and validates it as
`model_validate_json` validates JSON, so strict mode accepts the same
values. `model_dump_yaml` writes `model_dump(mode="json")` in block
style.

```python
class Host(BaseModel):
    name: str
    ports: list[int] = []


host = Host.model_validate_yaml("""
name: web
ports: [80, 443]
""")
print(host.model_dump_yaml(), end="")
# name: web
# ports:
#   - 80
#   - 443
```

The reader takes the part of YAML 1.2 that data files use: block and
flow mappings and sequences, plain, single-quoted and double-quoted
scalars, literal and folded block scalars, comments, explicit `? key`
entries with scalar keys, and one document with optional `---`, `...`
and `%YAML` lines. Plain scalars follow the YAML 1.2 core schema, so
`yes`, `on` and `2024-01-02` are strings, not booleans or dates, and
mapping keys stay strings as in JSON.

It refuses anchors and aliases, tags, collections as keys, duplicate
keys, tabs used for indentation and more than one document, giving the
line of the problem. A document therefore holds the same data for every
reader, and cannot expand into more data than its own size.

The writer quotes strings that other readers, YAML 1.1 ones included,
would take for another type, and writes floats with a decimal point, so
PyYAML reads its output as the same data.

## XML

`model_dump_xml` writes the model as an element named after its class,
or `root=`, with a child element for each field. `model_validate_xml`
reads that layout back, using the field types to turn text into
numbers, booleans, lists and mappings.

```python
print(host.model_dump_xml(indent=2), end="")
# <Host>
#   <name>web</name>
#   <ports>
#     <item>80</item>
#     <item>443</item>
#   </ports>
# </Host>
assert Host.model_validate_xml(host.model_dump_xml()) == host
```

The layout:

| Value | XML |
| ----- | --- |
| Model or mapping | One child element per key, named after the key |
| Key that is not an XML name, or `item`, `entry` or `xml...` | `<entry key="...">` |
| List, tuple or set | One `<item>` child per member |
| None | `<name nil="true" />` |
| Empty string, list or mapping | `<name />` |
| `True`, `False` | `true`, `false` |
| Infinity, NaN | `inf`, `-inf`, `nan` |

The reader takes the type of each element from the annotation, and
ignores the name of the root element and of list members. Under `Any`,
elements with only `<item>` children become lists, other elements with
children become mappings, and text stays a string. A union of scalar
types tries its members in order, so `int | str` reads `1` as an
integer and `str | int` reads it as a string.

The reader refuses document type declarations, which also rules out
entity expansion and external entities, and text mixed with child
elements. The writer refuses characters XML 1.0 cannot hold, such as
most control characters, and escapes carriage returns so they read
back unchanged.

## Differences from pydantic

- No JSON Schema generation, no `BaseSettings`, no dataclass support,
  no generic models, and no `context` passed to validators.
- The YAML and XML methods are Espalier's own; pydantic has none. Their
  invalid-input errors have the types `yaml_invalid` and `xml_invalid`.
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
