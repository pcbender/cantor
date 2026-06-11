# CP-1201 — Delegated Executor UX Architecture and Design

Status: approved and complete

## Purpose

MVP v1.1 proved the delegated-executor architecture: an orchestrator can define
a bounded task, prepare a sparse Git worktree, launch a manual or Codex CLI
executor, capture immutable evidence, request revisions, review a result, and
promote the exact accepted patch. A real `gpt-5.4-mini` smoke test also proved
the cloud path while leaving the canonical repository unchanged.

MVP v1.2 does not redesign that architecture. It makes the existing local
workflow understandable and economical enough for daily use.

## Architecture Lock

The following remain canonical:

- `DelegationTask` and `DelegationService` own task lifecycle transitions.
- `StateStore` owns durable task, profile, workspace, session, message, command,
  result, review, queue, promotion, and event records.
- Git worktrees own isolated executor workspace state.
- `DelegationResult` revisions and artifact checksums own reviewable evidence.
- `DelegationReview` owns revision, acceptance, and rejection decisions.
- `PromotionDecision` and the existing promotion service own canonical patch
  application.
- Executors cannot assign, accept, queue, or promote their own work.
- Delegation remains separate from Job/provider execution and from the frozen
  orchestration HTTP contract.

MVP v1.2 may add additive metadata and read-only projection models. It must not
add another lifecycle, executor path, approval object, or promotion path.

## Global Runtime and Repository Awareness

**Canto is globally installed and repo-aware. Repositories are bootstrapped,
not installed into.**

The target layout is:

```text
Global executable:
  /usr/local/bin/canto
  ~/.local/bin/canto

Global user state:
  ~/.canto/state.sqlite
  ~/.canto/vault/
  ~/.canto/installed/
  ~/.canto/work/
  ~/.canto/config/

Repository-local intent:
  <repo>/.canto/repo.toml
  <repo>/.canto/policy.toml

Delegation workspace:
  ~/.canto/work/delegations/<task_id>/workspace/
```

The Python environment or wheel installation may vary, but operational commands
must not require Canto source files to be copied into each repository.

### Global state

Durable tasks, profiles, sessions, results, reviews, approvals, credentials,
installed capabilities, and work files remain under the user's global
`~/.canto` home. They are never written into repository-local configuration.

The current implementation stores SQLite state at
`~/.canto/state/canto.db`. CP-1315 owns a compatibility-reviewed migration to
the target `~/.canto/state.sqlite` path. It must detect existing state, migrate
or continue it atomically, and refuse ambiguous dual databases. It must not
silently initialize an empty database while legacy durable state exists.

### Repository-local intent

`canto repo init` creates only non-secret, reviewable repository configuration:

- `.canto/repo.toml` identifies the bootstrapped repository and format version;
- `.canto/policy.toml` stores repository defaults and constraints for delegation
  scope, commands, and executor behavior.

These files contain no credentials, vault material, task records, transcripts,
patches, command output, or executor tokens. They may be committed with the
repository. Repository policy can narrow global/profile defaults but cannot
weaken Canto's hard safety rules or an explicit task denial.

### Repository identity

Bootstrap assigns a stable local `repo_id`. Runtime identity additionally
records and verifies:

- canonical repository absolute path;
- Git common-dir identity;
- base and initial `HEAD` commits where applicable;
- configured remote URL metadata when present.

Delegation worktrees remain under global Canto work storage and are tied back to
this repository identity and the exact task base commit. Promotion revalidates
both the bootstrapped repository identity and existing Git identity checks.
Moving a repository requires an explicit relink/update operation; path changes
are not accepted silently.

### Bootstrap behavior

Repo-scoped commands search upward from the current directory for
`.canto/repo.toml`. In a Git repository without valid Canto configuration they
fail before mutation with a concise bootstrap instruction:

```text
This Git repository is not initialized for Canto.
Run: canto repo init
```

Non-repository commands such as global health, installed capability listing,
and executor-profile management remain usable outside a bootstrapped repo.
Commands with an explicit `--repo` path resolve that repository and enforce the
same bootstrap rule.

## Current Journey

The current happy path requires the operator to:

1. Register or recreate an executor profile.
2. Create a task and copy a generated task ID from JSON.
3. Assign the profile.
4. Prepare a worktree.
5. Launch or manually start an executor.
6. Inspect raw JSON and filesystem logs.
7. Capture a result.
8. Read `changed_files.json`, `proposal.diff`, and command records separately.
9. Accept or request a revision.
10. Add the accepted result to the queue.
11. Interpret string blockers.
12. Promote explicitly.

The lifecycle is sound, but routine questions require too much raw-state
inspection:

- What is active and what needs my attention?
- Which profile and prompt produced this revision?
- Did tests actually pass, or were they only reported?
- Is this result safe to accept or promote?
- Why is promotion blocked and what is the safe next action?
- How does one executor/prompt variant compare with another?

## Interaction Model

### Command families

Existing commands remain compatible. MVP v1.2 organizes new UX under these
surfaces:

```text
canto delegate dashboard [TASK_ID] [--active] [--json]
canto delegate profile list|show|check|save
canto delegate compare create|show
canto delegate review-summary TASK_ID [--revision N] [--json]
canto delegate conflict TASK_ID [--json]
canto demo delegation [OPTIONS]
```

Mutating commands such as `launch`, `capture`, `revise`, `accept`, `queue-add`,
and `queue-promote` remain explicit. A dashboard or summary never performs the
displayed next action.

### Output convention

New MVP v1.2 commands default to concise human-readable terminal output and
offer `--json` backed by typed projection models. Existing commands that
already emit JSON keep their output for compatibility.

Human output follows a stable hierarchy:

1. Identity and status
2. Attention or blocker summary
3. Executor/session provenance
4. Result and command evidence
5. Repository and workspace state
6. Valid next operator actions
7. Artifact/log locations

Color may enhance output when attached to a terminal, but labels and status
must remain understandable without color.

## Dashboard Contract

The dashboard is a read-only projection assembled from existing services and
records. It is not persisted as a second task view.

### Compact task list

Each row shows:

- short task ID and title;
- lifecycle status;
- executor profile and harness;
- repository basename;
- latest and accepted result revisions;
- attention marker (`working`, `review`, `blocked`, `ready`, or `terminal`);
- one deterministic next-action label;
- updated timestamp.

Default ordering is attention priority, then `updated_at` descending, then full
task ID. `--active` excludes terminal tasks. JSON ordering is identical.

### Task detail

The detail view shows:

- full task, repository identity, scope, and denied paths;
- assigned profile and current availability;
- workspace and base commit;
- sessions and launches, including model/provider, prompt variant, exit state,
  duration, and token metadata when available;
- latest result, review status, changed-file count, patch statistics, and
  artifact checksum state;
- command evidence grouped as passed, failed, reported, missing, and waived;
- queue position and structured blockers;
- canonical `HEAD`/dirty affected-path readiness;
- valid next commands derived from the lifecycle and evidence.

`next_actions` is advisory projection data. Services remain authoritative and
must revalidate every requested mutation.

## Executor Profiles and Presets

### Distinction

- A **preset** is declarative local configuration that reduces repeated flags.
- An **executor profile** is the durable resolved configuration identified by
  `executor_id` and used for assignment.
- A **session launch snapshot** records the exact resolved executable, model,
  provider, arguments, permissions, timeout, and prompt used for provenance.

Presets contain no credentials or tokens. Codex authentication remains owned by
the Codex CLI; Ollama model/runtime state remains owned by Ollama.

### Storage

User presets live in:

```text
~/.canto/config/executors.yaml
```

The file is configuration, not lifecycle truth. Saving or selecting a preset
resolves it into the existing durable `ExecutorProfile` record. Built-in
examples provide conservative defaults for:

- `manual`
- `codex-cloud`
- `codex-ollama`

Built-ins are templates and do not assert model availability.

### Precedence

Resolution order, highest precedence first:

1. Explicit command-line launch override
2. Explicit task/session override
3. Saved executor profile
4. Named preset
5. Built-in conservative default

Overrides may change model, timeout, or approved safe arguments. They cannot
enable secrets, network, paths, commands, or permissions denied by the task.
Task scope is always the upper bound. The resolved launch snapshot is durable so
later configuration edits do not rewrite provenance.

### Preflight

`profile check` is non-mutating and reports executable availability, supported
harness, model/provider configuration, authentication/runtime hints, and the
effective command. It must not make a cloud model request or pull a local model.

## Session Prompts and A/B Comparison

### Prompt composition

The rendered executor prompt has ordered sections:

1. Locked Canto safety instructions
2. Task title and base instructions
3. Revision feedback, when present
4. Named prompt-variant supplement, when present
5. Allowed/denied paths and command policy
6. Completion/reporting instructions

Every rendered prompt is stored per launch. A prompt variant supplements the
task; it cannot replace locked safety or scope sections.

### Isolation decision

A/B variants do not run sequentially in one mutable task worktree. They run as
**sibling delegation tasks grouped by an additive `comparison_id`**:

- each sibling is a normal `DelegationTask` using the existing lifecycle;
- each records the same canonical repository identity, base commit, scope, and
  base instructions at comparison creation;
- each receives its own Git worktree, branch, sessions, results, reviews, and
  promotion state;
- variant name and prompt supplement are additive task/session metadata;
- comparison is read-only and never selects, accepts, or promotes a winner.

This keeps lifecycle and promotion rules unchanged and prevents one variant's
edits from influencing another. Comparison rejects results with different
canonical repositories, base commits, or scopes rather than guessing.

The comparison view shows changed files, patch statistics, commands, exit
state, runtime, token metadata when available, review state, and artifact paths.
If an operator chooses a variant, they review and accept that sibling task
normally. Other variants remain ordinary tasks and may be rejected or retained
for evidence.

## Local Ollama Boundary

MVP v1.2 reuses the existing `codex_cli` harness rather than adding an Ollama-
specific executor lifecycle. The resolved profile uses Codex CLI local-provider
arguments equivalent to:

```text
codex exec --oss --local-provider ollama --model MODEL ...
```

Requirements:

- `model_provider` is `ollama` and provenance records the local model name.
- `--oss` and `--local-provider ollama` are mandatory for this preset.
- No cloud fallback is permitted.
- Preflight checks local Codex and Ollama availability without pulling a model.
- Automated tests use a scripted executable; no test requires Ollama or a
  downloaded model.
- The optional real smoke test uses a disposable repository and stops at
  `reviewing` by default.

If Codex CLI local-provider behavior proves insufficient during CP-1205, a
separate process adapter may be proposed for review. It must still create the
same sessions, command evidence, results, reviews, and promotion path; CP-1205
may not silently add it.

## Review Summary Contract

`review-summary` is a read-only projection over immutable result artifacts,
command records, reviews, workspace metadata, and current canonical Git state.

It reports:

- task, result revision, producing session/launch/profile, and prompt variant;
- artifact presence and checksum validation;
- changed files and textual/binary patch statistics;
- passed, failed, reported, missing, and waived command requirements;
- denied/out-of-scope and symlink validation state;
- captured base versus canonical `HEAD`;
- dirty affected canonical paths;
- current review and queue state;
- `acceptance_ready` and `promotion_ready` booleans;
- structured blocker codes and safe next actions.

The summary cannot make acceptance or promotion authoritative. Acceptance and
promotion repeat their existing checks at mutation time.

## Conflict Explanation Contract

String-only blockers become typed projection entries while existing service
errors remain compatible. Each blocker has:

```json
{
  "code": "queued_path_overlap",
  "severity": "blocking",
  "message": "Task B overlaps task A in src/parser.py",
  "related_task_id": "task_A",
  "paths": ["src/parser.py"],
  "expected": null,
  "actual": null,
  "safe_actions": ["revise", "reject", "manual_reconcile"]
}
```

Initial codes:

- `queued_path_overlap`
- `canonical_head_diverged`
- `canonical_affected_path_dirty`
- `artifact_missing`
- `artifact_checksum_changed`
- `required_command_missing`
- `required_command_failed`
- `workspace_changed_after_capture`
- `result_not_latest`
- `promotion_rollback_failed`
- `repository_identity_changed`

Explanations never run merge, rebase, reset, cleanup, dequeue, rejection, or
retry automatically. Cross-repository tasks cannot conflict by path alone.

## One-Command Demo Contract

The proposed command is:

```text
canto demo delegation [--executor scripted|codex-cloud|codex-ollama]
                      [--model MODEL] [--promote] [--keep]
```

Defaults:

- `scripted` executor;
- no network or credentials;
- disposable Git repository and isolated Canto home;
- complete flow through `reviewing`;
- no promotion unless `--promote` is explicit;
- cleanup on successful completion unless `--keep` is set;
- preserve state and print recovery/cleanup paths on failure.

Cloud and Ollama modes require explicit selection and print quota/runtime
warnings before launch. Cloud mode requires authenticated Codex but no Canto-
stored credential. Ollama mode never falls back to cloud. The command prints a
human summary plus repository, workspace, artifact, and timeline locations.

The existing shell demo remains supported until this command reaches parity.

## Compatibility and Migration

- Existing task, profile, session, result, review, queue, promotion, and event
  records remain valid.
- CP-1315 introduces repo-local TOML configuration additively and migrates the
  global SQLite location without losing or forking existing state.
- New JSON fields are optional with defaults. Existing SQLite records require no
  destructive migration.
- Comparison grouping may require an additive StateStore record/table or
  optional task fields; CP-1203 must choose the smallest representation.
- Existing `add-codex`, `show`, `status`, `pool`, `timeline`, and mutation
  commands remain available. New profile/dashboard commands may delegate to
  their services rather than duplicate behavior.
- Delegation adds no HTTP fields or endpoints. Orchestration
  `contract_version` remains `1.0`.
- Human-readable defaults apply only to new MVP v1.2 commands unless a later
  compatibility-reviewed packet adds output flags to existing commands.

## Packet Ownership

- CP-1315 owns global/repo path resolution, repo bootstrap configuration,
  repository identity linking, state-path migration, and bootstrap diagnostics.
- CP-1202 owns dashboard projection models, rendering, and read-only commands.
- CP-1203 owns comparison grouping, isolated variant creation, prompt metadata,
  and comparison views.
- CP-1204 owns preset loading, resolution, profile commands, and launch
  snapshots.
- CP-1205 owns Ollama preflight, profile behavior, fixtures, and smoke-test docs.
- CP-1206 owns review-summary projection and readiness calculations.
- CP-1207 owns structured blocker projections and recovery explanations.
- CP-1208 owns the one-command demo and isolated cleanup behavior.
- CP-1209 owns troubleshooting and examples.
- CP-1210 owns complete UX integration and release verification.

## Approved Product Decisions

1. A/B grouping uses optional `comparison_id` and `variant_name` task fields,
   plus durable comparison events.
2. Successful scripted demos clean up unless `--keep`; failed demos preserve
   evidence and print cleanup instructions.
3. MVP v1.2 adds `canto delegate dashboard` and preserves existing
   `status`/`show` commands.
4. Token metadata is optional and parsed only from structured executor output;
   human stderr is never a correctness dependency.
5. Canto is globally installed and repo-aware; repositories are bootstrapped,
   not installed into.

## CP-1201 Acceptance

- Current workflow ownership and usability gaps are documented.
- Dashboard, profiles, prompt variants, A/B isolation, Ollama, review summary,
  conflicts, demo, output, and compatibility contracts are explicit.
- The design preserves the existing lifecycle, StateStore truth, review model,
  and promotion path.
- Automated tests remain offline and deterministic.
- CP-1315 implements the approved global-runtime/repo-bootstrap foundation
  before CP-1202 begins.
