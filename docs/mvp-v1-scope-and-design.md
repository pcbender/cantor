# MVP v1 Scope and Design

Status: Approved and complete
Work packet: CP-5001
Tier: Single-user, write-capable local release

## Purpose

MVP v1 turns the current local capability runtime into a durable, installable,
single-user product that can perform explicitly approved, reversible writes to
one target system.

This tier does not redesign Canto. It extends the locked skill, provider, tool,
artifact, job, approval, registry, policy, capability package, execution plan,
and orchestration contract models.

## Release Outcome

A developer can:

1. Install Canto locally without running Redis.
2. Store a target credential in a local credential vault.
3. Install a trusted local capability package.
4. Discover and plan a write workflow.
5. Execute a dry run that produces a reviewable change set.
6. Approve promotion of that exact change set to live execution.
7. Perform an idempotent target-system write.
8. Verify the resulting target state.
9. Roll back or compensate for the write when supported.
10. Inspect the durable plan, jobs, approvals, events, and artifacts after a
    restart.

## Scope

### Durable local state

`SqliteStateStore` becomes the default system of record behind the existing
`StateStore` boundary.

It owns durable records for:

- Jobs and status transitions.
- Ordered job and plan events.
- Approval objects and atomic decisions.
- Artifact metadata. Artifact files remain on the filesystem.
- Registry snapshots.
- Execution plans, including plan inputs, step jobs, approval links, events,
  errors, and produced artifact paths.

`PlanStore` is folded into the state-store boundary. Filesystem plan JSON is a
legacy source for migration, not a second durable store.

The default database location is under the local Canto home, with the final
path and configuration defined by CP-5002. SQLite must use transactions,
foreign keys, deterministic migrations, and compare-and-set updates equivalent
to the current job and approval transition behavior.

Redis remains supported only as a legacy or optional adjunct. MVP v1 does not
require Redis for installation, startup, orchestration, or execution.

### State migration

CP-5003 provides a one-time, explicit migration from current local sources:

- Redis jobs, events, approvals, artifacts, and registry snapshot.
- Filesystem execution plans.

Migration must be resumable or safely repeatable, report imported/skipped
records, and preserve identifiers and timestamps. It must not delete source
state automatically.

### Credential vault

Sensitive provider inputs continue to use `*_ref` fields. MVP v1 extends the
reference scheme from `env:NAME` to a vault-backed form selected in CP-5004.

The vault is single-user and local. It must provide:

- Named, scoped secret records.
- Least-privilege filesystem permissions.
- Secret replacement and rotation without changing capability manifests.
- Resolution immediately before provider launch.
- No plaintext secret persistence in jobs, plans, events, artifacts, logs, or
  provider request files.
- Redaction of known secret values and references from provider output and
  error details.

The cryptographic backend and local key-custody mechanism are decisions for
CP-5004. CP-5001 does not claim that filesystem permissions alone constitute
encryption at rest.

### Guarded write execution

Write-capable providers use the existing `(skill, provider)` execution
identity, `JobService`, policy evaluation, runner boundary, approvals, and
artifact collection.

A write workflow has two distinct stages:

1. **Dry run:** reads source and target state as permitted, performs no target
   mutation, and produces a deterministic proposed-change artifact.
2. **Live promotion:** applies the reviewed change set only after an explicit
   approval tied to the plan, step, target, and dry-run artifact checksum.

Live promotion must reject execution when:

- The dry-run artifact is missing or changed.
- The capability package version or checksum changed after review.
- The resolved `(skill, provider)` changed.
- The target identity or credential reference changed.
- Required approval is absent, pending, or rejected.
- Pre-write validation fails.
- The provider does not declare the required write permissions.

The live job produces post-write verification and rollback/compensation
artifacts. A successful process exit without verification is not sufficient to
mark the write workflow complete.

### Idempotency and recovery

Every live write request carries an idempotency key bound to the approved
change set. Repeating the same request must return the prior result or prove
that no additional mutation occurred.

Write providers declare one recovery mode:

- `rollback`: restore captured prior state.
- `compensate`: apply an explicit compensating operation.
- `manual`: produce complete recovery instructions when automatic recovery is
  not technically possible.

MVP v1 release acceptance requires the reference provider to support automatic
rollback or compensation. `manual` is allowed for future providers but does not
satisfy the reference workflow requirement.

### Write-provider contract

CP-5008 defines additive manifest and provider metadata for:

- Dry-run and live entrypoints or modes.
- Declared target write scope.
- Required credential references.
- Change-set, validation, verification, and recovery artifacts.
- Idempotency behavior.
- Recovery mode.
- Permission declarations, including `production_access` and destructive
  behavior where applicable.

The reference provider must target a system that can be exercised safely in
automated tests and demonstrated against a real local or explicitly configured
target. Target selection is finalized in CP-5008; CP-5001 does not preselect a
CMS or external service.

### Multi-runtime execution

The runner becomes a dispatcher over runtime-specific adapters while preserving
one provider execution contract.

MVP v1 targets:

- Python, preserving current behavior.
- Node.
- Local binary.
- Container, when an approved local container runtime is available.

Every adapter must enforce the same request/result protocol, timeout, output
limit, artifact containment, environment construction, secret injection,
policy checks, and event reporting. A runtime adapter cannot bypass
`JobService` or create a second execution path.

Container support is optional at runtime but its manifest validation and clear
unavailable-runtime error are required. Canto does not download runtimes or
container images automatically.

### Resource and network limits

MVP v1 adds baseline per-job controls for:

- Wall-clock timeout.
- CPU time.
- Memory.
- Artifact and working-directory disk usage.
- Captured output size.
- Process termination and child-process cleanup.
- Network egress allowlist derived from policy and approved target metadata.

Controls must fail closed when a provider requests a permission that the active
runtime cannot enforce. Platform-specific enforcement limits must be visible in
job events and documentation.

MVP v1 does not claim hostile-code isolation. Installed capability code remains
trusted local code. Strong multi-user and untrusted-package sandboxing belongs
to MVP v2 and MVP v3.

### Developer experience and packaging

The release includes:

- A `canto demo` command family based on deterministic local examples.
- Human-readable plan, artifact, and timeline views while retaining JSON output
  for automation.
- Actionable missing-input and missing-capability messages.
- Troubleshooting documentation.
- Local installation and upgrade instructions.
- A seed set of reviewed local capabilities, including the reference write
  workflow.

CLI presentation is an additive view over existing models. Machine-readable
HTTP and JSON behavior remains governed by orchestration contract v1.0.

## Architecture Boundaries

### Required invariants

- `(skill, provider)` remains the execution identity.
- `capability@version` remains package and provenance identity.
- Canto owns execution through `JobService` and runtime adapters.
- `Approval` remains the only persisted approval object.
- Capability installation remains explicit and local.
- Artifact paths remain contained within Canto-managed job directories.
- Secrets are resolved at execution time and never become durable job inputs.
- Dry run never mutates the target.
- Live write never occurs without an approved, unchanged dry-run change set.
- A live write workflow cannot be marked complete until the live job,
  post-write verification, and required recovery artifact generation have each
  reached a terminal state.

### Frozen contract policy

The orchestration contract remains at `contract_version: "1.0"` unless a work
packet demonstrates that a breaking wire change is unavoidable.

Expected MVP v1 contract work should be additive, such as optional policy,
promotion, verification, recovery, or write-status fields. Any removal, rename,
or incompatible status transition requires the major version process in
`docs/contract-compatibility.md`. Adding new status or enum values must be
compatibility-reviewed. If clients are not required to tolerate unknown
values, the change requires the major version process. Contract changes also
require regenerated OpenAPI and JSON Schemas.

Internal replacement of Redis and `PlanStore` does not itself change the HTTP
contract.

## Data and Control Flow

```text
Installed trusted capability
        |
        v
Discover -> Plan -> Dry-run approval -> Dry-run Job
                                      |
                                      v
                              Proposed change set
                                      |
                                      v
                         Live-promotion approval
                                      |
                                      v
Vault reference -> secret resolution -> Live Job -> Verification
                                             |
                                             v
                                  Rollback / compensation
```

All durable lifecycle records flow to `SqliteStateStore`. Provider artifact
files remain under Canto-managed job directories and are referenced by stored
artifact metadata.

## Work-Packet Sequence

CP-5001 is this scope/design packet and is complete when this document is
approved. The implementation sequence then begins with CP-5002.

The core packets execute in this order unless a later design review records a
dependency change:

1. CP-5002 — SQLite system of record and state-store contract tests.
2. CP-5003 — Redis/filesystem-plan migration tool.
3. CP-5004 — Credential vault and reference resolution.
4. CP-5005 — Rotation and redaction guarantees.
5. CP-5008 — Write-provider contract and reference provider.
6. CP-5006 — Dry-run to live promotion path.
7. CP-5007 — Idempotency and recovery.
8. CP-5009 — Pre-write validation and post-write verification.
9. CP-5010 — Multi-runtime adapters.
10. CP-5011 — Resource limits and egress enforcement.
11. CP-5012 — Local installation, upgrade, and quickstart.
12. CP-5013 — Seed trusted capability set.
13. CP-5014 — Stability, release notes, and documentation.

The CP-1201 through CP-1210 developer-experience packets may begin after
CP-5002 establishes the default local state path. UX changes that expose write
promotion wait for CP-5006 through CP-5009.

## Testing Strategy

Each implementation packet must add focused tests and preserve the full suite.
MVP v1 release verification includes:

- Shared state-store contract tests against memory, SQLite, and retained Redis
  implementations where supported.
- Restart and migration tests preserving IDs, ordering, and approvals.
- Secret-leak tests across persisted state, request files, logs, events,
  artifacts, stdout, stderr, and error paths.
- Dry-run mutation-negative tests.
- Promotion tamper and stale-approval tests.
- Idempotent retry and recovery tests.
- Runtime-adapter conformance tests.
- Resource-limit and egress-denial tests.
- End-to-end local install, vault, plan, approve, dry run, promote, verify, and
  recover demonstration.

Tests use local fixtures and mock targets by default. No test may require real
credentials, remote registries, or uncontrolled external writes.

## Release Gates

MVP v1 is not complete until all of the following are true:

- SQLite is the default durable store and Redis is optional.
- Existing local state has a documented migration path.
- No known secret value is persisted or emitted by tested execution paths.
- The reference write workflow requires an immutable dry-run artifact and
  explicit live approval.
- The reference write is idempotent and automatically recoverable.
- Pre-write and post-write artifacts prove intended and actual state.
- Every runtime adapter passes the same conformance suite.
- Resource and egress controls fail closed where enforcement is unavailable.
- The frozen contract artifacts are synchronized and compatibility-reviewed.
- Installation, upgrade, quickstart, troubleshooting, and release notes are
  complete.
- The complete local workflow passes without Redis or another state daemon.

## Non-Goals

- Multi-user identity, roles, authorization, or per-user isolation.
- Non-loopback server deployment.
- MySQL or PostgreSQL state stores.
- Redis queues or event fan-out.
- Remote registries, publishing, signing, or third-party package trust.
- Automatic dependency or runtime installation.
- AI-generated capabilities, AI-authored provider code, or autonomous plan
  approval.
- Advanced orchestration-level retry policies, parallelism, branching,
  conditional plans, or resume-from-failed-step workflows.
- Autonomous approval or unattended production writes.
- Hostile or mutually distrusting capability execution.

## Decisions Deferred to Later Packets

- SQLite schema, migration framework, database filename, and backup mechanics:
  CP-5002.
- Vault encryption backend, key custody, and reference syntax: CP-5004.
- Reference target system and write-provider manifest additions: CP-5008.
- Exact promotion and write-state model: CP-5006.
- Idempotency key derivation and recovery record format: CP-5007.
- Runtime adapter manifest details and availability checks: CP-5010.
- Platform-specific CPU, memory, disk, process, and egress enforcement:
  CP-5011.

These decisions must preserve the invariants and release gates in this
document.
