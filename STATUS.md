# Canto Implementation Status

Updated: 2026-06-11

## Release Preparation

MVP v1 CP-5001 through CP-5014 are complete. Release notes are available at
`docs/release-notes-mvp-v1.md`; installation, runtime limits, credentials,
write governance, seed capabilities, and troubleshooting each have dedicated
documentation. The isolated `scripts/demo-mvp-v1.sh` flow proves local package
installation, discovery, planning, approval, vault-backed execution, dry run,
promotion, verification, and rollback without Redis or network access.

MVP v1 verification:

- `git diff --check`
- `.venv/bin/pip check`
- `.venv/bin/pytest tests import_capability/tests`
- `./scripts/quickstart-mvp-v1.sh`
- `./scripts/demo-mvp-v1.sh`
- `bash scripts/demo-delegated-executors.sh`

MVP v1.1 Delegated Executor Workspaces CP-1301 through CP-1314 are complete and
merged. Canto now supports durable delegation tasks, bounded sparse Git
worktrees, manual and Codex CLI profiles, immutable result revisions,
review/revision loops, observed command evidence, explicit patch promotion,
conflict-aware promotion queues, and restart-safe timelines.

Current verification result: `242 passed`, with one existing non-blocking
Starlette `TestClient` deprecation warning. The MVP v1 scripts and the
network-free delegated-executor demo pass.

A review-only real cloud smoke test also succeeded with `gpt-5.4-mini`: Canto
created the sparse worktree, launched the authenticated headless Codex child,
captured revision 1, and stopped in `reviewing` without modifying the canonical
repository. The run identified assignment, generated-cache capture, and
revision-relaunch issues; those fixes are merged and covered by regression
tests. The reproducible procedure is documented in
`docs/local-installation.md`.

The v2.2 implementation is merged. Release notes are available at
`docs/release-notes-v2.2.md`. README quickstart commands and the isolated local
demonstration flow have been verified before v3 work begins.

Completed milestones:

- v1.1-v1.4: capability manifests, local packages, registry lifecycle, import
  planning capabilities, archives, and scaffolding.
- v2.0: installed-capability discovery, deterministic plans, approvals,
  artifact dependencies, execution, and explanation.
- v2.1: unified runtime/package registry view, canonical runnable identity,
  provider bindings, JobService execution, approval objects, and lazy refresh.
- v2.2: frozen orchestration contract v1.0, HTTP orchestration endpoints,
  polling semantics, OpenAPI, JSON Schemas, and compatibility documentation.
- MVP v1 CP-5001: approved scope and design.
- MVP v1 CP-5002: SQLite is the default durable state store for jobs, events,
  approvals, artifact metadata, registry snapshots, and execution plans.
- MVP v1 CP-5003 through CP-5014: state migration, encrypted credentials,
  redaction, governed writes, idempotency/recovery, verification, runtime
  adapters, resource/egress limits, wheel packaging, quickstarts, reviewed
  seed capabilities, and release stabilization.
- MVP v1.1 CP-1301 through CP-1314: delegated executor architecture and state,
  sparse workspaces, manual and Codex CLI execution, artifact capture,
  review/revision, exact-patch promotion, command evidence, parallel status,
  conflict detection, timelines, documentation, and end-to-end tests.

Release-prep verification:

- `pip check`: no broken requirements.
- SQLite and CLI checks: healthy runtime and expected registry output without a
  state daemon.
- API quickstart: focused API and OpenAPI tests pass.
- `./scripts/demo-v2.2.sh`: pack, validate, install, list, inspect, discover,
  plan, approve, execute, explain, export, and archive revalidation pass using
  isolated local state.

## Orchestration Contract v1.0

**Canto orchestration contract v1.0 is frozen subject to documented deferred
items.** The frozen loop is `discover → plan → approve → execute → observe`,
with Canto-owned execution through `JobService`, the existing `Approval` model,
and `202 + poll` completion semantics.

Freeze artifacts are checked in at:

- `docs/orchestration-api-contract.md`
- `docs/openapi.json`
- `docs/schemas/`
- `docs/contract-compatibility.md`
- `docs/contract-freeze-audit.md`

Freeze verification remains covered by the current full suite, including
OpenAPI/JSON Schema synchronization and the complete HTTP orchestration loop.

Deferred contract items are full authentication, non-loopback security
enforcement, Server-Sent Events, manifest schema-version metadata, and the
remaining wire-shape gaps listed in the freeze audit. Remote registry, AI
generation, signing, dependency solving, and webhooks remain out of scope.

This document tracks implementation against `SPEC-v1.MD`. Steps 1-14 are the
spec's prescribed build order. Steps 15 onward track remaining explicit v1
requirements and hardening discovered while completing that order.

Status values: `COMPLETE`, `IN PROGRESS`, `NOT STARTED`, `DEFERRED`.

| Step | Status | Work |
| ---: | --- | --- |
| 1 | COMPLETE | Repository skeleton and Python package layout. |
| 2 | COMPLETE | Redis connection, job model, events, artifacts, approvals, and in-memory test store. |
| 3 | COMPLETE | YAML manifest loader for skills, providers, and tools. |
| 4 | COMPLETE | Registry, skill, and provider API endpoints. |
| 5 | COMPLETE | Job creation and job inspection API endpoints. |
| 6 | COMPLETE | Dependency checker used before provider execution. |
| 7 | COMPLETE | Bounded registered Python provider runner contract. |
| 8 | COMPLETE | Contained artifact collection, listing, and text artifact reads. |
| 9 | COMPLETE | CLI health, registry, inspection, run, job, approve, and reject commands. |
| 10 | COMPLETE | `source_inventory.public_html_crawler` built-in provider. |
| 11 | COMPLETE | Approval state machine and approval-gated execution. |
| 12 | COMPLETE | Structured missing-skill and missing-provider responses. |
| 13 | COMPLETE | Approval-gated skill, provider, and tool scaffold capabilities. |
| 14 | COMPLETE | Unit, API, crawler, registry, state, and workflow tests. |
| 15 | COMPLETE | Callable `check_dependencies.manifest_dependency_checker` with JSON and Markdown artifacts. |
| 16 | COMPLETE | `migration_report.local_markdown_report` built-in capability. |
| 17 | COMPLETE | Atomic approval decisions for concurrent approve/reject requests. |
| 18 | COMPLETE | Final SPEC-v1 requirement and security-posture audit. |
| 19 | COMPLETE | Require approval for network access to domains absent from `policy.approved_domains`. |
| 20 | COMPLETE | Reject raw credential-like job inputs and require local references such as `env:NAME`. |
| 21 | COMPLETE | Prevent crawler redirects from leaving the approved source hostname. |
| 22 | COMPLETE | Full verification and release-readiness summary. |

## Verification

- Steps 1-15: `.venv/bin/pytest` passes 16 tests.
- Step 16: focused job and registry suite passes 11 tests.
- Step 17: focused state and job suite passes 13 tests.
- Step 18: audit identified the domain approval and credential-reference gaps tracked in steps 19-20.
- Step 19: focused job and crawler suite passes 11 tests; CLI exposes `--approved-domain`.
- Step 20: focused job and API suite passes 15 tests.
- Step 21: crawler suite passes 2 tests, including a zero-request cross-host redirect assertion.
- Step 22: `.venv/bin/pytest` passes 24 tests; compileall, registry JSON validation,
  and `git diff --check` pass.

## Current Result

All numbered SPEC-v1, MVP v1, MVP v1.1, and MVP v1.2 implementation packets are
complete. MVP v1.2 Delegated Executor UX Hardening includes foundation
packet CP-1315 and CP-1201 through CP-1210. The daily workflow now covers global
state with repo-local bootstrap, dashboard inspection, reusable profiles,
isolated prompt comparisons, local Ollama preflight, review summaries, typed
conflicts, explicit promotion, and a one-command offline demo. The current full
suite passes 280 tests without network access or downloaded models.

CP-1315 bootstrap now also generates non-secret shared/orchestrator/executor
manuals, preserves existing `AGENTS.md` guidance while adding a Canto pointer,
provides `canto repo doctor`, exposes committed manuals inside sparse delegated
worktrees, and injects explicit executor-role instructions at launch.

The Architecture Language Sprint is in progress. CP-1401 freezes the public
model around Developer, Worker, Toolbox, Operation, Run, Result, Guardrails,
Catalog, and qualified Apply actions. CP-1402 completed the public terminology
audit. Internal identifiers and the frozen orchestration contract remain
unchanged while current user guidance migrates to the public vocabulary.

Known non-blocking issue: Starlette's current `TestClient` emits a deprecation
warning recommending a future `httpx2` migration. Runtime behavior and tests
remain successful under the versions pinned in `pyproject.toml`.
- Working tree validation: `git diff --check` passes.

## Deferred By Specification

- `ollama_generate` is optional and must not be a v1 dependency.
- Automatic dependency installation is deferred to v1.1.
- Dashboard, marketplace, distributed queues, multi-user authentication, and
  autonomous registration remain v1 non-goals.
