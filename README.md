# Canto

Canto is a deliberately small local execution broker for Echo. It discovers registered skills, providers, and tools from YAML manifests; stores jobs, events, approvals, artifact metadata, registry snapshots, and plans in SQLite; executes registered providers with policy and bounds; and keeps artifact files on the local filesystem.

## Requirements

- WSL2 Ubuntu or another Linux environment
- Python 3.11+

## Quickstart

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[test]'
cp .env.example .env
.venv/bin/canto serve
```

Verify the environment before starting the server:

```bash
.venv/bin/pip check
.venv/bin/canto --help
.venv/bin/canto health
```

Expected result is an `ok` health status. Local durable state is stored in
`~/.canto/state.sqlite`; Redis is not required. Existing
`~/.canto/state/canto.db` state is migrated automatically when unambiguous.

Bootstrap a Git repository before running repo-scoped delegation commands:

```bash
cd /path/to/repository
canto repo init
canto repo show
canto repo doctor
```

This creates non-secret repo identity/policy files, `.canto/delegate.toml`,
role manuals under `.canto/agents/`, and a short Canto pointer in `AGENTS.md`.
Review and commit these files so delegated worktrees receive them from their
recorded Git base. `repo doctor` verifies identity, files, pointer, and Git
readiness. Canto remains globally installed; durable state, credentials,
capabilities, and delegation workspaces remain under `~/.canto`.

The API listens on `http://127.0.0.1:8765` by default. Interactive API
documentation is at `/docs`. The unauthenticated server is intended for
loopback-only use.

```bash
curl http://127.0.0.1:8765/health
curl http://127.0.0.1:8765/registry
```

Verify that the orchestration contract is exposed:

```bash
curl -X POST http://127.0.0.1:8765/discover \
  -H 'Content-Type: application/json' \
  -d '{"goal":"run the release demo"}'
```

An empty `matches` list is valid when no matching local capability is installed.

Run the deterministic local package and orchestration demonstration with:

```bash
./scripts/demo-v2.2.sh
```

The script uses an isolated temporary Canto home, performs no network access,
and leaves the normal user registry unchanged.

Run the MVP v1 governed-write quickstart with:

```bash
./scripts/quickstart-mvp-v1.sh
```

Run the complete isolated stability demonstration with:

```bash
./scripts/demo-mvp-v1.sh
```

Run the network-free delegated-executor demonstration with:

```bash
canto demo delegation
```

The delegated workflow coordinates manual or Codex CLI executors in bounded
Git worktrees, captures immutable review artifacts, and requires explicit
acceptance and promotion. See `docs/delegated-executors.md` for the workflow and
`docs/local-installation.md` for the optional real cloud smoke test using an
account-authorized model such as `gpt-5.4-mini`.

MVP v1.2 delegated-executor UX hardening is complete. It includes repo
bootstrap, task dashboards, executor presets, prompt comparisons, Ollama
preflight, deterministic review/conflict summaries, and the isolated demo.

Local wheel installation and upgrade instructions are in
`docs/local-installation.md`.

Inspect the reviewed built-in seed set with:

```bash
.venv/bin/canto seed-capabilities
```

See `docs/seed-capabilities.md` for its trust boundary and access summary.
MVP v1 release notes and troubleshooting are available at
`docs/release-notes-mvp-v1.md` and `docs/troubleshooting.md`.

## Run a source inventory

```bash
.venv/bin/canto run source_inventory \
  --provider public_html_crawler \
  --allow-network \
  --approved-domain example.com \
  --input source_url=https://example.com \
  --input max_depth=2
```

The crawler stays on the source hostname, uses bounded request and process timeouts, and defaults to at most 100 pages. Outputs are written under `work/jobs/<job_id>/`.
An approved domain also covers its subdomains, so `--approved-domain example.com`
allows `www.example.com`. The CLI prints the job ID before processing; execution
remains synchronous and the final job JSON is printed when processing stops.

## Approval flow

Providers can declare approval rules. Canto checks dependencies and policy before execution and places gated jobs in `waiting_for_approval`. Approve or reject them with:

```bash
.venv/bin/canto approve approval_YYYYMMDD_abcdef
.venv/bin/canto reject approval_YYYYMMDD_abcdef --reason "Not yet"
```

The built-in `scaffold_skill`, `scaffold_provider`, and `scaffold_tool` capabilities always require approval. Their output remains in the job artifact directory and is never automatically added to the live registry.

Inspect a registered provider's declared dependencies without installing anything:

```bash
.venv/bin/canto run check_dependencies \
  --provider manifest_dependency_checker \
  --input skill=source_inventory \
  --input provider=public_html_crawler
```

Build a deterministic migration assessment from a completed inventory job:

```bash
.venv/bin/canto run migration_report \
  --provider local_markdown_report \
  --input source_job_id=job_YYYYMMDD_abcdef \
  --input target_cms=WordPress
```

## API summary

- `GET /health`
- `GET /registry`
- `GET /skills/{skill}`
- `GET /skills/{skill}/providers/{provider}`
- `POST /jobs`
- `POST /jobs/{job_id}/promote`
- `POST /jobs/{job_id}/recover`
- `GET /jobs/{job_id}`
- `GET /jobs/{job_id}/events`
- `GET /jobs/{job_id}/artifacts`
- `GET /jobs/{job_id}/artifacts/{artifact_name}`
- `POST /approvals/{approval_id}/approve`
- `POST /approvals/{approval_id}/reject`
- `POST /discover`
- `POST /plans`
- `GET /plans/{plan_id}`
- `GET /plans/{plan_id}/explain`
- `POST /plans/{plan_id}/approve`
- `POST /plans/{plan_id}/execute`
- `GET /plans/{plan_id}/events`

Unknown skills and providers return structured `missing_skill` or `missing_provider` responses with approval-gated scaffold suggestions.

## Orchestration contract freeze

**Canto orchestration contract v1.0 is frozen subject to documented deferred
items.** The outer loop is `discover → plan → approve → execute → observe`.
Canto owns execution through `JobService`, and plan execution returns `202` so
clients poll the plan resource until a terminal status.

Contract artifacts:

- `docs/orchestration-api-contract.md`
- `docs/openapi.json`
- `docs/schemas/`
- `docs/contract-compatibility.md`
- `docs/contract-freeze-audit.md`

Deferred items include full authentication, non-loopback deployment security,
Server-Sent Events, manifest schema-version metadata, remote registries, AI
generation, signing, dependency solving, and webhooks.

## Security boundaries

Canto only launches entrypoints declared by registered provider manifests. It rejects entrypoints outside their provider directory, applies resource and output limits, validates policy before launch, and only collects declared artifacts whose resolved paths remain inside the job artifact directory. Credential-like inputs must use `*_ref` fields with `env:NAME` or encrypted `vault:scope/name` references; raw credential values are rejected before job persistence. Canto does not provide hostile-code isolation, so manifests and provider code remain trusted local configuration. The unauthenticated HTTP API is loopback-only by default; see `docs/auth-placeholder.md`.

Delegated executor sparse worktrees limit supplied repository context but are
not hostile-agent sandboxes. Executors cannot accept or promote their own work;
promotion applies only the exact reviewed patch after repository, checksum,
path, command-evidence, and applicability checks.

## Tests

```bash
.venv/bin/pytest
```
