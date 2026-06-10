# Orchestration Contract Compatibility

Canto orchestration contract v1.0 uses the `contract_version` response field.
The contract version is independent of the Canto application version and
capability package versions.

## Minor-Compatible Changes

The following changes are additive and minor-compatible when existing behavior
is preserved:

- Adding optional response fields.
- Adding optional request fields with backward-compatible defaults.
- Adding new endpoints.
- Adding new event types that clients are not required to handle specially.
- Adding new JSON Schema definitions without changing existing definitions.
- Adding optional capability manifest fields under the existing
  forward-compatible manifest policy.

Clients must ignore response fields they do not recognize.

## Major Breaking Changes

The following changes require a major `contract_version` bump:

- Removing or renaming an endpoint, request field, or response field.
- Changing a field's type or meaning incompatibly.
- Making an optional request field required.
- Removing or renaming a status value.
- Changing status transition semantics incompatibly.
- Replacing `202 + poll` plan execution with a different completion model.
- Changing canonical execution identity away from `(skill, provider)`.
- Replacing the persisted `Approval` object with another approval contract.

Adding a new status enum value is treated as breaking unless the affected field
is explicitly documented as open-ended. The frozen plan status enum is closed.

## Published Artifacts

`docs/openapi.json` and the files under `docs/schemas/` are contract artifacts.
Changes to them must follow this policy. Synchronization tests ensure generated
artifacts match the implementation; review determines whether a change is
minor-compatible or requires a major version.

## Deprecation

A field or endpoint may be marked deprecated in a minor release, but it remains
supported for the rest of the current major contract version. Removal occurs
only with a major `contract_version` bump.
