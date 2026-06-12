# Graphify Maintenance

Canto keeps Graphify as an explicit development aid, not a blocking execution
gate.

## Supported Workflow

Use the checked-in `AGENTS.md` guidance:

```bash
graphify query "question about the codebase"
graphify path "A" "B"
graphify explain "concept"
```

After modifying code, refresh the graph explicitly:

```bash
graphify update .
```

The refresh is AST-only and does not require an API key. Review the resulting
tracked graph artifacts before committing them.

## Repository Policy

Tracked outputs are the reviewable graph, report, visualization, manifest, and
stable Graphify metadata already present under `graphify-out/`.

Local extraction caches and runtime markers are ignored:

- `graphify-out/cache/`;
- `graphify-out/.graphify_root`;
- dated `.graphify_labels.json` files generated during local refreshes.

Do not add a repository `PreToolUse` hook that runs before every shell command.
Graphify failures or latency must not block unrelated Canto development,
testing, review, or recovery commands.

Git post-commit or post-checkout hooks are not required. If automation is added
later, prefer a non-blocking or CI freshness check with a bounded timeout and a
clear remediation command.

## Codex Integration

`graphify codex install` manages the Graphify section in `AGENTS.md`. It does
not require `.codex/hooks.json`. Codex uses the graph through the explicit
query/update instructions rather than a mandatory shell hook.
