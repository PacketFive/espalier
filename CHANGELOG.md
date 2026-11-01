# Changelog

All notable changes to pyrixos-espalier are listed here. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-11-01

### Added

- `BaseModel`, `ConfigDict`, `Field`, `FieldInfo`, `computed_field`,
  `field_validator`, `model_validator`, the `Annotated` validators and
  `PlainSerializer`, `TypeAdapter`, `ValidationError` and the alias
  generators `to_camel`, `to_pascal` and `to_snake`: the part of the
  pydantic 2 API that Lattice, Cloche and Trellis use, in Python with
  no compiled code.
- Strict and lax validation with pydantic's conversion rules, error
  types, locations and messages, checked against pydantic on the same
  input.
