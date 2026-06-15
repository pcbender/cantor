# Canto Roadmap

Status: updated after completion of MVP v1.2 Delegated Executor UX Hardening.

Canto has moved beyond proof-of-concept. The system can now package capabilities, install them, discover them, compose approved plans, execute those plans through the bounded JobService/runner path, expose orchestration over HTTP, and publish a frozen v1.0 orchestration contract.

**MVP v1.2 — Delegated Executor UX Hardening** is complete through CP-1210,
including foundation packet CP-1315. External Orchestrator Integration remains
scheduled within MVP v2 after the local single-user and delegated-executor
foundations.

---

## Operating Model

Canto development uses an Orchestrator / Worker pattern.

- **Cantor**: human authority; approves direction, risk, registration, releases, and destructive actions.
- **Orchestrator**: maintains architectural intent, defines work packets, reviews changes, and controls sequencing.
- **Worker**: implements bounded tasks exactly as scoped.

The worker must not redesign the architecture unless a work packet explicitly authorizes an architecture change.

---

## Architecture Lock

The following concepts are locked unless changed by an explicit architecture ticket:

- Skill
- Provider
- Tool
- Artifact
- Job
- Approval
- Registry
- Policy
- Dependency checking
- Bounded local execution
- Capability package
- Execution plan
- Orchestration contract

Workers may add capabilities and integrations inside this model. Workers may not rename, replace, or bypass this model.

---

## Canonical Identity Decision

Canto uses two identities for two different purposes:

- **`(skill, provider)`** is the canonical execution identity.
- **`capability@version`** is the packaging, provenance, checksum, risk, and distribution identity.

A capability may expose one or more executable `(skill, provider)` pairs. The package identity never replaces the runner identity.

---

# Completed Phases

## v1.1 — Capability Packaging

Goal: turn local skills/providers/tools into installable capability packages.

Delivered:

- Capability manifest format
- Manifest validation
- Capability package layout
- Validation command
- Package design documentation
- Fixtures and CLI/unit tests

Success condition met:

A local capability can be described, validated, and prepared for deterministic packaging.

---

## v1.2 — Local Capability Registry

Goal: install, list, inspect, validate, and remove packaged capabilities from a local registry.

Delivered:

- Local registry directory layout
- Registry API
- Registry index model
- Local list/search
- Inspect command
- Remove command
- Installed package validation
- Directory-first install design and implementation

Success condition met:

A capability can be installed locally, discovered in the local registry, inspected, validated, and removed safely.

---

## v1.3 — Import Capability

Goal: build the first showcase reusable capability for CMS/content import planning.

Delivered:

- Import capability skeleton
- Static HTML provider
- WordPress REST inventory provider
- ProcessWire exported-JSON provider
- SQL dump inventory and CMS detection
- Inventory artifact
- Content artifact
- Schema artifact
- Migration plan artifact
- Crosswalk mappings
- Artifact-only transformation rules

Non-goals preserved:

- No destructive import
- No production writes
- No credential storage
- No live database connections

Success condition met:

Canto can analyze content sources and produce migration-ready artifacts without writing to a target system.

---

## v1.3.5 — Capability Archives

Goal: complete the local package lifecycle before capability scaffolding.

Delivered:

- Deterministic `.canto` archive creation
- Archive validation
- Installation from `.canto` archives
- Export of installed capabilities
- Pack → install → list → inspect → execute → export lifecycle
- Installed checksum validation
- Collision rejection

Success condition met:

A capability directory can be packed, validated, installed, executed, and exported as a deterministic `.canto` archive.

---

## v1.4 — Capability Scaffolding Workflow

Goal: create deterministic local capability scaffolds that can be validated, packed, and installed.

Delivered:

- Scaffold design documentation
- `canto scaffold NAME`
- Manifest generation
- Skill/provider/test templates
- Scaffold → validate → pack → install flow

Non-goals preserved:

- No AI generation
- No remote registry
- No dependency installation
- No automatic trust

Success condition met:

Canto can create a valid placeholder capability package that fits the local capability lifecycle.

---

## v2.0 — Orchestrated Capability Discovery

Goal: discover installed local capabilities, propose reviewable workflows, and execute only approved plans.

Delivered:

- Capability intent/input/output metadata
- Deterministic local discovery
- Workflow candidate model
- Persisted plan model
- Draft and approved plans
- Approved-only sequential execution
- Exact artifact dependency resolution
- Plan explanation
- Full discover → plan → approve → execute → explain demo

Non-goals preserved:

- No remote registry
- No AI-generated capabilities
- No credential handling
- No target writes
- No dependency auto-installation

Success condition met:

Canto can discover installed capabilities for a goal, create a deterministic plan, approve it, execute it, and explain it.

---

## v2.1 — Registry Unification

Goal: unify discovery, planning, execution, approvals, and HTTP visibility around one executable registry view.

Delivered:

- Registry audit
- Canonical execution identity ADR
- HTTP/CLI registry parity
- Capability manifest provider bindings
- Provider binding validation
- Plan steps carrying runnable `(skill, provider)` identity
- Artifact-to-input binding model
- JobService-backed orchestration execution
- Single approval model unification
- Lazy registry reload semantics
- End-to-end unification test

Success condition met:

The same installed capability is visible to CLI registry, HTTP registry, discovery, planning, approval, JobService execution, explanation, and artifact production.

---

## v2.2 — Contract Freeze

Goal: freeze the v1.0 orchestration API contract for external callers.

Delivered:

- Contract freeze audit
- `contract_version` field on orchestration-facing responses
- OpenAPI export
- JSON Schemas
- HTTP orchestration endpoints:
  - `POST /discover`
  - `POST /plans`
  - `GET /plans/{plan_id}`
  - `GET /plans/{plan_id}/explain`
  - `POST /plans/{plan_id}/approve`
  - `POST /plans/{plan_id}/execute`
  - `GET /plans/{plan_id}/events`
- Polling semantics
- Auth placeholder documentation
- Contract compatibility statement
- HTTP contract integration coverage

Success condition met:

The external orchestration loop is frozen as:

```text
Discover → Plan → Approve → Execute → Observe
```

Canto owns execution. External orchestrators call Canto through the contract; they do not supply executors or bypass policy.

---

# Forward Roadmap

The forward plan has three primary MVP release tiers — **MVP v1** (single-user,
write-capable, local), **MVP v2** (local team server), and **MVP v3** (public
server). The local **MVP v1.1 Delegated Executor Workspaces** extension is
complete. **MVP v1.2 Delegated Executor UX Hardening** is also complete. Each
release remains a usable foundation for the next.

How to read this:

- Build the tiers in order. Within a tier, start with its foundation packets (the state store
  first) and work down the list.
- Workstreams that were previously standalone phases (external integration,
  MCP adapter, UX, remote registry, signing) are folded into the tier that needs
  them, shown as labeled work-packet groups under each tier. Delegated executor
  coordination is the local MVP v1.1 extension and executes before UX/DX.
  **AI-Assisted Authoring** and **Advanced Workflow Orchestration** are post-MVP
  — see the section after the tiers.
- Work-packet IDs (`CP-####`) are stable identifiers carried over from earlier revisions; the
  leading digits reflect the original workstream, not execution order. Sequencing is given by
  list position within a tier, not by the numeric ID.
- State moves off Redis as the system of record, per `docs/adr-state-store.md`: a SQL store
  behind the `StateStore` Protocol (`SqliteStateStore` for v1; `MySqlStateStore`, plus
  `PostgresStateStore` at v3, for the servers), covering jobs, events, approvals, artifact
  metadata, the registry snapshot, and execution plans (`PlanStore` folds in as server-owned
  state). Redis is retained only as an optional event/queue adjunct, never the durable truth.

Each tier extends the previously frozen contract; every contract-affecting change is an explicit
`contract_version` bump, not a silent edit.

---

## MVP v1 — Single-User, Write-Capable (local)

Goal: a single developer runs Canto locally and uses it end to end to perform real guarded
target-system writes — the first genuinely usable release.

Followed by: Delegated Executor Workspaces (MVP v1.1), then Orchestrator UX &
Developer Experience (formerly v3.2).

Deliverables:

- `SqliteStateStore` as the default system of record (behind the existing `StateStore`
  Protocol), replacing Redis as durable truth; embedded, single-file, ACID, no daemon — see
  `docs/adr-state-store.md`. Covers jobs, events, approvals, artifact metadata, the registry
  snapshot, and execution plans (`PlanStore` folds into the store of record)
- One-time Redis → SQLite state-migration tool for existing local deployments
- Single-user credential vault: scoped local secrets, vault-backed `*_ref` resolution
  (extending the `env:` model), rotation, and guaranteed redaction in artifacts/events/logs
- Guarded target-system writes honoring `destructive` / `production_access` permissions, with
  dry-run → live promotion, idempotency, and a rollback / compensation path
- Write-provider contract and a reference write-capable provider
- Pre-write validation and post-write verification artifacts
- Multi-runtime provider execution (non-Python: node / container / binary) under the same
  policy, bounds, approval, and artifact contract
- Baseline execution hardening: CPU / memory / disk limits and per-job network egress allowlist
- Local install / packaging of Canto itself and a quickstart
- Seed set of trusted local capabilities, including at least one real write workflow
- 1.0-single-user stability for contract, manifest, and package formats; release notes

Non-goals:

- No multi-user, authentication, or networked exposure (loopback only)
- No unattended or rollback-free writes; no write without a dry-run artifact
- No remote registry or third-party capability trust
- No server-class database or external state daemon required

Success condition:

A single developer installs Canto locally, stores credentials in the vault, installs a trusted
capability, approves a plan, and performs a real reversible guarded write to a target system —
observed and audited — with no networked multi-user surface.

Recommended work packets — core (state, credentials, writes, runtime, packaging):

Status: **complete**. CP-5001 through CP-5014 were implemented and verified on
2026-06-10. Deferred developer-experience packets remain separately scoped
below.

- CP-5001 — MVP v1 Scope and Design
- CP-5002 — `SqliteStateStore` System of Record (behind the `StateStore` Protocol)
- CP-5003 — Redis → SQLite State-Migration Tool
- CP-5004 — Single-User Credential Vault and Vault-Backed `*_ref` Resolution
- CP-5005 — Secret Rotation and Redaction Guarantees
- CP-5008 — Write-Provider Contract and Reference Provider
- CP-5006 — Guarded Write Execution Path (dry-run → live promotion)
- CP-5007 — Idempotency and Rollback / Compensation
- CP-5009 — Pre-Write Validation and Post-Write Verification
- CP-5010 — Multi-Runtime Provider Execution (node / container / binary)
- CP-5011 — Baseline Resource Limits and Per-Job Egress Allowlist
- CP-5012 — Local Install / Packaging and Quickstart
- CP-5013 — Seed Trusted Capability Set
- CP-5014 — MVP v1 Stability, Release Notes, and Documentation

---

## MVP v1.1 — Delegated Executor Workspaces (local extension)

Goal: allow an orchestrator to assign bounded implementation work to local
executor agents in isolated Git worktrees, capture durable review artifacts,
and promote accepted changes into the canonical workspace through an explicit,
auditable decision.

Design source: `docs/Canto Delegated Executor Workspaces.md`.

Architecture posture:

- Add delegation concepts beside existing Canto concepts; do not rename or
  replace Skill, Provider, Tool, Artifact, Job, Approval, Registry, Policy,
  capability packages, plans, or StateStore.
- CLI-first and local-only. The frozen orchestration HTTP contract remains
  unchanged.
- Implement manual/external executor coordination before automated Codex CLI
  launch.
- Use Git worktrees for workspace isolation and patch application for the first
  promotion mechanism.
- Treat executor output as untrusted until orchestrator review. Worktree and
  command-policy controls are safety rails, not hostile-code isolation.
- Store delegation lifecycle records in StateStore and large artifacts under
  Canto-managed delegation directories.

Non-goals:

- No autonomous task assignment, approval, or promotion.
- No direct executor access to canonical project state, secrets, or Canto
  target-write capabilities.
- No multi-user server, HTTP/MCP delegation API, remote executor pool, or public
  sandboxing.
- No automatic dependency installation or cross-executor communication.

Success condition:

An orchestrator creates a bounded task, a manual or Codex CLI executor edits an
isolated worktree and records tests/artifacts, the orchestrator requests a
revision, accepts the result, promotes the reviewed patch, and can inspect the
complete durable timeline after restart.

Recommended work packets — delegated executor workspaces:

CP-1300 is the workstream identifier, not an implementation packet. The
implementation sequence begins with CP-1301 and completes before CP-1201.

- CP-1301 — Delegated Executor Scope and Architecture
- CP-1302 — Delegation Data Models and StateStore Records
- CP-1303 — Delegation Workspace Lifecycle
- CP-1304 — Manual Executor Workflow
- CP-1305 — Codex CLI Executor Profile
- CP-1306 — Delegation Artifact Capture
- CP-1307 — Review and Revision Flow
- CP-1308 — Promotion Flow
- CP-1309 — Command Recording and Test Result Capture
- CP-1310 — Executor Pool Status and Parallel Task View
- CP-1311 — Conflict Detection and Merge Queue
- CP-1312 — Delegation Events and Timeline
- CP-1313 — Documentation and Demo
- CP-1314 — End-to-End Local Delegated Executor Test

CP-1301 through CP-1314 are complete and merged. The delegated executor
workspace workstream passed the full automated suite, the network-free local
demo, and a review-only real cloud Codex smoke test. MVP v1.2 is complete.

---

## MVP v1.2 — Delegated Executor UX Hardening (local extension)

Goal: make the completed delegated-executor architecture comfortable and clear
enough for daily local use without adding a second lifecycle, execution path,
approval model, or promotion mechanism.

Design posture:

- Keep `DelegationService`, `StateStore`, Git worktrees, immutable result
  revisions, reviews, command evidence, and exact-patch promotion as the
  canonical implementation.
- Prefer a coherent CLI workflow over a new local web application. A dashboard
  in MVP v1.2 means a human-readable terminal view unless CP-1201 proves a
  stronger need.
- Keep executor selection explicit. Presets reduce repeated configuration but
  never assign, launch, accept, or promote autonomously.
- Treat cloud Codex, local Ollama, and future harnesses as executor profiles
  behind the same delegation lifecycle. Model/provider identity remains
  provenance, not Canto execution identity.
- Make review evidence understandable without weakening checksum, scope,
  command, conflict, or canonical-repository checks.

Non-goals:

- No delegation HTTP/MCP endpoints, multi-user task board, browser dashboard,
  remote executor pool, or server-side scheduler.
- No autonomous task assignment, prompt optimization, acceptance, queueing, or
  promotion.
- No AI-generated provider code installation, credential injection, target
  writes, remote registry, dependency solving, or package signing.
- No replacement of the frozen orchestration contract or JobService execution
  path.

Hard rules:

- Do not introduce a second delegation lifecycle, executor launch path,
  acceptance decision, or promotion implementation.
- Do not let UX defaults weaken allowed/denied paths, command requirements,
  artifact checksums, repository identity, or explicit promotion authority.
- Do not claim hostile-agent isolation from sparse checkout or local process
  controls.
- Do not require network access, cloud quota, Ollama, or a downloaded model for
  the automated test suite.
- Do not add remote registry, AI generation, credential handling, target
  writes, or autonomous scheduling to this workstream.

Success condition:

A developer can configure a known executor once, create and launch a bounded
task with minimal flags, compare or revise executor sessions, understand the
patch/tests/conflicts at a glance, and run a complete disposable demo through
review without manually querying raw SQLite records or artifact JSON.

Recommended work packets — delegated executor UX hardening:

### CP-1201 — Delegated Executor UX Architecture and Design

Status: **approved and complete**. See
`docs/delegated-executor-ux-architecture.md`.

Audit the current `canto delegate` workflow and define the MVP v1.2 interaction
model before changing code.

Include:

- current command journey from profile setup through promotion;
- canonical task-detail and task-list views;
- dashboard information hierarchy and terminal output conventions;
- executor preset configuration and precedence;
- session/prompt revision and A/B comparison semantics;
- local Ollama harness boundary and offline test strategy;
- promotion review-summary and conflict-explanation contracts;
- one-command demo behavior, cleanup, and safety boundaries;
- compatibility and migration impact for existing delegation records.

Acceptance:

- Architecture continues to use the existing delegation lifecycle and durable
  records.
- The design explicitly distinguishes task, result revision, executor session,
  review, queue entry, and promotion.
- No code is required; approved product decisions are recorded for subsequent
  packets.

### CP-1315 — Repo Bootstrap, Repo-Scoped Configuration, and Agent Instructions

Status: **complete**. Global state, legacy SQLite migration, repository
bootstrap/configuration, identity binding, agent-facing role manuals,
`AGENTS.md` integration, `repo doctor`, launch-time role prompts, tests, and
docs are implemented.

Implement the approved rule: **Canto is globally installed and repo-aware;
repositories are bootstrapped, not installed into.**

Behavior:

- Add `canto repo init` to create `.canto/repo.toml` and
  `.canto/policy.toml` in the canonical Git repository.
- Create `.canto/delegate.toml`, role manuals under `.canto/agents/`, and an
  idempotent Canto pointer in top-level `AGENTS.md` without clobbering existing
  human guidance.
- Add `canto repo doctor` and inject executor role/manual references into
  supervised launch prompts.
- Resolve repo-scoped commands by searching upward from the working directory
  or from an explicit `--repo` path.
- Keep durable state, credentials, installed capabilities, executor profiles,
  artifacts, and delegation workspaces under global `~/.canto`.
- Link repo-local configuration to a stable `repo_id`, canonical path, Git
  common-dir identity, base commits, and remote metadata where present.
- Preserve delegation worktrees at
  `~/.canto/work/delegations/<task_id>/workspace/` and bind them to repository
  identity plus the exact base commit.
- Migrate the current `~/.canto/state/canto.db` layout safely to the target
  `~/.canto/state.sqlite`, refusing ambiguous dual-state situations.
- Give repo-scoped commands a clear `canto repo init` bootstrap message when run
  in an uninitialized Git repository.

Acceptance:

- A globally installed `canto` works from any initialized repository without a
  repo-local Canto installation.
- `canto repo init` is deterministic, non-destructive, and creates no secrets
  or durable task state in the repository.
- Existing global SQLite state is preserved through an atomic, tested migration
  or explicit compatibility path.
- Repository identity is recorded and revalidated by delegation preparation and
  promotion.
- Global commands remain usable outside a repository; only repo-scoped commands
  require bootstrap.
- Tests cover nested working directories, moved/mismatched repositories,
  missing Git commits, existing config, legacy state, and conflicting state
  files.
- Existing manifests, packages, registry, jobs, approvals, orchestration, and
  delegation records remain compatible.

### CP-1202 — Delegation Task Dashboard

Status: **complete**. Read-only compact/detail dashboard projections, human
terminal rendering, JSON output, deterministic ordering, and tests are
implemented.

Add a concise terminal dashboard for active and recent delegation tasks.

Behavior:

- Show task status, executor/profile, workspace, latest revision, review state,
  command evidence, queue blockers, and next valid operator actions.
- Support a compact list and detailed single-task view.
- Read durable state only; do not schedule, launch, review, or promote.

Acceptance:

- Multiple concurrent tasks are understandable without raw JSON.
- Terminal output remains deterministic and has a machine-readable option.
- Existing `show`, `status`, `pool`, and `timeline` compatibility is preserved.

### CP-1203 — Session Prompt and A/B Comparison Workflow

Status: **complete**. Prompt variants, supplemental instructions, immutable
session/result provenance, isolated sibling tasks, evidence comparison, CLI
commands, and compatibility tests are implemented.

Make repeated executor sessions and prompt variants explicit and reviewable.

Behavior:

- Allow an orchestrator to supply a named prompt variant or supplemental
  instruction for a launch.
- Preserve the exact rendered prompt and output per session.
- Run compared variants from the same recorded Git base in isolated workspace
  state so one session's edits cannot influence the other.
- Compare two sessions/results by changed files, patch summary, commands, exit
  state, and token/runtime metadata when available.
- Comparison never selects a winner or changes acceptance automatically.

Acceptance:

- A/B sessions remain attached to one task and immutable result revisions.
- Comparison rejects sessions with incompatible bases instead of guessing.
- Reviewers can identify which prompt/session produced each result.
- Revision feedback remains distinct from optional prompt variants.

### CP-1204 — Executor Profile Presets

Status: **complete**. Built-in and user presets, credential rejection, explicit
override precedence, profile list/show/save/check commands, availability checks,
and tests are implemented.

Reduce repeated executor setup with local named presets.

Behavior:

- Provide conservative built-in or generated examples for manual, cloud Codex,
  and local Ollama profiles.
- Store executable, model/provider provenance, launch mode, safe extra args,
  timeout, and default permissions without storing credentials.
- Define explicit precedence among preset, saved profile, task override, and
  command-line override.

Acceptance:

- A known profile can be reused without re-entering model/executable flags.
- Invalid or unavailable executables/models fail clearly before task mutation.
- Presets cannot weaken task scope, denied paths, or promotion requirements.

### CP-1205 — Local Ollama Executor and Smoke Test

Status: **complete**. The local-only Ollama preset, Codex/Ollama/model
preflight, no-pull behavior, scripted tests, and smoke-test boundary are
implemented.

Add and verify a local Ollama-backed executor profile through the same Codex CLI
or approved local harness boundary defined by CP-1201.

Behavior:

- Local-only model execution; no cloud fallback.
- Detect unavailable Ollama/runtime/model state with actionable diagnostics.
- Use a disposable Git fixture and stop at review by default.

Acceptance:

- Automated tests use a scripted/mock executable and require no downloaded
  model.
- An optional documented smoke test proves a configured local model.
- Local Ollama results use the same artifacts, reviews, command evidence, and
  promotion path as cloud Codex results.

### CP-1206 — Promotion Review Summary

Status: **complete**. Deterministic review evidence, checksum and canonical
readiness checks, blockers, human/JSON CLI output, and tests are implemented.

Add a human-readable pre-acceptance and pre-promotion summary derived from
immutable evidence.

Show:

- result revision and producing session/profile;
- changed files and patch statistics;
- observed, failed, reported, missing, and waived commands;
- denied/out-of-scope checks and artifact checksum state;
- canonical base/HEAD state and promotion readiness;
- explicit reasons acceptance or promotion is blocked.

Acceptance:

- Summary generation is read-only and deterministic.
- It does not replace artifact checksum verification at acceptance/promotion.
- Operators can review routine changes without opening raw JSON first.

### CP-1207 — Rich Conflict and Recovery Explanations

Status: **complete**. Typed overlap, stale-base, dirty-path, evidence, and
promotion-failure explanations with safe operator options are implemented.

Make overlap, stale-base, dirty-worktree, checksum, and failed-promotion states
actionable.

Behavior:

- Identify the conflicting task/revision, repository, and overlapping paths.
- Distinguish queue overlap from canonical divergence and local dirty changes.
- Show safe operator options such as revise, recapture, dequeue, retry, reject,
  or manual reconciliation without performing them automatically.
- Surface rollback-attempt and partial-state details for promotion failures.

Acceptance:

- Explanations are structured as well as human-readable.
- No automatic merge, rebase, reset, cleanup, or destructive recovery is added.
- Cross-repository tasks never report false path conflicts.

### CP-1208 — One-Command Delegated Executor Demo

Status: **complete**. The isolated offline demo command, optional explicit
promotion, external-runtime opt-ins, cleanup behavior, failure preservation,
and tests are implemented.

Add a `canto demo delegation`-style command consistent with CP-1201 design.

Behavior:

- Create a disposable repository and isolated Canto state.
- Run the complete scripted local workflow through review and optionally an
  explicitly requested promotion demonstration.
- Support a no-network default; cloud Codex and local Ollama modes are explicit
  opt-ins with quota/runtime warnings.
- Print artifact, workspace, timeline, and cleanup locations.

Acceptance:

- Default demo is deterministic, offline, and leaves normal `~/.canto` state
  unchanged.
- Failure preserves useful evidence and prints cleanup instructions.
- Existing shell demo remains valid until the command fully replaces it.

### CP-1209 — Delegated Executor Troubleshooting and Examples

Status: **complete**. Task-oriented manual, cloud Codex, and local Ollama
examples, diagnostics, artifact locations, and safe cleanup guidance match the
implemented CLI.

Add task-oriented examples and diagnostics for manual, cloud Codex, and local
Ollama workflows.

Cover:

- missing Git base commit, executable, login, model, or local runtime;
- sparse-path and denied-path mistakes;
- failed tests and generated cache files;
- revision relaunch, stale base, conflict queue, and promotion failure;
- artifact/log locations and safe cleanup.

Acceptance:

- Documentation matches implemented commands and defaults.
- Examples use disposable repositories and no real credentials.
- Cloud examples stop at review unless promotion is explicitly requested.

### CP-1210 — MVP v1.2 End-to-End UX Validation

Status: **complete**. The restart-safe integration flow covers a reusable
preset, dashboard, isolated prompt variants, immutable comparison, command
evidence, review summary, typed overlap explanation, explicit acceptance and
promotion, and the offline demo. The full suite passes 275 tests without
network access or downloaded models.

Prove the daily-use workflow across the completed UX surface.

Must cover:

- reusable profile preset;
- task creation and dashboard visibility;
- two prompt/session variants or a revision cycle;
- review summary and command evidence;
- conflict explanation;
- explicit acceptance and promotion in a disposable repository;
- restart-safe inspection;
- one-command offline demo;
- optional cloud Codex and local Ollama smoke-test documentation.

Acceptance:

- Full existing suite passes without network or downloaded models.
- No regression to manifests, packages, registry, jobs, approvals,
  orchestration, writes, or delegated promotion.
- MVP v1.2 release/status documentation records exact verification results.

### CP-1211 — Worker Outcome Validation

Status: **complete in MVP v1.1.1 hotfix**. The initial local Ollama dogfood run
showed that a Worker process can exit successfully without completing its
assigned repository work. The observed `qwen2.5-coder:14b` session emitted
tool-call JSON as text, changed no files, and reached Capture with no Result to
record.

Improve the existing delegation UX so process completion, completed work, and
advisory output are reported as distinct outcomes.

Behavior:

- Do not treat exit code `0` alone as proof that assigned work completed.
- Detect an unchanged Workspace before presenting Capture as the next action.
- Preserve and identify useful text-only output as advisory Worker evidence.
- Report likely model/harness tool-execution incompatibility with actionable
  profile guidance.
- Derive readiness and blockers through the existing projection layer without
  adding a second Worker lifecycle or execution path.

Acceptance:

- A successful process with repository changes continues through normal
  Capture and review.
- A successful process with no repository changes is reported clearly before
  Capture and does not imply that a Result exists.
- Advisory output remains inspectable through the existing launch artifacts.
- Existing delegation records remain readable; no persisted status enum or
  frozen orchestration contract change is required.
- Tests use scripted executors and require no Ollama model or network access.

### CP-1212 — Clean Missing-Task Error for AI Worker Launch

Status: **planned maintenance follow-up**. Cloud Worker dogfooding showed that
`canto delegate launch-ai UNKNOWN_TASK --allow-cloud` lets the expected
`DelegationError` escape Typer and prints a Python traceback from
`delegate_launch_ai` instead of a concise CLI error.

Behavior:

- Catch `DelegationError` from task lookup and subsequent delegation
  operations in `delegate_launch_ai`.
- Print `Error: Delegation task not found: TASK_ID` through the existing
  delegation CLI error path.
- Exit non-zero without a traceback.
- Preserve current behavior for valid prepared tasks, repository policy
  failures, selection failures, and Worker launch failures.
- Audit adjacent AI Worker CLI commands for the same expected-error boundary
  without broadly refactoring the CLI.

Acceptance:

- A missing task ID exits non-zero with one clear error message and no
  traceback.
- A valid `workspace_ready` task still reaches automatic Worker selection.
- Tests use local state and mocked Workers; no network or API key is required.
- No status enum, delegation lifecycle, or frozen orchestration contract
  changes are introduced.

MVP v1.2 is complete. CP-1211 was delivered as the bounded MVP v1.1.1
maintenance hotfix without reopening the release or completed CP-1300
workstream. CP-1212 is a bounded CLI maintenance follow-up. CP-1315 is an MVP
v1.2 foundation packet. Delegation HTTP/MCP exposure and multi-user executor
coordination remain MVP v2 work.

---

## Architecture Language Sprint

Goal: freeze an intuitive public vocabulary before the next implementation
workstream while preserving Canto's established internal architecture and
frozen orchestration contract.

Status: **complete**. CP-1401 through CP-1407 were completed and verified on
June 12, 2026.

Public language centers on Developer, Worker, Toolbox, Operation, Run, Result,
Guardrails, Catalog, and qualified Apply actions. Internal concepts remain
Capability, Skill, Provider, Tool, Plan, Job, Registry, Policy, and Approval.

The approved lexicon and packet boundaries are defined in:

- `docs/architecture-language-lexicon.md`
- `docs/architecture-language-sprint.md`

Work packets:

- CP-1401 — Public Architecture Lexicon (complete and frozen)
- CP-1402 — Public Terminology Audit (complete)
- CP-1403 — Public Documentation Migration (complete)
- CP-1404 — CLI, Help, and Message Language Design (complete)
- CP-1405 — Agent and Delegation Language Migration (complete)
- CP-1406 — Compatibility and Contract Audit (complete)
- CP-1407 — Language Freeze and Adoption Record (complete)

This is a presentation and compatibility workstream. It does not rename
persisted models, manifest fields, canonical identifiers, or frozen HTTP
contract fields. CLI aliases remain additive and require CP-1404 approval
before implementation.

The freeze record is `docs/architecture-language-freeze.md`. Future public
terminology changes require an Architecture Language decision record and
compatibility review.

---

## MVP v1.3 — Governed AI Worker Pool (single-user local extension)

Goal: give single-user Canto a globally configured pool of validated local and
cloud AI Workers, then deterministically select the least-cost eligible Worker
for a bounded delegation task under Developer-defined cloud, priority, and
budget policy.

Design source: `docs/ai-worker-pool-architecture.md`.

Architecture posture:

- Keep API keys only in the global Canto vault; repository bootstrap stores
  endpoint references and policy, never credentials.
- Support OpenAI, Anthropic, Google, generic OpenAI-compatible, and local Ollama
  endpoints through explicit adapters.
- Require a versioned coding-Worker probe before a model is eligible for
  implementation work; useful text-only models remain advisory.
- Let Canto select automatically from eligible candidates with deterministic,
  explainable ranking across capability, reliability, cost, latency, locality,
  size fit, availability, priority, and budget.
- Never widen local-only policy or fall back to cloud silently.
- Reuse the existing delegation Workspace, session, Result, Review, and Apply
  lifecycle.
- Introduce one provider-neutral API Worker harness locally; migrate that same
  harness behind authenticated server execution in MVP v2.
- Preserve existing CLI-authenticated profiles as explicit last-resort
  compatibility Workers, but exclude them from automatic pool selection,
  ranking, discovery, and fallback.

Non-goals:

- No OAuth, browser login, inherited CLI sessions, automatic key creation, or
  billing administration.
- No remote Worker pool, multi-user endpoint grants, autonomous approval, or
  silent policy changes.
- No model training, fine-tuning, or autonomous prompt/policy optimization.
- No change to the frozen orchestration HTTP contract in this workstream.

Success condition:

A Developer configures vault-backed local and cloud endpoints once, Canto
discovers and probes their exact models, automatically selects the least-cost
eligible Worker for a bounded task, records the selection and actual usage,
and completes the existing Capture → Review → Apply flow without manual model
trial-and-error or credentials in the repository.

Recommended work packets:

- CP-1501 — Governed AI Worker Pool Architecture and Design
- CP-1502 — Endpoint, Model, Probe, Selection, and Usage Models
- CP-1503 — Vault-Backed Endpoint Configuration
- CP-1504 — Provider Discovery Adapters
- CP-1505 — Versioned Coding-Worker Probe Harness
- CP-1506 — Worker Classification and Compatibility Evidence
- CP-1507 — Priority, Budget, and Eligibility Policy
- CP-1508 — Deterministic Worker Ranking and Explain Output
- CP-1509 — Provider-Neutral API Worker Harness
- CP-1510 — Automatic Assignment and Explicit Fallback
- CP-1511 — Usage, Cost, Health, and Reliability Records
- CP-1512 — Repo Bootstrap Integration and Migration
- CP-1513 — End-to-End Single-User Worker Pool Demo
- CP-1514 — Security, Stability, and Documentation Pass

CP-1501 through CP-1514 are complete. The governed single-user AI Worker pool
supports vault-backed endpoint configuration, exact model discovery, versioned
coding probes, deterministic policy selection, explicit cloud fallback,
provider-neutral API execution, durable usage evidence, repo bootstrap policy,
and an offline end-to-end demo. This workstream precedes MVP v2 and preserves
its server migration path.

### Local Model Catalog Reconciliation

Design source: `docs/local-model-catalog-reconciliation.md`.

Dogfooding established that local model capability must be learned once and
reused, rather than rediscovered by loading every installed model for every
task. Canto will reconcile exact local runtime inventory while preserving
historical probe and usage evidence. Runtime availability, curated metadata,
and observed Worker classification remain distinct.

Planned packets:

- CP-1515 — Local Model Catalog Reconciliation Design
- CP-1516 — Model Availability And Metadata Provenance Fields
- CP-1517 — Local Endpoint Reconciliation Service
- CP-1518 — `canto ai model refresh` And Change Summary
- CP-1519 — Model Status, Explain, And Safe Forget
- CP-1520 — Optional Local Probe Queue And Metadata Enrichment Boundary
- CP-1521 — Dogfood, Compatibility, Security, And Documentation Pass

Hard rules:

- Refresh inventories but does not load, run, pull, or delete models.
- Removed models become missing; their evidence is not erased.
- Changed digests invalidate probes without losing history.
- Web research is optional, source-labeled enrichment and never grants Worker
  eligibility.
- Automatic implementation selection requires current availability and a
  current successful Canto probe.
- Local refresh and probes never trigger cloud fallback.

---

## MVP v2 — Local Team Server

Goal: deploy one Canto instance on an internal network that a team of humans and AI
orchestrators share, with authenticated identity, per-user isolation, and operability.

Folds in: External Orchestrator Integration (formerly v3.0) and the MCP / Tool Adapter Layer
(formerly v3.1) — the team's humans and model clients reach the shared server through the frozen
HTTP contract and a local MCP bridge.

Deliverables:

- `MySqlStateStore` as the server-tier system of record (behind the `StateStore` Protocol),
  with multi-process concurrency and relational audit/retention queries — see
  `docs/adr-state-store.md`
- Optional Redis adjunct for event fan-out (SSE) and/or an async job queue — never the system
  of record
- Authentication (API keys / bearer tokens) on all mutating endpoints, with a documented
  `contract_version` bump
- Server-populated identity replacing client-supplied `requested_by` / `approved_by`
- Role model (Cantor / operator / viewer) and per-resource authorization
- Identity-stamped audit trail across jobs, plans, approvals, and secret access
- Multi-user secret scoping, ownership, and explicit grants
- Per-user state isolation and visibility rules
- Job-level execution sandboxing between users (stronger than the v1 baseline bounds)
- External orchestrator integration (formerly v3.0): reference client, contract smoke demo,
  request/response examples, human-in-the-loop approval flow, and error-scenario coverage
- MCP / tool adapter (formerly v3.1): a local MCP bridge mapping discover / plan / approve /
  execute / observe / explain / list-artifacts onto the frozen HTTP endpoints
- Deployment and operability: containerized deployment, configuration management, MySQL
  durability / HA and backup-restore, structured logging / metrics / tracing,
  health / readiness / liveness, retention and cleanup, rate limits and quotas
- 1.0-team release with upgrade and state-migration tooling and an operator runbook

Non-goals:

- No public exposure or untrusted third-party capabilities
- No federated / third-party identity providers
- No managed multi-tenant hosting

Success condition:

A team deploys Canto on an internal network, authenticates multiple users and orchestrators
(including model clients via MCP), isolates their work, runs approved guarded writes attributed
to real identities, and operates the service — observe, recover, retain, throttle — from
documented runbooks.

Recommended work packets — core (identity, state, isolation, operability):

- CP-6001 — MVP v2 Scope and Threat Model
- CP-6002 — `MySqlStateStore` Server-Tier System of Record (behind the `StateStore` Protocol)
- CP-6003 — Optional Redis Event-Bus / Queue Adjunct (event fan-out, async execution)
- CP-6004 — API Key / Bearer Token Authentication
- CP-6005 — Server-Populated Identity
- CP-6006 — Role and Authorization Model
- CP-6007 — Identity-Stamped Audit Trail
- CP-6008 — Multi-User Secret Scoping and Grants
- CP-6009 — Per-User State Isolation and Visibility
- CP-6010 — Job-Level Execution Sandboxing
- CP-6011 — Containerized Deployment and Configuration
- CP-6012 — MySQL Durability / HA and Backup-Restore
- CP-6013 — Logging, Metrics, and Tracing
- CP-6014 — Health / Readiness / Liveness and Retention
- CP-6015 — Rate Limits and Quotas
- CP-6016 — Upgrade / State-Migration Tooling and Operator Runbook
- CP-6017 — MVP v2 Release Notes and Documentation

Recommended work packets — external orchestrator integration (formerly v3.0):

- CP-1001 — External Orchestrator Integration Design
- CP-1002 — Python Client Library
- CP-1003 — Contract Smoke Test Script
- CP-1004 — External Orchestrator Example Prompts
- CP-1005 — Human Approval Demo
- CP-1006 — Error Scenario Examples
- CP-1007 — End-to-End External Demo
- CP-1008 — External-Integration Documentation Pass

Recommended work packets — MCP / tool adapter (formerly v3.1):

- CP-1101 — MCP Adapter Design
- CP-1102 — MCP Tool Definitions (discover, plan, approve, execute, observe, explain, list artifacts)
- CP-1103 — Local MCP Server / Bridge Implementation
- CP-1104 — MCP-to-Frozen-HTTP Endpoint Mapping
- CP-1105 — Approval and Execution Boundary Safety Notes
- CP-1106 — Adapter Tests Using Mock Capabilities
- CP-1107 — MCP-Adapter Documentation Pass

---

## MVP v3 — Public Server

Goal: operate Canto as a publicly reachable service that can safely accept and run capabilities
from many mutually-distrusting sources at scale.

Folds in: Remote Registry & Publishing (formerly v4.0) and Package Trust, Signing & Provenance
(formerly v4.1) — public sharing and trust-at-scale are public-tier concerns.

Deliverables:

- Managed / HA MySQL **or** PostgreSQL as the system of record at public scale
  (`MySqlStateStore` / `PostgresStateStore`, operator's choice), with a Redis adjunct for event
  fan-out and queueing where required — see `docs/adr-state-store.md`
- Full sandboxed isolation of untrusted and remotely-installed capabilities
  (container / namespace / seccomp-class)
- Hardened per-job network egress control and abuse protection at public scale
- Remote registry and publishing (formerly v4.0): remote registry, metadata schema,
  `canto registry add/remove/list/search`, `canto publish`, package download flow, registry
  cache, and local install from a downloaded archive
- Package trust, signing, and provenance (formerly v4.1): signing, signature verification,
  publisher identity, provenance fields, `canto verify`, and handling for unsigned / invalid /
  revoked / unknown packages — enforced at public scale
- Federated / third-party identity provider integration
- Public-grade multi-tenant isolation and quota / abuse controls
- Independent public security audit and penetration-test sign-off
- Public trust, abuse, and incident-response policy
- Public release posture and supported-configuration matrix

Non-goals:

- No marketplace or payments
- No autonomous approval or self-trust
- No silent trust escalation for unsigned or unknown packages

Success condition:

Canto runs as a public service where mutually-distrusting users install signed capabilities
from a remote registry and execute approved guarded writes in isolated sandboxes, and the
platform withstands an independent security audit — without any capability exceeding its
declared permissions, network scope, or resource budget.

Recommended work packets — core (isolation, federation, multi-tenant, audit):

- CP-7001 — MVP v3 Scope and Public Threat Model
- CP-7002 — Managed / HA MySQL or PostgreSQL (`PostgresStateStore`) and Redis Adjunct at Public Scale
- CP-7003 — Sandboxed Isolation of Untrusted / Remote Capabilities
- CP-7004 — Hardened Egress Control and Abuse Protection
- CP-7005 — Remote-Registry Trust Automation at Public Scale (implementation in the Remote Registry group below)
- CP-7006 — Enforced Signing / Provenance at Public Scale (implementation in the Signing group below)
- CP-7007 — Federated / Third-Party Identity Integration
- CP-7008 — Public Multi-Tenant Isolation and Quotas
- CP-7009 — Independent Security Audit and Pen-Test Sign-Off
- CP-7010 — Trust, Abuse, and Incident-Response Policy
- CP-7011 — MVP v3 Public Release and Supported-Configuration Matrix

Recommended work packets — remote registry and publishing (formerly v4.0):

- CP-2001 — Remote Registry Design
- CP-2002 — Registry Metadata Schema
- CP-2003 — `canto registry add/remove/list`
- CP-2004 — `canto registry search`
- CP-2005 — `canto publish` Design
- CP-2006 — Package Download Flow
- CP-2007 — Trust and Provenance Metadata
- CP-2008 — Checksum Verification on Download
- CP-2009 — Registry Cache
- CP-2010 — Local Install from Downloaded Archive
- CP-2011 — Remote-Registry Documentation Pass

Recommended work packets — package trust, signing, and provenance (formerly v4.1):

- CP-2101 — Package Signing Design
- CP-2102 — Signature Verification
- CP-2103 — Publisher Identity Metadata
- CP-2104 — Provenance Fields
- CP-2105 — Trust Policy Document
- CP-2106 — `canto verify` Command
- CP-2107 — Unsigned / Invalid / Revoked / Unknown Package Handling
- CP-2108 — Signing-and-Trust Documentation Pass

---

# Post-MVP

Deferred until after the MVP tiers ship. Not required for a usable release; each builds on the
proven MVP foundation.

## AI-Assisted Capability Authoring (formerly v5.0)

Goal: let an orchestrator help create or modify capabilities while Canto enforces scaffold, validation, tests, packaging, approval, and install boundaries.

Deliverables:

- Authoring workflow design
- Missing-capability-to-scaffold workflow
- Orchestrator-generated implementation proposal format
- Test generation guidelines
- Review gates
- Pack/install only after validation and approval
- Audit trail for AI-assisted changes

Non-goals:

- No autonomous code trust
- No self-installing generated capabilities
- No bypass of tests or approval
- No production writes by generated capabilities unless separately approved

Success condition:

A missing capability can be scaffolded, implemented with AI assistance, tested, packed, reviewed, approved, and installed without bypassing Canto's safety model.

Recommended work packets:

- CP-3001 — AI-Assisted Authoring Workflow Design
- CP-3002 — Missing-Capability-to-Scaffold Workflow
- CP-3003 — Orchestrator Implementation Proposal Format
- CP-3004 — Test Generation Guidelines
- CP-3005 — Review Gates
- CP-3006 — Validation-and-Approval-Gated Pack/Install
- CP-3007 — Audit Trail for AI-Assisted Changes
- CP-3008 — AI-Authoring Documentation Pass

---

## Advanced Workflow Orchestration (formerly v6.0)

Goal: support richer workflows after the linear, approved, artifact-based model has proven stable.

Potential deliverables:

- Branching plans
- Conditional steps
- Parallel-safe execution
- Retry policy
- Plan cancellation
- Resume from failed step
- Artifact versioning
- Plan templates

Non-goals:

- No uncontrolled autonomy
- No hidden execution
- No background mutation without explicit approval

Success condition:

Canto can express and execute richer workflows while maintaining explainability, artifact traceability, approval gates, and bounded execution.

Recommended work packets:

- CP-4001 — Advanced Workflow Model Design
- CP-4002 — Branching Plans
- CP-4003 — Conditional Steps
- CP-4004 — Parallel-Safe Execution
- CP-4005 — Retry Policy
- CP-4006 — Plan Cancellation
- CP-4007 — Resume From Failed Step
- CP-4008 — Artifact Versioning
- CP-4009 — Plan Templates
- CP-4010 — Advanced-Workflow Documentation Pass

---

## Deferred Until Explicitly Approved

Now scheduled (moved out of deferral):

- Credential vaulting → MVP v1
- Target-system writes → MVP v1
- Non-Python runners → MVP v1
- Full multi-user authentication and authorization → MVP v2
- Hosted/public Canto service → MVP v3
- Remote registry trust automation → MVP v3
- Federated / third-party identity providers → MVP v3
- Parallel execution → Post-MVP (Advanced Workflow Orchestration)

The following remain intentionally deferred:

- Autonomous package installation
- Dependency auto-installation
- Marketplace / payment features
- Autonomous approval or self-trust

---

## Release Status Summary

Current completed milestone:

```text
MVP v1.2 — Delegated Executor UX Hardening
```

MVP tiers (forward spine, built in order):

```text
MVP v1 — Single-user, write-capable (local) [complete]
MVP v1.1 — Delegated Executor Workspaces [complete]
MVP v1.2 — Delegated Executor UX Hardening [complete]
MVP v2 — Local team server
MVP v3 — Public server
```

Post-MVP: AI-Assisted Authoring, Advanced Workflow Orchestration.

Strategic direction:

```text
Canto is not the AI.
Canto is the governed capability runtime that AIs and humans can call.
```
