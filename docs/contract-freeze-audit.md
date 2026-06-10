# Orchestration Contract Freeze Audit

This audit records gaps that remain after the orchestration contract v1.0
freeze. Implemented freeze work is represented by `docs/openapi.json`, the JSON
Schemas under `docs/schemas/`, and the HTTP contract integration tests.

## Deferred Wire-Shape Gaps

- Plan responses retain the backward-compatible internal `candidate` envelope
  and compatibility maps instead of flattening `goal` and `steps` exactly as
  shown in the narrative contract examples.
- Workflow steps do not expose a response-only numeric `index` or inline risk;
  order supplies the index and risk is available through plan explanation.
- Approval links are exposed as `step_approval_ids` rather than the narrative
  contract's expanded `approvals` list.
- A goal with no match produces a persisted empty draft plan. It does not yet
  return the proposed `missing_capability` response and submittable suggested
  action.
- Plan failures persist a string `error`; the proposed structured
  `{code, message, step_index}` error object is deferred.

These shapes are frozen by the checked-in OpenAPI document. Changing them must
follow `docs/contract-compatibility.md`.

## Deferred Lifecycle Features

- `cancelled` is reserved as a terminal status, but no cancellation endpoint or
  cancellation operation is implemented.
- The event endpoint returns a pollable JSON event collection. Server-Sent
  Events are deferred and may be added only as an additive representation.
- Plan listing through optional `GET /plans` is not implemented.

## Deferred Manifest Versioning

- Capability manifests have a package `version` but no manifest
  `schema_version`. The generated capability manifest JSON Schema is the current
  machine-readable definition.

## Deferred Authentication

- Bearer authentication is reserved but not enforced.
- Non-loopback binding does not automatically require authorization.
- `requested_by` and `approved_by` remain caller-supplied audit labels rather
  than server-derived authenticated identities.

The current unauthenticated API is intended for trusted loopback use only. See
`docs/auth-placeholder.md`.

## Out of Scope

Remote registries, AI generation, package signing, dependency solving,
webhooks, and full authentication are not part of orchestration contract v1.0.
