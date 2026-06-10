# Canto v2.2 Release Notes

Canto v2.2 freezes orchestration contract v1.0 after completing the local
capability package lifecycle and registry unification work.

## Highlights

- Deterministic `.canto` archive creation, validation, installation, export,
  inspection, and removal.
- Local capability registry with checksum validation and lazy runtime refresh.
- Capability manifests with intent metadata and explicit `(skill, provider)`
  execution bindings.
- Deterministic local discovery, workflow planning, explanation, approvals, and
  sequential execution through `JobService`.
- Unified HTTP and CLI visibility for installed capabilities.
- HTTP orchestration loop:
  `discover → plan → approve → execute → observe/explain`.
- `202 Accepted` plus polling semantics for plan execution.
- One persisted `Approval` model shared by jobs and plans.
- Checked-in OpenAPI and JSON Schema contract artifacts with drift tests.

## Contract

Orchestration contract v1.0 is frozen subject to the deferred items documented
in `docs/contract-freeze-audit.md`. Compatibility rules are defined in
`docs/contract-compatibility.md`.

The canonical execution identity is `(skill, provider)`.
`capability@version` remains the package and provenance identity.

## Verification

The v2.2 merge was verified with:

```bash
.venv/bin/pytest tests import_capability/tests
```

Result: `159 passed`, with one existing Starlette `TestClient` deprecation
warning.

The checked-in release demonstration is available at:

```bash
./scripts/demo-v2.2.sh
```

It uses an isolated temporary capability registry and in-memory job state. The
verified flow covers pack, validation, installation, discovery, planning,
approval, `JobService` execution, explanation, export, and artifact validation.

## Deferred

This release does not add remote registries, AI generation, package signing,
automatic dependency solving, webhooks, full authentication, credential
handling, or target-system writes.
