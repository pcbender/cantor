# Canto v1.1 Capability Manifest

A capability manifest describes the contents and metadata of a reusable Canto
capability package. It is the package-level description for existing Canto
skills, providers, tools, dependencies, risk metadata, and expected artifacts.

The manifest model does not replace or change the existing skill, provider,
tool, registry, job, policy, or approval models.

## Required fields

- `name`: Package name. It must begin with a lowercase letter and contain only
  lowercase letters, digits, underscores, or hyphens. Separators cannot be
  repeated or appear at the end.
- `version`: Package version in `MAJOR.MINOR.PATCH` format, such as `1.0.0`.
  Prerelease and build suffixes are not currently accepted.

## Optional fields

- `description`: Human-readable package description. Defaults to an empty
  string.
- `skills`: List of included skill names. Defaults to an empty list.
- `providers`: List of included provider identifiers. Defaults to an empty
  list.
- `tools`: List of included tool names. Defaults to an empty list.
- `intents`: List of goal-oriented intent names used for deterministic local
  discovery, such as `import_site`. Defaults to an empty list.
- `inputs`: List of logical values or artifact names required by orchestration,
  such as `website_url` or `inventory.json`. Defaults to an empty list.
- `outputs`: List of logical artifact names produced for orchestration, such as
  `inventory.json`. Defaults to an empty list.
- `dependencies`: Mapping of dependency groups to lists. Defaults to an empty
  mapping. When `dependencies.python` is present, it must be a list.
- `risk`: Risk metadata. `risk.level` accepts `low`, `medium`, or `high` and
  defaults to `low`. `risk.requires_approval` defaults to `false`.
- `artifacts`: List of artifact names associated with the capability. Defaults
  to an empty list.
- `execution`: Explicit bindings from the package to runnable providers. It is
  optional for backward compatibility. `execution.providers` is a list whose
  entries require `skill` and `provider`. Optional `consumes` and `produces`
  fields are string mappings between provider names and logical artifact names.
  In `consumes`, the key is the provider input and the value is the required
  logical artifact. In `produces`, the key is the provider output and the value
  is the logical artifact made available to later steps. Bindings are explicit;
  Canto does not guess or transform unclear mappings.

Unknown top-level fields are allowed for forward compatibility. Validation
reports them as warnings, and warnings do not make a manifest invalid.

## Example

```yaml
name: source_inventory
version: 1.0.0
description: Inventory a website and produce migration planning artifacts.
skills:
  - source_inventory
providers:
  - source_inventory.public_html_crawler
tools: []
dependencies:
  python:
    - requests
    - beautifulsoup4
risk:
  level: low
  requires_approval: false
artifacts:
  - inventory.json
  - report.md
execution:
  providers:
    - skill: source_inventory
      provider: public_html_crawler
      consumes:
        website_url: website_url
      produces:
        inventory_path: inventory.json
```

The same example is maintained as
`tests/fixtures/capabilities/full_valid.yaml`.

## Validation

Validate a local manifest with:

```bash
canto capability validate path/to/canto.yaml
```

A valid manifest exits with status `0`. Validation errors are printed and exit
with a nonzero status. Warnings are printed but retain a successful exit
status.

The validator checks YAML syntax, required fields, package name and version
formats, list-valued fields, Python dependency shape, risk level, and explicit
execution provider binding structure.

## Current non-goals

Canto v1.1 manifest validation does not:

- Resolve or install declared dependencies.
- Fetch packages or metadata from a remote registry.
- Sign packages or establish publisher identity.
- Update or downgrade an existing installed capability version.

Local capability directories can be packed into `.canto` archives, validated,
installed, inspected, exported, and exposed to runtime discovery. Remote
distribution and dependency resolution remain future work.
