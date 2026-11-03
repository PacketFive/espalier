# Changelog

All notable changes to pyrixos-espalier are listed here. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.1] - 2026-11-02

### Changed

- The package metadata names Weqaar Janjua as the author, with PacketFive
  as the maintainer.
- The quality gates run with coldframe from PyPI, the new name of
  pybootstrap, and read their settings from `[tool.coldframe]`.

## [1.1.0] - 2026-11-01

### Added

- YAML: `BaseModel.model_validate_yaml` and `model_dump_yaml`, and
  `TypeAdapter.validate_yaml` and `dump_yaml`. The reader takes one
  YAML 1.2 document of block and flow collections and plain, quoted and
  block scalars, resolves plain scalars with the core schema, and
  refuses anchors, aliases, tags and complex keys. The writer's output
  reads as the same data in YAML 1.1 readers such as PyYAML.
- XML: `BaseModel.model_validate_xml` and `model_dump_xml`, and
  `TypeAdapter.validate_xml` and `dump_xml`. Fields and keys are child
  elements and list members are `<item>` elements. The reader converts
  text by the annotated types and refuses document type declarations.
- The error types `yaml_invalid` and `xml_invalid`.

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
