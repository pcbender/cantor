# Local Installation and Upgrade

Canto is installed globally for one user and becomes repository-aware through
repo-local configuration. Installed Toolboxes, durable Runs and Results,
credentials, and Worker workspaces remain under the user's Canto home; the
repository stores only non-secret intent, Guardrails, and role instructions.

MVP v1 supports a trusted, single-user Linux or WSL2 installation from a local
source checkout or wheel. Python 3.11 or newer and `prlimit` are required. Node
and Docker/Podman are optional and only needed by Provider implementations that
declare those runtimes.

Development install:

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[test]'
.venv/bin/pip check
```

Until a user-level wheel is installed, invoke the checkout directly as
`.venv/bin/canto` or add that virtual environment's `bin` directory to the
interactive shell `PATH`. A repository bootstrap does not install Canto or
modify `PATH`; Canto is globally installed and repositories are only
bootstrapped.

Build and install a local wheel:

```bash
.venv/bin/pip wheel . --no-deps --no-build-isolation --wheel-dir dist
python3 -m pip install dist/canto_broker-*.whl
```

Upgrade from a newer trusted checkout or wheel with `pip install --upgrade`.
The upgrade preserves `~/.canto`, including SQLite state, installed capability
packages, and the encrypted credential vault. Back up that directory before a
release upgrade. CP-5003 documents migration from legacy Redis/filesystem
state.

Canto uses global user state and repo-local intent:

```text
~/.canto/state.sqlite
~/.canto/vault/
~/.canto/installed/
~/.canto/work/
<repo>/.canto/repo.toml
<repo>/.canto/policy.toml
<repo>/.canto/delegate.toml
<repo>/.canto/agents/shared.md
<repo>/.canto/agents/orchestrator.md
<repo>/.canto/agents/executor.md
<repo>/AGENTS.md
```

Run `canto repo init` once in each Git repository used for repo-scoped
delegation. Review and commit the generated files, then run
`canto repo doctor`. Repository files contain no secrets or durable task
records. If `AGENTS.md` already exists, Canto preserves its content and adds one
idempotent, delimited pointer section.
Existing `~/.canto/state/canto.db` is migrated to `~/.canto/state.sqlite` when
the current state file does not already exist. If both files exist, Canto stops
and requires explicit operator reconciliation.

Verify the complete local write workflow without network access:

```bash
./scripts/quickstart-mvp-v1.sh
```

The script uses an isolated temporary home, checks health, performs a managed
JSON dry run, approves its live promotion, verifies the write, approves
rollback, and verifies restoration. It does not alter the normal user registry.

## Real Cloud Delegated Worker Smoke Test

This optional test verifies the MVP v1.1 delegated-Worker path against a real
Codex cloud model. It consumes account quota and requires an authenticated
Codex CLI. Model availability depends on the account running the test. The CLI
retains internal `executor` profile and `task_id` terminology for compatibility.

Confirm the prerequisites:

```bash
codex --version
codex login status
canto delegate --help
```

Create a disposable canonical repository with an initial commit. Canto requires
the commit so it can bind the delegated Result to an exact Git base:

```bash
mkdir -p ~/canto-delegation-smoke/src ~/canto-delegation-smoke/tests
cd ~/canto-delegation-smoke
git init

printf 'before delegation\n' > src/message.txt
printf 'before delegation\n' > tests/expected.txt
git add src/message.txt tests/expected.txt
git commit -m "Initialize delegation smoke test"
canto repo init
```

Register the cloud Worker profile, create the bounded assignment, and copy the
internal `task_id` printed by `create` into `TASK_ID`:

```bash
canto delegate add-codex cloud-mini \
  --executable codex \
  --model gpt-5.4-mini

canto delegate create "Update the delegation fixture" \
  --repo "$PWD" \
  --allow src \
  --allow tests \
  --deny README.md \
  --instruction "Change src/message.txt and tests/expected.txt to contain exactly: delegated by gpt-5.4-mini. Make no other changes. Do not commit."

TASK_ID=task_REPLACE_WITH_PRINTED_ID
canto delegate assign "$TASK_ID" --executor cloud-mini
canto delegate prepare "$TASK_ID"
canto delegate launch "$TASK_ID"
canto delegate capture "$TASK_ID"
```

`launch` runs a headless child process equivalent to:

```text
codex exec --sandbox workspace-write --cd DELEGATED_WORKTREE \
  --model gpt-5.4-mini -
```

The child is not a second GUI window. Canto records its argv, prompt, stdout,
stderr, exit code, model provenance, and Workspace. A successful capture leaves
the assignment in `reviewing`; it does not accept the Result or Apply it to the
canonical repository.

Verify that the canonical checkout is unchanged and inspect the durable review
evidence:

```bash
git status --short
cat src/message.txt
cat tests/expected.txt

canto delegate show "$TASK_ID"
canto delegate timeline "$TASK_ID"

ARTIFACT_DIR="$HOME/.canto/work/delegations/$TASK_ID/artifacts"
cat "$ARTIFACT_DIR/revision-1/changed_files.json"
git apply --stat "$ARTIFACT_DIR/revision-1/proposal.diff"
cat "$ARTIFACT_DIR"/*.stdout.log
cat "$ARTIFACT_DIR"/*.stderr.log
```

Expected results:

- The child launch exits successfully and the assignment reaches `reviewing`.
- `changed_files.json` contains only `src/message.txt` and
  `tests/expected.txt`.

- The canonical files still contain `before delegation`.
- Generated untracked Python and pytest cache files are excluded from capture.
- No commit, push, acceptance, or Apply occurs automatically.

To exercise revision handling without Apply:

```bash
canto delegate revise "$TASK_ID" --note "Use different reviewed text"
canto delegate launch "$TASK_ID"
canto delegate capture "$TASK_ID"
```

The second launch receives the revision note, creates separate prompt/output
logs, and produces immutable Result revision 2. Only after reviewing the exact
patch should the Developer use `canto delegate accept`, `queue-add`, and the
compatibility command `queue-promote` to authorize and perform the qualified
Apply action. Delete the disposable repository and its delegation work files
when the test is no longer needed.

## Optional Local Ollama Smoke Test

Use only a model already installed in the local Ollama runtime:

```bash
codex --version
ollama list
canto delegate profile save local-ollama \
  --preset codex-ollama \
  --model qwen3:8b
canto delegate profile check local-ollama
```

Then follow the disposable repository and assignment flow above, assigning
`local-ollama` instead of the cloud profile. Stop after `capture` and inspect
`canto delegate review-summary TASK_ID`. Canto does not download models, use a
cloud fallback, accept the Result, or Apply it automatically.
