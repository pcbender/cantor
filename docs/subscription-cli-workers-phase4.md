# CP-1721 - Phase 4 Multi-Provider CLI Adapters

Status: implemented.

## Goal

Phase 4 extends Canto-launched subscription CLI Workers beyond Codex while
preserving the existing governed delegation lifecycle:

Find or assign Worker -> prepare Workspace -> launch -> capture Result -> review
-> Apply only when accepted.

## Supported CLI Harnesses

Canto now recognizes these Canto-launched CLI harnesses:

- `codex_cli`
- `claude_cli`
- `gemini_cli`

The existing `CodexCliExecutor` name remains as a compatibility shim. Runtime
selection, pool visibility, dashboard availability, and profile checks use the
generic CLI adapter path.

## Built-In Presets

`canto delegate profile save` can use these subscription presets:

- `codex-cloud`
- `claude-subscription`
- `gemini-subscription`

Codex local Ollama remains available through `codex-ollama`.

## Auth And Secret Boundary

Canto does not store cloud API keys in executor profiles.

For subscription CLI Workers:

- Codex subscription auth is checked through local Codex auth state.
- Claude subscription auth is checked through `claude auth status` and must use
  first-party `claude.ai` auth.
- Gemini CLI support uses executable availability plus Canto's subprocess
  environment scrub. Gemini API-key environment variables are not passed to the
  Worker subprocess.

The CLI process owns its own subscription session. Canto owns task scope,
Workspace isolation, launch evidence, Result capture, review, and Apply.

## Selection Behavior

Repo policy can allow CLI transport and list specific profile IDs:

```toml
[selection]
allowed_transports = ["cli", "http"]
allowed_cli_profiles = ["website-codex-cloud"]
preferred_cli_profiles = ["website-codex-cloud"]
prefer_subscription_cli = true
api_fallback_requires_approval = true
```

`launch-ai` tries allowed CLI profiles first. If CLI profiles are exhausted,
Phase 3 fallback rules still apply: balanced and quality tasks require explicit
approval before HTTP/API fallback.

## Dogfood Result

Canto was dogfooded on this branch with:

```bash
canto delegate launch-ai task_a2dfa94e38194aa8b7b0199fc118fd53
```

The task selected `website-codex-cloud`, ran through `codex exec`, captured a
reviewable Result, and produced no Canto API usage record for the task. The
Result was accepted but not Applied to the canonical repository.

## Non-Goals

- No remote Worker service.
- No full multi-user identity model.
- No hidden API fallback.
- No automatic provider performance learning.
- No delegated Worker self-Apply.
