# Governed AI Worker Pool

Canto selects API-backed coding Workers for delegated repository work while
preserving the existing Workspace, Result, Review, and Apply lifecycle.
Endpoint credentials and durable model records are global; repository policy
only narrows which validated Workers may be used.

## Configure An Endpoint

Cloud endpoints require HTTPS and an API key stored in Canto's encrypted vault.
Omit `--api-key` to enter it through a hidden prompt:

```bash
canto ai endpoint add openai-primary \
  --provider openai \
  --base-url https://api.openai.com

canto ai endpoint add local-ollama \
  --provider ollama \
  --base-url http://127.0.0.1:11434
```

Supported providers are `openai`, `anthropic`, `google`,
`openai_compatible`, and `ollama`. Automatically selected Workers do not use
browser, OAuth, inherited CLI, or external session authentication.

## Discover, Refresh, And Probe

Discovery contacts only the named configured endpoint. A model is not eligible
for implementation work until the versioned probe proves structured file edits
and command execution:

```bash
canto ai model discover local-ollama
canto ai model refresh local-ollama
canto ai model list --endpoint local-ollama
canto ai model probe local-ollama:qwen2.5-coder:14b
```

Exact provider identifiers and resolved versions are persisted. A changed
version or catalog checksum makes prior probe evidence stale.

Use `discover` for initial endpoint discovery and compatibility workflows. Use
`refresh` for authoritative local Ollama reconciliation. A successful refresh
marks newly seen models available, changed digests stale, and absent models
missing without deleting their evidence. Endpoint failure is recorded as
uncertainty and does not falsely mark every model missing.

Probing remains explicit:

```bash
canto ai model refresh local-ollama --probe-new
canto ai model refresh local-ollama --probe-stale
```

These options probe only the named local endpoint's added or changed models,
sequentially, with no cloud fallback. Without either option, refresh never
runs a model.

## Inspect And Maintain Local Models

```bash
canto ai model status --endpoint local-ollama
canto ai model show local-ollama:qwen2.5-coder:14b
canto ai model forget local-ollama:removed-model
```

Status separates availability, observed Worker classification, and probe
state. Forget is allowed only for a non-available model with no retained probe,
usage, selection, or delegation references.

Optional reviewed metadata is imported from a local JSON object and remains
advisory:

```bash
canto ai model metadata-add local-ollama:qwen2.5-coder:14b model-card.json \
  --source-kind curated \
  --source-uri https://example.invalid/official-model-card \
  --reviewed
```

Only `declared` and `curated` manual sources are accepted. Metadata never
overwrites observed probe evidence or grants implementation eligibility.

## Repository Policy

`canto repo init` creates `.canto/workers.toml`. It contains no credentials or
durable task state. Its default is local-only, with budgets disabled. Priority
may be `economy`, `balanced`, `quality`, or `urgent`. Policy can narrow
endpoints, providers, models, token limits, estimated cost, turns, tool calls,
and wall time. More specific policy cannot widen a parent policy.
`preferred_models` is an ordered ranking hint within `allowed_models`; it does
not authorize a model and preserves fallback to later eligible models.

Saved CLI Worker profiles may enter `launch-ai` only when repository policy
explicitly permits CLI transport:

```toml
[selection]
allowed_transports = ["cli"]
allowed_cli_profiles = ["local-codex"]
preferred_cli_profiles = ["local-codex"]
prefer_subscription_cli = true
```

The default `allowed_transports = []` preserves HTTP/API-backed `launch-ai`
behavior. `allowed_transports = ["cli"]` prevents API fallback; use
`["cli", "http"]` only when API fallback is intentionally allowed.

`canto repo doctor` includes AI Worker readiness. It reports policy-required
endpoints and exact models, current cloud readiness, and local model status.
Missing explicitly allowed endpoints or models are blocking failures. Optional
local capacity is shown as a warning when cloud use remains authorized.

## Select And Run

```bash
canto ai pool select TASK_ID
canto ai pool explain SELECTION_ID
canto delegate launch-ai TASK_ID
```

Cloud use requires `--allow-cloud`. Local-to-cloud fallback additionally
requires `--allow-cloud-fallback`; it is never silent. Fallback stops if a
failed Worker changed the Workspace. CLI-authenticated profiles remain
credential-free `ExecutorProfile` records and are eligible only when repository
policy explicitly allows CLI transport.

## Evidence And Security

Canto records candidate rejections, exact model version, sessions, launches,
token usage, cost when pricing is known, provider request IDs, and endpoint
health. API keys are never written to repositories, endpoint YAML, prompts,
Results, or error messages. Commands run without a shell and must match the
delegation allowlist; writes remain inside allowed Workspace paths.

The pool is single-user and local in this release. It does not add remote
registry behavior, shared-server identity, OAuth, autonomous approval, or a
second execution/review path.

## Offline Demo

```bash
canto demo ai-worker-pool
canto demo ai-worker-pool --apply
```

The first command stops after Developer acceptance. `--apply` verifies and
promotes the exact accepted Result in the disposable demo repository. Neither
command needs a model server, network, or credentials.
