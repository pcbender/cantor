# MVP v1 Troubleshooting

This guide uses public Run, Result, and Guardrails language where possible and
includes internal Job, Artifact, Provider, and Policy identifiers when needed
to match commands and diagnostics.

## Health is degraded

Run `canto health` and confirm `state` is `ok`. SQLite lives at
`~/.canto/state.sqlite`; check that `~/.canto` is writable by the current
user. Redis is not required. Legacy state migration is documented in
`docs/state-migration.md`.

Read-only delegation inspection commands (`canto delegate pool` and
`canto delegate status`) open existing SQLite state without schema or WAL
initialization. If state is absent or unreadable, they report a concise
state-access error rather than creating files or emitting a traceback.

## The `canto` command is not on PATH

A repo bootstrap does not install Canto. From a source checkout, use the
checkout executable (for example `~/canto/.venv/bin/canto`) or add that virtual
environment's `bin` directory to the shell `PATH`. For normal use, install the
trusted local wheel as described in `docs/local-installation.md`.

## A credential cannot be resolved

Use `canto credential list` to confirm the `vault:scope/name` reference exists.
For `env:NAME`, export the variable in the process that starts Canto. Do not put
plaintext values in Run inputs (`job` records). Recreate or rotate corrupt
records; never edit encrypted vault JSON manually.

## A Run is waiting for Approval

Inspect the Job and Events, then use the listed Approval ID with `canto approve`
or `canto reject`. Applying a reviewed write Result and running recovery each
require their own Approval. Changing a reviewed Artifact, Provider package,
target identity, credential reference, or input invalidates the Apply request.

## A live write fails before mutation

Check the validation and change-set artifacts from the dry run. The reference
provider rejects target drift between review and live execution. Run a new dry
run rather than editing artifacts. Direct live write jobs are intentionally
rejected.

## A provider exceeds a runtime limit

Inspect the `runtime_limits_applied` job event. Providers may request lower
limits, but not raise global ceilings. Relevant environment variables are
listed in `.env.example`. Local runtime enforcement requires Linux `prlimit`.

## Network access is denied

The job policy must allow network access and list approved domains. The
provider must declare `runner.egress_enforcement: provider_allowlist`. Canto
fails closed when the active runtime cannot enforce the declared network
permission. Network-write providers are not supported in MVP v1.

## Node, binary, or container execution fails

Node and executable binaries must already exist locally. Binary entrypoints
must have execute permission. Container providers require Docker or Podman and
an image already present on the machine; Canto never pulls images.

## Installation or wheel verification fails

Install the local build/test extras with `pip install -e '.[test]'`, then run
`pip check`. Wheel and upgrade instructions are in
`docs/local-installation.md`. Capability package installation remains explicit
and local; there is no remote registry or automatic dependency installation.

## Delegation cannot find a repository or base commit

Run `canto repo init` from a Git repository with at least one commit. Use
`canto repo show` from a nested directory to verify the canonical path, Git
common directory, initial HEAD, and remote metadata. Canto refuses moved or
mismatched repository identity instead of silently rewriting it.

Run `canto repo doctor` to verify `.canto/delegate.toml`, all role manuals, the
`AGENTS.md` pointer, and Git readiness. If it reports uncommitted instruction
files, review and commit them before delegation; worktrees are created from
committed Git bases.

## A delegated executor or Ollama model is unavailable

Run `canto delegate profile check PROFILE`. Cloud Codex requires an available,
authenticated Codex CLI; verify login with `codex login status`. Ollama also
requires `ollama list` to succeed and the requested model to be installed.
Canto stores no login credentials, pulls no model, and provides no cloud
fallback for an Ollama profile.

## Sparse or denied paths reject capture

Inspect `canto delegate dashboard TASK_ID --json`. Scope paths must be
repository-relative, non-symlink paths and may not overlap denied paths.
Generated `__pycache__` and `.pytest_cache` content is excluded, but real
out-of-scope edits must be revised in the delegated worktree.

## Review, conflict, or promotion is blocked

Run `canto delegate review-summary TASK_ID` and
`canto delegate conflict TASK_ID`. They distinguish failed or missing command
evidence, changed checksums, stale canonical HEAD, dirty affected paths, queue
overlap, and failed-promotion rollback state. Canto does not automatically
merge, rebase, reset, retry, or clean up.

Prompts, stdout/stderr, command logs, and immutable result artifacts live under
`~/.canto/work/delegations/TASK_ID/artifacts/`. Revision feedback remains a
review decision and is separate from optional prompt variants.

If a supervised Worker exits successfully but changes no Workspace files,
Capture has no Result to record. Use `canto delegate revise TASK_ID --note
"..."` to return the same task to `revision_requested`; the next launch receives
that feedback. Canto projects the matching launch outcome onto the session, so
completed or failed supervised sessions do not remain displayed as running.

If repeated local-model launches produce tool-call text instead of tool
execution, treat the profile as incompatible with implementation work. Use it
for advisory output or explicitly assign an authenticated `codex-cloud`
profile. Canto must not make that local-to-cloud switch automatically.

Do not use `sleep` to poll Worker completion. Keep `canto delegate launch`
attached when possible. If the calling agent has yielded that command, run
`canto delegate wait TASK_ID`; it observes durable status and returns when the
task completes, fails, blocks, or otherwise needs Developer attention.

If promotion rolls back safely because accepted patch evidence is incomplete,
use `canto delegate revise TASK_ID --note "..."` and capture a new immutable
Result. Do not edit an existing Result artifact or force the incomplete patch
into the canonical repository.
