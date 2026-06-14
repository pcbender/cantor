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

## Discover And Probe

Discovery contacts only the named configured endpoint. A model is not eligible
for implementation work until the versioned probe proves structured file edits
and command execution:

```bash
canto ai model discover local-ollama
canto ai model list --endpoint local-ollama
canto ai model probe local-ollama:qwen2.5-coder:14b
```

Exact provider identifiers and resolved versions are persisted. A changed
version or catalog checksum makes prior probe evidence stale.

## Repository Policy

`canto repo init` creates `.canto/workers.toml`. It contains no credentials or
durable task state. Its default is local-only, with budgets disabled. Priority
may be `economy`, `balanced`, `quality`, or `urgent`. Policy can narrow
endpoints, providers, models, token limits, estimated cost, turns, tool calls,
and wall time. More specific policy cannot widen a parent policy.

## Select And Run

```bash
canto ai pool select TASK_ID
canto ai pool explain SELECTION_ID
canto delegate launch-ai TASK_ID
```

Cloud use requires `--allow-cloud`. Local-to-cloud fallback additionally
requires `--allow-cloud-fallback`; it is never silent. Fallback stops if a
failed Worker changed the Workspace. CLI-authenticated profiles remain an
explicit Developer-assigned compatibility escape hatch and never enter
automatic discovery, ranking, or fallback.

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
