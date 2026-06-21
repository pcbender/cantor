# Canto Implementation Status

Updated: 2026-06-20

## Subscription CLI Workers

CP-1701 through CP-1720 are in progress on
`feature/subscription-cli-workers-phase3`. The design freeze is documented in
`docs/subscription-cli-workers.md`; current call sites are audited in
`docs/cli-executor-callsites.md`. Phase 1 keeps Codex CLI delegation
behavior-preserving while extracting a provider-neutral CLI execution seam,
adding a scrubbed subprocess environment, and exposing an explicit Codex
subscription-auth preflight through:

```bash
canto delegate profile check PROFILE --subscription-auth
```

Phase 2 adds explicit CLI transport policy. Saved Codex CLI `ExecutorProfile`
records may be selected by `canto delegate launch-ai TASK_ID` only when
`.canto/workers.toml` includes `allowed_transports = ["cli"]` or
`["cli", "http"]`. API fallback remains disabled when policy allows only CLI
transport.

Phase 3 adds structured CLI fallback states, priority-driven API fallback
rules, and optional orchestrator-provider context. Economy never spends API
credits after CLI exhaustion; balanced and quality report that API fallback
requires approval; urgent may use API fallback only when HTTP/API authority and
budget policy also permit it.

## Governed Memory Service

CP-1601 is approved and documented in
`docs/Canto Memory Service Specification.md`. CP-1602 through CP-1614 are
implemented on the governed memory service working branch. Canto now provides
project/repository/global-terminology scopes, proposal and existing Approval
activation, deterministic FTS-backed recall, reference resolution, context
packs, source pointers, retention, export, audit, secret rejection, and
generated agent guidance. The workstream reuses the existing StateStore,
Approval, repository identity, and delegation evidence models and does not
change the frozen orchestration HTTP contract. CP-1615 adds a true cross-Worker
shared-memory dogfood test and bounded Orchestrator approval by default for
low-risk repository/project memory.

## Governed AI Worker Pool

MVP v1.3 CP-1501 through CP-1514 are complete on the working branch. Canto can
configure vault-backed local/cloud endpoints, discover and probe exact models,
select the least-cost eligible Worker under explicit policy, run it through the
existing delegated Workspace lifecycle, and persist selection, usage, cost,
health, and exact-version evidence. Cloud use and fallback are never implicit.

Run `canto demo ai-worker-pool` for the offline acceptance flow or add
`--apply` to prove exact-Result promotion in the disposable demo repository.

CP-1515 now specifies the next bounded Worker-pool maintenance slice: local
model catalog reconciliation. The proposed direction is explicit
`canto ai model refresh ENDPOINT_ID` inventory reconciliation, separate
availability/classification/probe state, preserved evidence for removed or
changed models, and optional source-labeled metadata enrichment. Runtime code
has not yet been added for CP-1516 through CP-1521.

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
suite passes 281 tests without network access or downloaded models.

CP-1315 bootstrap now also generates non-secret shared, Developer, and Worker
manuals at compatibility paths, preserves existing `AGENTS.md` guidance while
adding a Canto pointer, provides `canto repo doctor`, exposes committed manuals
inside sparse delegated worktrees, and injects explicit Worker-role
instructions at launch.

The Architecture Language Sprint CP-1401 through CP-1407 is complete. Public
language is frozen around Developer, Worker, Toolbox, Operation, Run, Result,
Guardrails, Catalog, Review, and qualified Apply actions. Generated role
manuals and Worker launch prompts enforce the authority split. Internal
identifiers, existing commands and JSON fields, and orchestration
`contract_version: 1.0` remain unchanged. The freeze and exceptions are
recorded in `docs/architecture-language-freeze.md`.

Architecture Language verification: focused bootstrap and Worker launch tests
pass 21 tests; the full `tests import_capability/tests` suite passes 281 tests.

MVP v1.1.1 hotfix complete: CP-1211 — Worker Outcome Validation. A local
Ollama dogfood session using `qwen2.5-coder:14b` emitted tool-call JSON as text
instead of executing tools. Codex exited successfully, Canto marked the Worker
done, and Capture then found no Workspace changes. Canto now records
`completed_work`, `advisory`, or `no_work` as an additive launch outcome,
detects zero-change sessions before offering Capture, preserves text-only
stdout as advisory evidence, and surfaces likely model/harness compatibility
problems. Existing task statuses and the frozen orchestration contract are
unchanged.

MVP v1.1.2 hotfix is in progress: CP-1212 — Clean Missing-Task Error for AI
Worker Launch now reports unknown AI delegation task IDs through the existing
concise CLI error path without a traceback. The same hotfix keeps Canto-side
Worker policy/tool failures from poisoning local endpoint health, verifies
promotion by accepted content rather than brittle diff byte identity, and
filters the known Starlette `TestClient` dependency warning in the test
harness. Valid selection, launch, promotion, delegation statuses, and the
frozen orchestration contract remain unchanged.

Local model catalog reconciliation is complete through CP-1521. A configured
loopback Ollama endpoint can be refreshed explicitly; new, changed, missing,
unchanged, and unreachable states remain distinct. Current implementation
selection requires an available local model and current successful probe.
Status, detail, safe forget, opt-in sequential probe, and reviewed metadata
commands are documented in `docs/ai-worker-pool.md`. Tests use fake local
endpoint responses and make no model-server, cloud, or web-research calls.
The full `tests import_capability/tests` suite passes 352 tests; `pip check`
reports no broken requirements.

`canto repo doctor` now reports configured AI Worker endpoint, exact model,
cloud readiness, and local model status. Explicit policy requirements are
blocking; optional missing local capacity is a warning when cloud use remains
authorized.

Local Ollama dogfooding now validates current list-based capability metadata
and Ollama-native structured tool-call history. `local-ollama:gemma4:12b`
passes the implementation probe and is enabled in this repository's local-first
Worker policy. Provider HTTP errors include bounded response details without
request data or credentials.
The repository now prefers `local-ollama:qwen3.6:35b-a3b` and retains
`local-ollama:gemma4:12b` as an eligible local fallback through explicit
ordered `preferred_models` policy.

CP-1728 hotfix is implemented on the working branch: Nested Codex Worker
sandbox composition. Dogfooding showed that Codex Workers launched from inside
another agent sandbox need explicit Canto state access and, for cloud-backed
CLI Workers, explicit nested Codex network access. The hotfix is documented in
`docs/codex-nested-agent-sandbox-hotfix.md`.

CP-1729 hotfix is implemented on the working branch: Local Ollama Worker
reliability. `canto delegate launch-ai TASK_ID --local-only` forces the direct
local Ollama API Worker path, bypassing CLI and cloud Workers. Codex-Ollama CLI
profiles now receive nested sandbox network access because Ollama is reached
over loopback HTTP. The hotfix is documented in
`docs/local-ollama-worker-hotfix.md`.

- Working tree validation: `git diff --check` passes.

## Deferred By Specification

- `ollama_generate` is optional and must not be a v1 dependency.
- Automatic dependency installation is deferred to v1.1.
- Dashboard, marketplace, distributed queues, multi-user authentication, and
  autonomous registration remain v1 non-goals.
