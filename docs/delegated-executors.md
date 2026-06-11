# Delegated Executor Workspaces

Canto MVP v1.1 coordinates bounded coding work in isolated Git worktrees. The
orchestrator owns task scope, review, command evidence, and promotion. Manual
and Codex CLI executors may edit a delegated worktree, but cannot accept or
promote their own result.

Delegation is separate from capability execution through `JobService`. It adds
no HTTP endpoints and does not change orchestration `contract_version: 1.0`.

## Trust Boundary

- A sparse worktree limits supplied repository context; it is not a security
  sandbox for a process running as the same operating-system user.
- Denied paths override allowed paths and block artifact capture or promotion.
- Manual command claims are `manual_unverified` and do not satisfy required
  command gates.
- Canto-observed commands run as argv with no shell, inside the worktree.
- Promotion applies the exact accepted patch after repository, checksum,
  affected-path cleanliness, command, and Git applicability checks.
- Canto never commits, pushes, injects credentials, or contacts a remote
  executor in this workflow.

## Manual Workflow

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
# Address the executor separately and edit only the returned workspace path.
canto delegate message TASK_ID "Parser implementation is in progress"
canto delegate report-command TASK_ID "pytest tests/parser"
canto delegate done TASK_ID --summary "Parser and tests updated"
canto delegate capture TASK_ID
canto delegate revise TASK_ID --note "Add the missing error case"
canto delegate resume TASK_ID
```

After the revision is captured, the orchestrator can accept and promote it:

```bash
canto delegate accept TASK_ID --reviewer maintainer
canto delegate queue-add TASK_ID --enqueued-by maintainer
canto delegate queue
canto delegate queue-promote TASK_ID --decided-by maintainer
```

Use `canto delegate reject` instead of acceptance when the result must not be
promoted.

## Codex CLI Profile

Registering a profile checks only local executable availability and stores no
credentials:

```bash
canto delegate add-codex local-codex --executable codex --model MODEL
canto delegate assign TASK_ID --executor local-codex
canto delegate prepare TASK_ID
canto delegate launch TASK_ID
canto delegate capture TASK_ID
```

Launch uses `codex exec --sandbox workspace-write --cd WORKTREE -`, sends the
bounded task prompt on standard input, applies a timeout, and records stdout,
stderr, argv, model provenance, and enforcement metadata. Executor output is
still untrusted until capture and orchestrator review.

## Commands and Evidence

Declare allowed and required commands in the task scope through the model API.
Run an allowed command under Canto observation:

```bash
canto delegate run-command TASK_ID "pytest tests/parser"
```

An orchestrator may waive a required command only with a rationale:

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
```

The timeline is reconstructed from durable StateStore records and survives a
SQLite restart. Large patches, logs, and summaries live under
`~/.canto/work/delegations/TASK_ID/artifacts/`.

## Local Demo

Run the network-free disposable demo:

```bash
bash scripts/demo-delegated-executors.sh
```

It proves one manual workflow and one supervised scripted-Codex workflow. The
script uses temporary repositories and does not modify the Canto checkout.
