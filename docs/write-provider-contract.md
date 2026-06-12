# Write-Provider Contract

Publicly, a governed write is a Run that produces an exact reviewable Result.
The Developer authorizes applying that Result to the named target; Canto then
performs the qualified Apply action after verification. This document retains
the precise Provider, Job, Artifact, and promotion terms required by the
implementation contract.

Write-capable providers remain ordinary Canto providers identified by
`(skill, provider)`. They add a `write` mapping that declares:

- `modes`: both `dry_run` and `live`.
- `target.scope` and the declared input that supplies target identity.
- Any declared credential-reference inputs.
- Change-set, validation, verification, and recovery output bindings.
- A required idempotency-key input.
- Recovery mode: `rollback`, `compensate`, or `manual`.
- Explicit `production_access` and `destructive` permissions.

The built-in `managed_json.local_document` provider is the MVP reference. A
dry run reads a local JSON document and creates a deterministic change set
without mutating the target.

`canto promote JOB_ID` creates a pending Approval bound to the dry-run artifact
checksum, provider provenance, target identity, credential references, and
input checksum. Approving that existing Approval revalidates the snapshot and
creates a live Job through `JobService`. Direct live write jobs and stale or
tampered promotions are rejected. The HTTP equivalent is
`POST /jobs/{job_id}/promote`.

Live jobs atomically claim the provider's idempotency key. A repeated request
for the same reviewed change set returns the prior result without invoking the
provider; reuse for a different change set fails. Failed claims may be retried.

`canto recover JOB_ID` creates another Approval from the live job's recovery
artifact. After approval, rollback or compensation runs through the same
provider and `JobService` path. The HTTP equivalent is
`POST /jobs/{job_id}/recover`.

Validation and verification artifacts are enforced by `JobService`. Promotion
binds the dry-run validation checksum, pre-write validation must still pass,
and a live or recovery job cannot complete unless post-write verification has
status `passed` and the expected recovery artifact is present. The reference
provider also rejects a live write when target state differs from the reviewed
dry-run `before` value.
