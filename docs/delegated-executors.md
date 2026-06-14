# Delegated Worker Workspaces

Canto MVP v1.1 coordinates bounded coding work in isolated Git worktrees. The
Developer owns work scope, review, command evidence, and authorization to Apply
an accepted Result. Manual and Codex CLI Workers may edit a delegated worktree,
but cannot accept or Apply their own Result.

The CLI and persisted model retain compatibility terms such as `delegate`,
`executor_id`, `ExecutorProfile`, Artifact, and Promotion. This guide uses the
public language while showing exact commands and identifiers.

Delegation is separate from capability execution through `JobService`. It adds
no HTTP endpoints and does not change orchestration `contract_version: 1.0`.

## Trust Boundary

- A sparse worktree limits supplied repository context; it is not a security
  sandbox for a process running as the same operating-system user.
- Committed Canto role manuals are included as read context in sparse
  worktrees, but remain outside mutable task scope.
- Denied paths override allowed paths and block Result capture or Apply.
- Manual command claims are `manual_unverified` and do not satisfy required
  command gates.
- Canto-observed commands run as argv with no shell, inside the worktree.
- Canto Applies the exact accepted patch after repository, checksum,
  affected-path cleanliness, command, and Git applicability checks.
- Canto never commits, pushes, injects credentials, or contacts a remote Worker
  in this workflow.

## Manual Workflow

Bootstrap repository intent once before creating tasks:

```bash
cd /path/to/repository
canto repo init
git add AGENTS.md .canto
git commit -m "Bootstrap Canto agent instructions"
canto repo doctor
```

`AGENTS.md` is the agent-facing entrypoint. Common rules live in
`.canto/agents/shared.md`; Developer sessions also read `orchestrator.md`, and
delegated Workers also read `executor.md`. Those filenames retain compatibility
terms. Canto injects the Worker role and file references into every supervised
launch prompt rather than relying on file discovery alone.

```bash
canto delegate create "Update parser" \
  --repo /path/to/repository \
  --allow src/parser \
  --allow tests/parser \
  --deny .env \
  --instruction "Implement the bounded parser change."

canto delegate assign TASK_ID --executor manual-reviewer
canto delegate prepare TASK_ID
canto delegate start TASK_ID
# Address the Worker separately and edit only the returned Workspace path.
canto delegate message TASK_ID "Parser implementation is in progress"
canto delegate report-command TASK_ID "pytest tests/parser"
canto delegate done TASK_ID --summary "Parser and tests updated"
canto delegate capture TASK_ID
canto delegate revise TASK_ID --note "Add the missing error case"
# A manual Worker resumes explicitly; a Codex profile can be launched again.
canto delegate resume TASK_ID
```

After the revision is captured, the Developer can accept it and authorize Canto
to Apply that exact Result to the canonical repository:

```bash
canto delegate accept TASK_ID --reviewer maintainer
canto delegate queue-add TASK_ID --enqueued-by maintainer
canto delegate queue
canto delegate queue-promote TASK_ID --decided-by maintainer
```

Use `canto delegate reject` instead of acceptance when the Result must not be
Applied.

## Codex CLI Profile

Registering a Worker profile checks only local executable availability and
stores no credentials:

```bash
canto delegate profile save local-codex --preset codex-cloud --model MODEL
canto delegate profile check local-codex
canto delegate assign TASK_ID --executor local-codex
canto delegate prepare TASK_ID
canto delegate launch TASK_ID
canto delegate wait TASK_ID
canto delegate capture TASK_ID
canto delegate revise TASK_ID --note "Address review feedback"
canto delegate launch TASK_ID
canto delegate capture TASK_ID
```

`canto delegate add-codex` remains available for compatibility.

`delegate launch` remains attached to the supervised Codex process. If an
agent command runner yields while that process continues elsewhere, use
`canto delegate wait TASK_ID` instead of fixed-duration sleeps. The command
polls durable Canto state until the task finishes or needs attention. Use
`--timeout SECONDS` and `--interval SECONDS` to bound waiting; timeout does not
cancel or mutate the Worker task.

## Worker Selection and Cloud Fallback

The Developer may prefer a compatible local Worker, but local model
availability is not proof that the model can execute the Codex tool protocol.
If a local Worker repeatedly returns tool-call text or otherwise cannot make
the required Workspace changes, stop retrying that profile and explicitly
select a supervised cloud Codex Worker:

```bash
codex login status
canto delegate profile save cloud-codex --preset codex-cloud --model MODEL
canto delegate profile check cloud-codex
canto delegate assign TASK_ID --executor cloud-codex
```

This launches a separate `codex exec` process in the same bounded Canto
Workspace. Codex CLI owns authentication; Canto stores no cloud API key.
Network and quota use must be disclosed. Canto never switches from local to
cloud automatically, and cloud Results still require Capture, Developer
Review, explicit acceptance, and qualified Apply.

## Dashboard and Prompt Comparisons

```bash
canto delegate dashboard --active
canto delegate dashboard TASK_ID
canto delegate dashboard TASK_ID --json

canto delegate compare create TASK_ID \
  --variant concise="Make the smallest correct edit." \
  --variant documented="Include concise maintenance comments."
canto delegate compare show COMPARISON_ID
```

Comparison variants are isolated sibling tasks from one recorded Git base.
Assign, prepare, launch, and capture each sibling independently. A one-off
launch may use `--variant NAME --instruction TEXT`. Canto stores the exact
prompt and producing session/launch; comparison reports evidence but never
chooses or accepts a winner.

## Local Ollama Profile

```bash
canto delegate profile save local-qwen \
  --preset codex-ollama \
  --model qwen3:8b
canto delegate profile check local-qwen
```

This uses Codex CLI with `--oss --local-provider ollama`. The check requires
`codex`, `ollama`, a responsive local runtime, and an already-installed model.
Canto does not pull models or fall back to cloud execution.

Launch uses `codex exec --sandbox workspace-write --cd WORKTREE -`, sends the
bounded assignment prompt on standard input, applies a timeout, and records
stdout, stderr, argv, model provenance, and enforcement metadata. Worker output
is still untrusted until Canto captures a Result and the Developer reviews it.

## Commands and Evidence

Declare allowed and required commands in the task scope through the model API.
Run an allowed command under Canto observation:

```bash
canto delegate run-command TASK_ID "pytest tests/parser"
```

A Developer may waive a required command only with a rationale:

```bash
canto delegate waive-command TASK_ID "pytest tests/parser" \
  --reason "Fixture platform does not provide the optional runtime"
```

## Inspection

```bash
canto delegate show TASK_ID
canto delegate list
canto delegate status --active
canto delegate pool
canto delegate timeline TASK_ID
canto delegate review-summary TASK_ID
canto delegate conflict TASK_ID
```

The timeline is reconstructed from durable StateStore records and survives a
SQLite restart. Large patches, logs, and summaries are internal Artifacts that
make up the reviewable Result. They live under
`~/.canto/work/delegations/TASK_ID/artifacts/`.

## Local Demo

Run the network-free disposable demo:

```bash
canto demo delegation
canto demo delegation --promote
canto demo delegation --keep
```

The default is deterministic, offline, isolated from normal `~/.canto`, and
stops at Review. `--promote` is the compatibility option that authorizes Canto
to Apply the accepted demo Result to its disposable repository. Successful
runs clean themselves unless `--keep` is supplied; failed runs preserve
evidence and print its location. `--mode cloud` and `--mode ollama` are explicit
external-runtime opt-ins. The existing shell demo remains available.

## Safe Cleanup

Artifacts are intentionally read-only. Prefer the demo command's cleanup. For
retained or failed work, inspect the printed root first, remove any Git
worktree through the canonical repository when applicable, then restore owner
write permission only inside that disposable root before deleting it. Canto
never resets or removes a canonical repository automatically.
