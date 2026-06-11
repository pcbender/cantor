# Local Installation and Upgrade

MVP v1 supports a trusted, single-user Linux or WSL2 installation from a local
source checkout or wheel. Python 3.11 or newer and `prlimit` are required. Node
and Docker/Podman are optional and only needed by providers that declare those
runtimes.

Development install:

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[test]'
.venv/bin/pip check
```

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

Verify the complete local write workflow without network access:

```bash
./scripts/quickstart-mvp-v1.sh
```

The script uses an isolated temporary home, checks health, performs a managed
JSON dry run, approves its live promotion, verifies the write, approves
rollback, and verifies restoration. It does not alter the normal user registry.

## Real Cloud Delegation Smoke Test

This optional test verifies the MVP v1.1 delegated-executor path against a real
Codex cloud model. It consumes account quota and requires an authenticated
Codex CLI. Model availability depends on the account running the test.

Confirm the prerequisites:

```bash
codex --version
codex login status
canto delegate --help
```

Create a disposable canonical repository with an initial commit. Canto requires
the commit so it can bind the delegated result to an exact Git base:

```bash
mkdir -p ~/canto-delegation-smoke/src ~/canto-delegation-smoke/tests
cd ~/canto-delegation-smoke
git init

printf 'before delegation\n' > src/message.txt
printf 'before delegation\n' > tests/expected.txt
git add src/message.txt tests/expected.txt
git commit -m "Initialize delegation smoke test"
```

Register the cloud executor profile, create the bounded task, and copy the
`task_id` printed by `create` into `TASK_ID`:

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
stderr, exit code, model provenance, and workspace. A successful capture leaves
the task in `reviewing`; it does not accept or promote the result.

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

- The child launch exits successfully and the task reaches `reviewing`.
- `changed_files.json` contains only `src/message.txt` and
  `tests/expected.txt`.
- The canonical files still contain `before delegation`.
- Generated untracked Python and pytest cache files are excluded from capture.
- No commit, push, acceptance, or promotion occurs automatically.

To exercise revision handling without promotion:

```bash
canto delegate revise "$TASK_ID" --note "Use different reviewed text"
canto delegate launch "$TASK_ID"
canto delegate capture "$TASK_ID"
```

The second launch receives the revision note, creates separate prompt/output
logs, and produces immutable revision 2. Only after reviewing the exact patch
should an operator use `canto delegate accept`, `queue-add`, and
`queue-promote`. Delete the disposable repository and its delegation work files
when the test is no longer needed.
