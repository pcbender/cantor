# Canto Delegated Executor Workspaces

Status: proposed
Tier: Local MVP v1 extension
Proposed workstream: CP-1300
Purpose: add model-agnostic, tool-agnostic, auditable delegation and promotion across agent sessions.

---

## 1. Purpose

Canto now has a durable, local, single-user, write-capable runtime. The next local capability is delegated executor coordination: allowing a high-value orchestrator to assign bounded implementation work to one or more lower-cost executor agents, while Canto records the work, isolates the workspace, captures artifacts, and gates promotion.

This feature does not make Canto an autonomous agent. It makes Canto the local coordination, audit, artifact, and promotion layer for multiple agents.

The strategic model is:

```text
Human / Cantor
    |
    v
A: Orchestrator agent
    |
    | assigns bounded work
    v
B1, B2, B3...: Executor agents
    |
    | work in isolated delegated workspaces
    v
Diffs / tests / logs / artifacts
    |
    v
A reviews, revises, accepts, rejects, or promotes
```

Canto remains the governed runtime. Agents may reason, edit, test, and review, but promotion into trusted project state is explicit and auditable.

---

## 2. Problem

A frontier model running a Codex, Claude Code, ChatGPT, or similar session is expensive when it performs all implementation work directly. A lower-cost local or cloud model can often perform bounded coding, test-writing, documentation, analysis, or cleanup work.

However, simply asking a cheaper model for suggestions is not enough. If the orchestrator must manually rewrite or reapply all changes, the economic gain is weak.

The useful pattern is:

```text
Executor performs real work in an isolated workspace.
Executor produces changed files, diffs, logs, and test artifacts.
Orchestrator reviews the result instead of redoing the work.
Canto records and governs the delegation lifecycle.
```

Today Canto does not provide a first-class delegation task, executor session, workspace, artifact bundle, review state, or promotion flow for this pattern.

---

## 3. Product Thesis

Canto delegated executors are:

```text
model-agnostic,
tool-agnostic,
workspace-isolated,
artifact-producing,
review-gated,
and auditable.
```

Canto should not depend on one vendor's internal subagent system.

A delegated executor may be:

* A Codex CLI session backed by a frontier, cloud, or local OSS model.
* A Claude Code subagent or separate Claude Code session.
* An Ollama-backed local model harness.
* A Hermes/OpenClaw-style agent.
* A human-operated local worker.
* A future MCP-connected executor.

Canto coordinates the work without owning the model's reasoning loop.

---

## 4. Relationship to Existing Canto Architecture

This feature extends the existing model. It does not replace it.

Existing Canto concepts remain locked:

* Skill
* Provider
* Tool
* Artifact
* Job
* Approval
* Registry
* Policy
* Capability package
* Execution plan
* Orchestration contract
* StateStore

New concepts are added beside them:

* DelegationTask
* ExecutorProfile
* ExecutorSession
* DelegationWorkspace
* DelegationMessage
* DelegationResult
* DelegationReview
* PromotionDecision

Delegated executor work is not the same as a target-system write workflow. It is a local development/workspace workflow. A delegated executor may edit a delegated workspace and run allowed local commands, but it may not promote changes into canonical project state without review.

---

## 5. Definitions

### Cantor

The human authority. The Cantor approves direction, release decisions, destructive actions, and high-risk promotion.

### Orchestrator

The supervising agent or human session. The orchestrator scopes work, assigns tasks, reviews outputs, requests revisions, and accepts or rejects results.

Examples:

* Frontier Codex CLI session
* Claude Code session
* ChatGPT
* Human CLI operator
* Future MCP client

### Executor

A delegated worker agent or model session that performs bounded work in an isolated workspace.

Examples:

* Codex CLI using `--oss` with a local Ollama model
* Claude Code subagent
* Claude Code separate session
* Hermes agent
* OpenClaw-connected worker
* Human contractor or local shell worker

### Delegation Workspace

A Canto-managed isolated workspace where the executor may read and write files within declared boundaries.

Initial implementation should use Git worktrees.

### Promotion

The act of applying accepted executor output into the canonical repo/workspace. Promotion is review-gated and recorded.

---

## 6. Core Use Case

A frontier Codex session is supervising repository `X`.

A local Codex CLI session backed by a local model is available as an executor.

The orchestrator says:

```text
Look at the spec and implement CP-1302. Work only in the delegated worktree.
Run the required tests. Tell me when the diff is ready for review.
```

The executor works in its own worktree, edits files, runs tests, and reports:

```text
Done. Diff ready. Tests pass.
```

The orchestrator reviews the diff and says:

```text
Revise the schema names and add failure-state tests.
```

The executor revises and reports again.

Eventually the orchestrator accepts the result, promotes the diff, runs final tests, and tells the human:

```text
CP-1302 complete. Moving on to CP-1303.
```

Canto records the task, messages, workspace, changed files, commands, logs, artifacts, reviews, and promotion decision.

---

## 7. Non-Goals

This feature does not provide:

* Autonomous approval.
* Autonomous promotion into trusted project state.
* Executor self-assignment without orchestrator scope.
* Multi-user authentication or authorization.
* Public server execution.
* Remote registry trust.
* Untrusted-code sandboxing strong enough for hostile code.
* Marketplace behavior.
* Automatic dependency installation.
* Unreviewed commits.
* Unreviewed target-system mutation.
* Agent-to-agent free-for-all communication.

The local MVP version assumes trusted local code and a single-user machine, consistent with MVP v1.

---

## 8. Required Invariants

* The orchestrator owns task scope and review.
* Executors work only in delegated workspaces.
* Executors do not directly modify the canonical workspace.
* Executors do not self-promote their work.
* Promotion requires an explicit orchestrator decision.
* Canto records executor identity, model/tool profile, workspace, changed files, commands, artifacts, review, and promotion state.
* Delegated workspace artifacts are durable through the StateStore.
* Denied paths are never included in executor context.
* Secrets are never injected into executor prompts or workspaces unless explicitly allowed by a future scoped secret policy.
* Executor output is treated as untrusted until reviewed.
* Local MVP implementation must not require a server deployment.

---

## 9. Architecture

```text
Human / Cantor
    |
    v
Orchestrator Session
    |
    | create delegation task
    v
Canto Delegation Service
    |
    | create isolated workspace
    | launch or address executor
    v
Executor Session
    |
    | edits files
    | runs allowed commands
    | writes result artifacts
    v
Delegation Result
    |
    v
Orchestrator Review
    |
    +--> request revision
    |
    +--> reject
    |
    +--> accept
             |
             v
       Promotion Queue
             |
             v
       Canonical Workspace
```

---

## 10. Local MVP Shape

The first implementation should be local-only and conservative.

Minimum local feature set:

* One orchestrator session.
* One or more configured executor profiles.
* Git worktree-based delegated workspaces.
* Manual or CLI-launched executor sessions.
* File-based or StateStore-backed message exchange.
* Diff/test/log/artifact capture.
* Review states.
* Apply/promote accepted diffs.
* Full audit trail.

This is enough to prove the economic pattern without building a server or multi-user system.

---

## 11. Executor Profiles

An ExecutorProfile describes how to address or launch an executor.

Example:

```json
{
  "executor_id": "local-gemma-codex",
  "name": "Local Gemma Codex",
  "harness": "codex_cli",
  "model_provider": "ollama",
  "model": "gemma4",
  "mode": "local",
  "default_permissions": {
    "can_edit_workspace": true,
    "can_run_commands": true,
    "can_access_network": false,
    "can_access_secrets": false,
    "can_promote": false
  }
}
```

Initial supported harnesses:

* `manual`
* `codex_cli`

Future harnesses:

* `claude_code`
* `ollama_direct`
* `openai_compatible_agent`
* `anthropic_agent`
* `hermes`
* `openclaw`
* `mcp_executor`

---

## 12. DelegationTask Schema

A DelegationTask is the unit of assigned executor work.

Example:

```json
{
  "task_id": "delegate_20260611_001",
  "title": "Implement CP-1302 schemas",
  "status": "assigned",
  "created_by": "orchestrator",
  "assigned_executor": "local-gemma-codex",
  "repo": {
    "path": "/home/user/src/canto",
    "base_ref": "main"
  },
  "workspace": {
    "mode": "git_worktree",
    "branch": "delegate/CP-1302-schemas",
    "path": ".canto/work/delegations/delegate_20260611_001/workspace"
  },
  "scope": {
    "allowed_paths": [
      "canto/core/",
      "canto/models/",
      "tests/"
    ],
    "denied_paths": [
      ".env",
      ".git/",
      "secrets/",
      ".canto/vault/"
    ],
    "allowed_commands": [
      "pytest tests/",
      "ruff check canto tests"
    ],
    "network": "disabled",
    "secrets": "disabled"
  },
  "instructions": {
    "summary": "Define DelegationTask, ExecutorSession, and DelegationResult models.",
    "acceptance": [
      "Schemas validate representative examples.",
      "No public orchestration contract fields are changed.",
      "Tests cover completed, failed, revision_requested, accepted, and rejected states."
    ]
  },
  "artifacts_required": [
    "proposal.diff",
    "changed_files.json",
    "commands.log",
    "summary.md"
  ]
}
```

---

## 13. Delegation Status Model

Initial statuses:

```text
draft
assigned
workspace_ready
executor_working
executor_blocked
executor_done
reviewing
revision_requested
accepted
rejected
promoting
promoted
promotion_failed
cancelled
failed
```

Terminal statuses:

```text
promoted
rejected
cancelled
failed
```

A task may cycle between:

```text
executor_done -> reviewing -> revision_requested -> executor_working
```

until accepted or rejected.

---

## 14. DelegationMessage Schema

Messages preserve the A/B conversation without depending on a specific chat system.

Example assignment message:

```json
{
  "message_id": "msg_001",
  "task_id": "delegate_20260611_001",
  "from": "orchestrator",
  "to": "local-gemma-codex",
  "message_type": "assignment",
  "body": "Read the spec and implement the schema models. Work only in the delegated workspace. Run tests before marking done.",
  "created_at": "2026-06-11T10:00:00Z"
}
```

Example executor response:

```json
{
  "message_id": "msg_002",
  "task_id": "delegate_20260611_001",
  "from": "local-gemma-codex",
  "to": "orchestrator",
  "message_type": "done_for_review",
  "body": "Implemented schemas and tests. pytest passed.",
  "artifacts": [
    "proposal.diff",
    "commands.log",
    "summary.md"
  ],
  "created_at": "2026-06-11T10:32:00Z"
}
```

---

## 15. DelegationResult Schema

A DelegationResult captures what the executor produced.

Example:

```json
{
  "task_id": "delegate_20260611_001",
  "status": "executor_done",
  "executor": {
    "executor_id": "local-gemma-codex",
    "harness": "codex_cli",
    "model_provider": "ollama",
    "model": "gemma4"
  },
  "workspace": {
    "branch": "delegate/CP-1302-schemas",
    "path": ".canto/work/delegations/delegate_20260611_001/workspace"
  },
  "changed_files": [
    "canto/models/delegation.py",
    "tests/test_delegation_models.py"
  ],
  "commands_run": [
    {
      "command": "pytest tests/test_delegation_models.py",
      "status": "passed",
      "exit_code": 0
    }
  ],
  "artifacts": [
    {
      "name": "proposal.diff",
      "type": "diff",
      "sha256": "..."
    },
    {
      "name": "summary.md",
      "type": "summary",
      "sha256": "..."
    },
    {
      "name": "commands.log",
      "type": "log",
      "sha256": "..."
    }
  ],
  "warnings": [],
  "recommended_next_action": "orchestrator_review"
}
```

---

## 16. Review and Promotion

The orchestrator may make one of five decisions:

```text
request_revision
accept
reject
promote
cancel
```

Acceptance means the orchestrator approves the executor's result.

Promotion means Canto applies the accepted diff or merge into the canonical workspace.

Promotion must verify:

* The task is accepted.
* The workspace still exists.
* The base reference is known.
* The diff applies cleanly.
* Denied paths were not modified.
* Required artifacts exist.
* Required commands have passed, or the orchestrator explicitly waives them.
* No secret or denied-path files are included in the diff.
* The promotion target is the expected canonical repo.

Promotion produces:

* Promotion event.
* Applied diff artifact.
* Merge/apply log.
* Final changed files list.
* Optional final test log.

---

## 17. Workspace Isolation

Initial implementation uses Git worktrees.

A DelegationWorkspace should have:

* Unique task ID.
* Unique branch name.
* Recorded base commit.
* Allowed path policy.
* Denied path policy.
* Workspace lifecycle events.
* Cleanup behavior.
* Artifact extraction.

Canto should be able to report:

```text
which task created this workspace,
which executor used it,
which files changed,
which commands ran,
which result was accepted,
and whether it was promoted.
```

---

## 18. Command Policy

Allowed commands are task-scoped.

Initial command policy may be simple string-prefix or exact-command matching. Later versions may use structured command policies.

Examples:

```json
{
  "allowed_commands": [
    "pytest tests/",
    "ruff check canto tests",
    "python -m compileall canto"
  ],
  "denied_commands": [
    "rm -rf",
    "curl",
    "wget",
    "ssh",
    "scp",
    "git push"
  ]
}
```

Local MVP enforcement may be advisory for externally managed executor sessions. When Canto launches the executor, enforcement must be active. When a human manually launches B, Canto must clearly mark enforcement as `manual_unverified`.

---

## 19. Storage

Delegation state is stored in the local durable StateStore.

The StateStore should persist:

* Delegation tasks.
* Executor profiles.
* Executor sessions.
* Delegation messages.
* Workspace metadata.
* Status transitions.
* Review decisions.
* Promotion decisions.
* Artifact metadata.
* Command records.

Large artifact files remain on the filesystem under Canto-managed delegation directories.

Example path:

```text
.canto/work/delegations/<task_id>/
    workspace/
    artifacts/
        proposal.diff
        changed_files.json
        commands.log
        summary.md
        promotion.log
```

---

## 20. Events

Delegation emits ordered events:

```text
delegation.created
delegation.assigned
delegation.workspace_created
delegation.executor_started
delegation.message_recorded
delegation.command_recorded
delegation.artifact_created
delegation.executor_done
delegation.review_started
delegation.revision_requested
delegation.accepted
delegation.rejected
delegation.promotion_started
delegation.promoted
delegation.promotion_failed
delegation.cancelled
delegation.failed
```

Events should be visible through CLI first. HTTP exposure can come later.

---

## 21. CLI Surface

Initial CLI commands:

```text
canto delegate create
canto delegate list
canto delegate show <task_id>
canto delegate message <task_id>
canto delegate mark-working <task_id>
canto delegate mark-done <task_id>
canto delegate review <task_id>
canto delegate revise <task_id>
canto delegate accept <task_id>
canto delegate reject <task_id>
canto delegate promote <task_id>
canto delegate artifacts <task_id>
```

Optional executor launch command:

```text
canto delegate launch <task_id> --executor local-gemma-codex
```

Optional helper:

```text
canto delegate diff <task_id>
```

---

## 22. HTTP and MCP Posture

Local MVP implementation may start CLI-first.

HTTP endpoints are deferred unless needed for MCP or external orchestrators.

Likely future endpoints:

```text
POST /delegations
GET /delegations
GET /delegations/{task_id}
POST /delegations/{task_id}/messages
POST /delegations/{task_id}/review
POST /delegations/{task_id}/promote
GET /delegations/{task_id}/events
GET /delegations/{task_id}/artifacts
```

MVP v2 should expose this through authenticated HTTP and MCP, with server-populated identity and per-user isolation.

---

## 23. Safety and Trust

Local MVP delegated executors are trusted-local-code-adjacent, not hostile-code isolated.

Canto must be honest about this:

* Worktree isolation protects the canonical workspace from accidental edits.
* It does not make arbitrary executor code safe.
* Strong sandboxing belongs to future MVP v2/v3 work.
* Denied paths and command policy reduce risk but are not a complete hostile-agent boundary unless Canto launches and supervises the executor in a controlled sandbox.

---

## 24. Future Growth Path

### Local MVP extension

* CLI-first delegation.
* Git worktree isolation.
* Codex CLI executor profile.
* Manual executor profile.
* Diff/log/artifact capture.
* Review and promotion flow.

### MVP v2

* Authenticated HTTP delegation endpoints.
* Multi-user executor ownership.
* Team-visible task board.
* MCP adapter.
* Server-side executor scheduling.
* Role-based review and promotion.
* Stronger process isolation.

### MVP v3

* Public server-safe executor sandboxing.
* Remote executor pools.
* Signed executor profiles.
* Untrusted executor isolation.
* Quotas, abuse controls, and tenant boundaries.
* Public audit and incident-response posture.

---

# Work Packets

## CP-1301 — Delegated Executor Scope and Architecture

Goal: freeze the local MVP delegated executor design.

Deliverables:

* Architecture note.
* Invariants.
* Non-goals.
* Local/MVP v2/MVP v3 growth boundaries.
* Glossary: orchestrator, executor, workspace, promotion.
* Acceptance criteria for the CP-1300 workstream.

Acceptance:

* Maintainers can tell what this feature is and what it is not.
* No existing Canto concepts are renamed or replaced.
* Scope is local-first and does not require server deployment.

---

## CP-1302 — Delegation Data Models and StateStore Records

Goal: define and persist the core delegation objects.

Deliverables:

* DelegationTask model.
* ExecutorProfile model.
* ExecutorSession model.
* DelegationMessage model.
* DelegationResult model.
* DelegationReview model.
* PromotionDecision model.
* StateStore persistence methods.
* Unit tests.

Acceptance:

* Delegation objects can be created, updated, queried, and evented through the local StateStore.
* Status transitions are deterministic and validated.
* Invalid transitions are rejected.

---

## CP-1303 — Delegation Workspace Lifecycle

Goal: create isolated delegated workspaces.

Deliverables:

* Git worktree workspace implementation.
* Workspace creation from base ref.
* Workspace metadata persistence.
* Workspace cleanup command.
* Changed-file detection.
* Denied-path detection.
* Tests with local fixture repos.

Acceptance:

* A task can create a unique worktree.
* Canto records base commit, branch, and workspace path.
* Canto can detect changed files and denied-path modifications.

---

## CP-1304 — Manual Executor Workflow

Goal: support human-launched or externally launched executor sessions before automated launching.

Deliverables:

* CLI instructions for executor B.
* Task assignment message generation.
* Manual status update commands.
* Manual done-for-review flow.
* Artifact collection from workspace.
* Enforcement status marked as `manual_unverified`.

Acceptance:

* A human can run A and B as separate Codex sessions and use Canto to coordinate the task.
* Canto captures messages, status, diff, logs, and summary artifacts.

---

## CP-1305 — Codex CLI Executor Profile

Goal: add a first automated executor harness for Codex CLI.

Deliverables:

* ExecutorProfile for `codex_cli`.
* Config for executable path, model, provider flags, working directory, and launch mode.
* Initial support for local OSS/Ollama-backed Codex.
* Launch command generation.
* Captured transcript/log path.
* Availability check.

Acceptance:

* Canto can prepare or launch a Codex CLI executor session for a delegation task.
* Failure to find Codex or the requested model produces a clear error.
* The executor works only in the delegated workspace.

---

## CP-1306 — Delegation Artifact Capture

Goal: capture reviewable output from executor work.

Deliverables:

* `proposal.diff`.
* `changed_files.json`.
* `commands.log`.
* `summary.md`.
* Optional executor transcript capture.
* SHA-256 metadata.
* Artifact listing CLI.

Acceptance:

* Every done-for-review task has a diff artifact and changed-file manifest.
* Artifact hashes are stored.
* Artifacts survive process restart.

---

## CP-1307 — Review and Revision Flow

Goal: allow the orchestrator to review, reject, or request revisions.

Deliverables:

* Review command.
* Revision request command.
* Review state transitions.
* Review comments/messages.
* Revision cycle support.
* Tests for repeated revision loops.

Acceptance:

* A task can cycle through done-for-review, revision-requested, working, and done-for-review again.
* All review messages and decisions are durable.

---

## CP-1308 — Promotion Flow

Goal: apply accepted executor work to the canonical workspace.

Deliverables:

* Accept command.
* Promote command.
* Clean-apply check.
* Denied-path promotion check.
* Required artifact check.
* Apply/merge log.
* Promotion event.
* Promotion failure handling.

Acceptance:

* Accepted diffs can be promoted.
* Rejected or unreviewed diffs cannot be promoted.
* Promotion failure leaves canonical workspace unchanged or clearly reports partial state.

---

## CP-1309 — Command Recording and Test Result Capture

Goal: record executor commands and test results.

Deliverables:

* Command record model.
* CLI for recording command results.
* Optional command wrapper for launched executors.
* Test result summary extraction where practical.
* Command artifacts.

Acceptance:

* Done-for-review tasks show which commands were run and their exit status.
* Promotion can require specific commands to have passed or require an explicit waiver.

---

## CP-1310 — Executor Pool Status and Parallel Task View

Goal: support multiple executor sessions in parallel.

Deliverables:

* Executor list/status view.
* Delegation task list grouped by executor/status.
* Conflict-risk display based on changed/allowed paths.
* Basic blocked/idle/working/done states.
* CLI summary view.

Acceptance:

* A local user can supervise multiple executor tasks at once.
* Canto shows which executor is doing what, in which workspace, against which base ref.

---

## CP-1311 — Conflict Detection and Merge Queue

Goal: prevent multi-executor chaos during promotion.

Deliverables:

* Base-ref divergence detection.
* Changed-file overlap detection.
* Promotion queue.
* Rebase/review-needed status.
* Conflict reporting.

Acceptance:

* Canto warns when two accepted tasks modify overlapping files.
* Canto refuses unsafe promotion without review.
* The orchestrator can choose promotion order.

---

## CP-1312 — Delegation Events and Timeline

Goal: make the delegation lifecycle observable.

Deliverables:

* Ordered delegation events.
* CLI timeline view.
* Event persistence.
* Artifact links in timeline.
* Restart-safe event display.

Acceptance:

* A user can inspect what happened in a delegation task after restart.
* The timeline includes assignment, workspace creation, messages, artifacts, reviews, and promotion.

---

## CP-1313 — Documentation and Demo

Goal: document and demonstrate the local two-agent workflow.

Deliverables:

* User guide.
* Architecture guide.
* Safety notes.
* Example: A frontier Codex orchestrator + B local Codex OSS executor.
* Example: two parallel executors.
* Troubleshooting.

Acceptance:

* A developer can follow the docs to run the A/B local workflow.
* The demo proves executor worktree edits, review, revision, accept, and promotion.

---

## CP-1314 — End-to-End Local Delegated Executor Test

Goal: prove the feature as a local MVP.

Deliverables:

* Fixture repo.
* Mock executor or scripted executor.
* Full create → assign → workspace → edit → artifact → review → revise → accept → promote flow.
* Restart coverage.
* Conflict coverage.

Acceptance:

* End-to-end tests pass without external services.
* Feature works without multi-user server, remote registry, or public sandboxing.

---

# Open Questions

## OQ-1 — Should CP-1300 be part of MVP v1 or a new MVP v1.1?

Recommendation: call it MVP v1.1 or Local Delegation Extension. MVP v1 is already complete. This avoids rewriting the completed release while still building on it.

## OQ-2 — Should the first implementation be CLI-only?

Recommendation: yes. Start CLI-first. HTTP/MCP can follow once the local state model is proven.

## OQ-3 — Should Canto launch executor sessions or only coordinate manually launched sessions first?

Recommendation: implement manual coordination first, then Codex CLI launch. Manual mode proves the protocol without fighting terminal/session automation too early.

## OQ-4 — Should executor sessions be allowed to run commands directly?

Recommendation: yes, but start with recorded/advisory enforcement unless Canto launches the executor. Full enforcement requires Canto to supervise the process.

## OQ-5 — Should executors be allowed to call Canto skills?

Recommendation: not in the first local version. Allow executors to propose Canto calls. The orchestrator executes them. Scoped executor Canto access can come later.

## OQ-6 — Should promotion apply patches or merge branches?

Recommendation: support patch apply first. Git branch merge can follow. Patch apply is easier to validate and audit.

## OQ-7 — Should executor context include full repo access?

Recommendation: workspace may contain the full repo, but task scope must declare allowed and denied paths. Denied-path changes block promotion.

## OQ-8 — How strong must sandboxing be?

Recommendation: be explicit that local MVP delegation is not hostile-agent isolation. Worktree isolation and command policy are safety rails, not a complete security sandbox.

## OQ-9 — Should executor output be represented as Canto artifacts or a new object type?

Recommendation: both. DelegationResult is the lifecycle object; diff/log/summary files are artifacts.

## OQ-10 — How does this relate to Claude Code subagents?

Recommendation: treat Claude Code subagents as one possible executor harness in the future. Canto should coordinate across tools rather than copy vendor-specific subagent internals.

## OQ-11 — Should multiple executors communicate with each other?

Recommendation: no for the first version. Executors communicate with the orchestrator through Canto. Cross-executor communication creates coordination risk and should be deferred.

## OQ-12 — Should Canto decide which executor gets which task?

Recommendation: no for the first version. The orchestrator assigns tasks. Later versions may add executor recommendation or scheduling.

## OQ-13 — Should this use the existing JobService?

Recommendation: not for the first implementation of delegation state itself. Delegation is a coordination workflow, not a provider execution job. However, if Canto launches executor processes, the launch path should eventually share resource-limit and event patterns with JobService.

## OQ-14 — Does this change the orchestration API contract?

Recommendation: not initially. CLI-first local delegation does not change the frozen orchestration contract. HTTP delegation endpoints should carry their own additive contract surface later.

## OQ-15 — What is the minimum success demo?

Recommendation:

A frontier orchestrator session creates a delegation task. A local Codex OSS/Ollama executor works in a delegated worktree, edits files, runs tests, marks done, and produces a diff. The orchestrator requests one revision, accepts the result, promotes it, and Canto shows the full durable timeline and artifacts after restart.
