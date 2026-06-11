# Delegated Executor Scope and Architecture

Status: Approved and complete
Work packet: CP-1301
Tier: MVP v1.1 local delegation extension

## Purpose

This packet freezes the local architecture for delegated executor work before
implementation begins in CP-1302. Canto will coordinate bounded coding or
documentation tasks performed by executor agents in isolated Git worktrees,
capture reviewable artifacts, and promote accepted changes through an explicit
orchestrator decision.

Delegation is a coordination workflow. It is not a replacement for skills,
providers, jobs, execution plans, target-write approvals, or `JobService`.

## Release Outcome

A local orchestrator can:

1. Select a configured executor profile and create a bounded delegation task.
2. Create a Canto-managed workspace from a recorded repository commit.
3. Materialize a delegation workspace containing only the declared repository
   context.
4. Record messages, commands, status transitions, logs, diffs, and artifacts.
5. Request one or more revisions without losing audit history.
6. Accept or reject the executor result.
7. Promote an accepted patch into the expected canonical repository.
8. Inspect the complete task timeline after restarting Canto.

## Locked Terms

- **Cantor:** the human authority for product direction, destructive actions,
  release decisions, and exceptional risk acceptance.
- **Orchestrator:** the supervising human or agent that defines task scope,
  assigns an executor, reviews results, requests revisions, and decides whether
  accepted work should be promoted.
- **Executor:** a bounded worker session that performs work only in its assigned
  delegation workspace.
- **Delegation workspace:** a Canto-managed Git worktree rooted at a recorded
  base commit and materialized according to task path policy.
- **Acceptance:** the orchestrator records that a specific executor result is
  suitable for promotion.
- **Promotion:** Canto applies the accepted, checksum-bound patch to the
  expected canonical repository after revalidating task policy and repository
  state.
- **Repository identity:** the canonical repository absolute path, Git common
  directory identity where available, initial `HEAD` commit, and configured
  remote URL metadata when present. Promotion verifies that the target still
  matches the recorded identity before applying an accepted patch.

## Architecture Decisions

### Existing concepts remain unchanged

The following remain authoritative in their current domains: Skill, Provider,
Tool, Artifact, Job, Approval, Registry, Policy, capability package, execution
plan, orchestration contract, `JobService`, and `StateStore`.

Delegation adds `DelegationTask`, `ExecutorProfile`, `ExecutorSession`,
`DelegationWorkspace`, `DelegationMessage`, `DelegationResult`,
`DelegationReview`, `PromotionDecision`, command records, and delegation events.
These models do not rename or overload existing runtime concepts.

`PromotionDecision` is an audit record for repository change promotion. It is
not a second Canto `Approval` object and does not authorize target-system
writes. Existing `Approval` remains authoritative for job and plan execution
gates.

### Delegation has its own service boundary

CP-1302 introduces a `DelegationService` that owns delegation lifecycle rules
and uses the injected `StateStore`. Delegation tasks are not Jobs and executor
work is not modeled as provider execution.

When Canto launches an executor in CP-1305, the launch adapter may reuse the
runner's process-limit, redaction, and event patterns. It must not route around
`DelegationService`, create a second promotion path, or silently turn executor
commands into Canto jobs.

### State and files

`StateStore` owns delegation records, deterministic status transitions,
messages, reviews, promotion decisions, command records, artifact metadata,
and ordered events. CP-1302 may add narrowly scoped protocol methods and SQL
tables; it must preserve existing store behavior and contract tests.

Large files live under:

```text
~/.canto/work/delegations/<task_id>/
    workspace/
    artifacts/
```

The database stores identifiers, checksums, relative paths, and lifecycle
metadata. Filesystem content is never a second source of lifecycle truth.

### Workspace isolation and context policy

Initial workspaces use Git worktrees with a unique task branch and recorded
base commit. Canto also configures per-worktree sparse checkout from the task's
allowed paths. Required repository metadata may be included explicitly, but a
path is never implicitly allowed.

Denied paths override allowed paths and are excluded from sparse checkout.
Untracked canonical files are not copied into the worktree. Symlinks and path
normalization are checked before context creation, artifact capture, and
promotion. Any denied-path change blocks completion and promotion.

This protects canonical state from accidental edits and limits supplied
context. It is not hostile-agent isolation: an executor process running as the
same operating-system user may still access other host paths outside Canto's
workspace controls.

### Executor profiles and harnesses

The first profile harnesses are:

- `manual`: Canto prepares instructions and the workspace; a human launches or
  addresses the executor separately.
- `codex_cli`: Canto prepares and optionally launches a configured Codex CLI
  executable in the delegated workspace.

Profiles record harness, executable/configuration, model provider, model,
launch mode, and default permissions. They contain no credentials. Model and
tool selection are provenance metadata, not execution identity.

Manual sessions always record command and network enforcement as
`manual_unverified`. Canto-launched sessions record the controls Canto actually
enforced. The system must not claim command or network enforcement it cannot
prove.

### Messages and executor protocol

Messages are durable Canto records independent of any vendor chat format.
Executors communicate with the orchestrator through task messages; direct
executor-to-executor communication is out of scope.

The minimum protocol is assignment, progress/blocker, revision request, and
done-for-review. Canto records executor-reported data separately from
Canto-observed workspace state so a claim such as “tests passed” is never
treated as verified without a matching command record or explicit waiver.

### Artifacts

Every done-for-review result must include Canto-generated:

- `proposal.diff`
- `changed_files.json`
- `commands.log`
- `summary.md`

Artifacts are captured from the workspace, stored outside it, hashed with
SHA-256, and bound to a result revision. Executor transcripts are optional and
must pass secret/reference redaction before persistence.

### Status model

The initial statuses are:

```text
draft -> assigned -> workspace_ready -> executor_working
executor_working -> executor_blocked | executor_done | failed | cancelled
executor_blocked -> executor_working | failed | cancelled
executor_done -> reviewing
reviewing -> revision_requested | accepted | rejected
revision_requested -> executor_working
accepted -> promoting | cancelled
promoting -> promoted | promotion_failed
promotion_failed -> promoting | rejected | cancelled
```

Terminal statuses are `promoted`, `rejected`, `cancelled`, and `failed`.
Transition validation belongs to `DelegationService`; callers cannot persist an
arbitrary status change directly.

### Review and revision

Each done-for-review capture creates an immutable result revision with artifact
checksums and the workspace commit/diff base. Reviews reference that revision.
A revision request preserves earlier results and reviews, returns the same task
workspace to working state, and requires a new result revision.

Acceptance binds the latest reviewed result revision. Any subsequent workspace
change invalidates acceptance and requires a new capture and review.

### Promotion

The initial promotion mechanism is patch application, not branch merge.
Promotion runs only after acceptance and verifies:

- canonical repository path and repository identity;
- expected base commit and current target `HEAD`;
- accepted result revision and artifact checksums;
- required artifacts and command requirements or explicit waivers;
- allowed/denied path policy;
- clean patch applicability using Git's check mode;
- no uncommitted canonical changes in affected paths.

Promotion first performs a non-mutating apply check. It then applies the exact
accepted patch and records the resulting changed files and Git state. Canto
does not commit, push, or merge automatically in MVP v1.1.

If mutation begins and promotion fails, Canto reports the partial state and
does not run destructive cleanup automatically. CP-1308 must minimize this
window and test rollback to the pre-apply state for failures Canto can induce
safely.

Promotion prefers atomic Git operations where available. If Canto can safely
restore the pre-promotion index and worktree state after an induced failure,
CP-1308 tests must prove that restoration. If restoration cannot be guaranteed,
the failure state is explicit and promotion stops before any further mutation.

### Command policy

Task scope stores structured command rules even if the first CLI accepts
command strings. Exact executable/argument matching is preferred over shell
prefix matching. Shell control operators, redirection, substitutions, and
commands that escape the workspace are denied for Canto-launched execution
unless a later packet adds explicit structured support.

Manual executors may report commands, but those records remain
`manual_unverified`. Promotion can require named commands to have a passing
Canto-observed record or an explicit orchestrator waiver with rationale.

### CLI and contract posture

MVP v1.1 is CLI-first under `canto delegate`. CP-1304 introduces the manual
workflow commands; later packets add launch, artifacts, review, promotion,
pool, conflict, and timeline views.

No delegation HTTP endpoints or orchestration response fields are added in
this workstream. Orchestration `contract_version` remains `1.0`. Authenticated
HTTP and MCP delegation belong to MVP v2.

## Required Invariants

- The orchestrator defines scope, assignment, review, and promotion decisions.
- Executors never work in or directly modify the canonical workspace.
- Executors cannot self-assign, self-accept, or self-promote.
- Only the latest accepted immutable result revision can be promoted.
- Denied paths override all other path rules and block promotion.
- Sparse checkout limits executor context but is not treated as a security
  boundary.
- Secrets and vault contents are never injected into executor context.
- Executor identity, harness/model provenance, workspace, messages, commands,
  artifacts, reviews, events, and promotion state are durable.
- Executor assertions are distinguished from Canto-observed evidence.
- Promotion never commits, pushes, or bypasses canonical-workspace checks.
- Delegation remains local-only and does not alter the frozen orchestration
  contract.

## Non-Goals

- Autonomous executor selection, scheduling, approval, or promotion.
- Executor access to Canto target-write operations or scoped secrets.
- Multi-user identity, authorization, ownership, or shared task boards.
- HTTP/MCP delegation endpoints or remote executor pools.
- Hostile-code isolation or a claim that worktrees are a security sandbox.
- Automatic dependency installation, Git commit/push, or remote repository
  mutation.
- Cross-executor messaging, consensus, or free-form collaboration.
- AI-generated capabilities or unreviewed provider code installation.

## Growth Boundaries

### MVP v1.1

CLI-first local coordination, manual and Codex CLI profiles, sparse Git
worktrees, durable artifacts/reviews/events, patch promotion, and local parallel
task visibility.

### MVP v2

Authenticated delegation HTTP/MCP endpoints, server-populated identity,
per-user ownership, role-gated review/promotion, team task visibility,
server-side scheduling, and stronger executor process isolation.

### MVP v3

Public-safe executor sandboxes, remote pools, signed executor profiles,
tenant quotas, abuse controls, and audit/incident-response posture.

## Packet Boundaries

1. CP-1302 defines models, transition rules, StateStore records, service
   persistence, and a placeholder command-record schema only. CP-1309 adds
   observed execution and test-result capture behavior.
2. CP-1303 creates and inspects sparse worktrees; it does not launch executors.
3. CP-1304 proves manual coordination and marks enforcement unverified.
4. CP-1305 adds Codex CLI availability, command preparation, and supervised
   launch without adding other harnesses.
5. CP-1306 creates immutable result revisions and review artifacts.
6. CP-1307 adds durable review/revision loops without promotion.
7. CP-1308 applies accepted patches without committing or pushing.
8. CP-1309 adds observed command/test records and promotion requirements.
9. CP-1310 adds parallel status views without automatic scheduling.
10. CP-1311 adds overlap/divergence detection and an orchestrator-controlled
    promotion queue.
11. CP-1312 adds restart-safe event timeline presentation.
12. CP-1313 documents and demonstrates manual and Codex CLI workflows.
13. CP-1314 proves the complete local flow with scripted executors and no
    external service.

## Workstream Acceptance

CP-1300 is complete when CP-1301 through CP-1314 satisfy all of the following:

- A fixture task completes create, assign, sparse workspace, work, capture,
  review, revision, acceptance, promotion, and restart-safe inspection.
- Promotion applies only the accepted checksum-bound patch and blocks denied
  paths, stale bases, overlap conflicts, missing artifacts, and unmet command
  requirements.
- Manual and Codex CLI profiles report accurate enforcement and provenance.
- Multiple tasks can be supervised concurrently without silent promotion
  conflicts.
- StateStore contract tests cover memory, SQLite, and retained Redis where the
  backend supports delegation records.
- No test requires network access, real credentials, a remote model, a remote
  registry, or a server deployment.
- Existing Canto manifests, jobs, plans, approvals, registry behavior, and
  orchestration contract tests remain compatible.

## CP-1301 Acceptance

- Maintainers can distinguish delegation from provider/job execution and from
  target-system write approval.
- Workspace context, command enforcement, artifact immutability, review, and
  promotion rules are explicit enough for CP-1302 through CP-1308.
- Local MVP v1.1, MVP v2, and MVP v3 boundaries are explicit.
- This architecture is suitable for the roadmap's placement of CP-1300 before
  CP-1201.
- This packet changes documentation only.
