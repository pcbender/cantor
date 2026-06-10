# Current Sprint — MVP v1 (Single-User, Write-Capable)

## Sprint Goal

Deliver the foundation of the first genuinely usable release: move the system of record off
Redis onto an embedded SQL store, then build guarded single-user target-system writes on top of
it. The tier's exit is a single developer performing a real, reversible, audited write to a
target system, locally, with no networked multi-user surface.

Start with the state store (`CP-5002`) — it underpins durability and the audit trail that every
later packet assumes, has no upstream dependencies, and removes the Redis-daemon setup friction
from local development immediately.

## Architecture Rule

Do not break the frozen orchestration contract. The new state store lands behind the existing
`StateStore` Protocol (no contract change); `PlanStore` folds into that store as server-owned
state. Writes are always guarded — dry-run → live promotion, explicit approval, idempotency,
and a rollback path. The locked model (Skill, Provider, Tool, Artifact, Job, Approval, Registry,
Policy, Capability package, Execution plan, Orchestration contract) stays intact. See
`docs/adr-state-store.md`.

## Tasks (MVP v1 core)

| ID | Status | Task |
| --- | --- | --- |
| CP-5001 | READY | MVP v1 scope and design. |
| CP-5002 | BLOCKED | `SqliteStateStore` as system of record (behind the `StateStore` Protocol; covers jobs, events, approvals, artifact metadata, registry snapshot, plans). Depends on CP-5001. |
| CP-5003 | BLOCKED | Redis → SQLite state-migration tool. Depends on CP-5002. |
| CP-5004 | BLOCKED | Single-user credential vault and vault-backed `*_ref` resolution. Depends on CP-5002. |
| CP-5005 | BLOCKED | Secret rotation and redaction guarantees. Depends on CP-5004. |
| CP-5006 | BLOCKED | Guarded write execution path (dry-run → live promotion). Depends on CP-5004. |
| CP-5007 | BLOCKED | Idempotency and rollback / compensation. Depends on CP-5006. |
| CP-5008 | BLOCKED | Write-provider contract and reference write-capable provider. Depends on CP-5006. |
| CP-5009 | BLOCKED | Pre-write validation and post-write verification artifacts. Depends on CP-5006. |
| CP-5010 | BLOCKED | Multi-runtime provider execution (node / container / binary). Depends on CP-5001. |
| CP-5011 | BLOCKED | Baseline resource limits and per-job egress allowlist. Depends on CP-5001. |
| CP-5012 | BLOCKED | Local install / packaging and quickstart. Depends on CP-5002, CP-5006. |
| CP-5013 | BLOCKED | Seed trusted capability set, incl. one real write workflow. Depends on CP-5008, CP-5010. |
| CP-5014 | BLOCKED | MVP v1 stability, release notes, and documentation. Depends on all above. |

Developer-experience packets (CP-1201..CP-1210, formerly v3.2) are part of MVP v1 but a later
slice in this tier; they are not the immediate sprint focus.

## Definition of Done

- A single developer installs Canto locally, stores credentials in the vault, installs a trusted
  capability, approves a plan, and performs a real reversible guarded write to a target system —
  observed and audited.
- The SQL store is the system of record; existing Redis state migrates cleanly; no Redis daemon
  is required for local use.
- Existing tests still pass; new tests cover the state store (incl. CAS and ordered-append
  semantics), the credential vault, and guarded-write dry-run/rollback paths.
- No change to the frozen contract without an explicit `contract_version` bump.
- No multi-user, authentication, networked exposure, remote registry, or unattended writes.
