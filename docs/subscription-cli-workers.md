# Subscription CLI Workers

Status: Phase 1 complete; Phase 2 Codex CLI candidate routing in progress.

## Purpose

Canto should reduce API-key spend for delegated Worker tasks by using installed
subscription-authenticated CLI tools where the Developer explicitly permits that
transport. The long-term target is one Worker pool that can choose between local,
subscription CLI, and API-backed Workers. The near-term implementation is
phased so Canto keeps its existing delegation, Result, Review, and Apply
lifecycle intact.

## Current Boundary

Canto currently has two Worker paths:

- `canto delegate launch-ai TASK_ID` selects API-backed Workers from validated
  endpoint/model records and runs them through `APIWorkerHarness`.
- `canto delegate launch TASK_ID` runs an explicitly assigned `ExecutorProfile`
  through the Codex CLI compatibility path.

Phase 1 preserves that behavior while extracting the CLI execution seam. Phase
2 begins the unification path by allowing explicitly permitted saved Codex CLI
profiles to be selected by `launch-ai` before API-backed Workers.

## Decisions

- Canto remains the governed runtime. Workers cannot self-assign, self-review,
  self-accept, self-promote, or Apply their own Results.
- CLI subscription Workers are a separate auth and cost plane from HTTP API-key
  Workers.
- CLI Worker subprocesses must not receive API keys, vault credentials, base-URL
  overrides, or arbitrary inherited environment variables.
- `ExecutorProfile` remains the source of CLI Worker configuration in the
  first selectable-candidate phase.
- `DelegationResult` remains produced by `canto delegate capture`; CLI execution
  produces launch/session evidence only.
- `canto delegate launch TASK_ID` remains the explicit profile command.
- `canto delegate launch-ai TASK_ID` may select a saved CLI profile only when
  repository Worker policy explicitly includes `cli` transport.
- API fallback is disabled when policy allows only `cli`; HTTP/API fallback is
  possible only when policy also allows `http`.
- Memory writes by CLI Workers are deferred. CLI Workers may receive bounded
  prompt context, but durable memory updates continue through existing Canto
  review/approval paths.

## Phase 1 Scope

Phase 1 is behavior-preserving for Codex CLI execution:

1. Audit current CLI executor and Worker pool call sites.
2. Add a provider-neutral `CliExecutor` and `CliAdapter` seam.
3. Move existing Codex command/auth/parsing behavior into `CodexCliAdapter`.
4. Keep `CodexCliExecutor` as a compatibility shim.
5. Add a subprocess environment allowlist that strips API key and endpoint
   override variables.
6. Add Codex subscription auth preflight helpers without forcing every existing
   test fixture to provide local user auth.
7. Cover the seam, environment scrub, timeout, and compatibility behavior with
   network-free tests.

## Deferred

- Claude and Gemini CLI adapters.
- Priority-driven quota exhaustion and API fallback.
- Provider-diversity scoring against the current orchestrator provider.
- Performance feedback registry and capability floors beyond current
  `classification` and probe evidence.

## Phase 2 Policy

Repo-local `.canto/workers.toml` may explicitly permit CLI selection:

```toml
[selection]
allowed_transports = ["cli"]
allowed_cli_profiles = ["local-codex"]
preferred_cli_profiles = ["local-codex"]
prefer_subscription_cli = true
```

Default `allowed_transports = []` preserves current HTTP/API-backed
`launch-ai` behavior. CLI transport is never inferred from the presence of a
saved profile.

## Phase 3 Fallback

Phase 3 adds structured CLI fallback states:

- `not_allowed`
- `no_candidate`
- `launched`
- `api_allowed`
- `api_requires_approval`
- `api_blocked`

Priority controls what happens when CLI candidates are unavailable or exhausted:

- `economy`: block API fallback.
- `balanced` and `quality`: require approval before API fallback.
- `urgent`: allow API fallback only when policy also permits HTTP/API use.

Optional `orchestrator_provider` policy context is surfaced in CLI candidate
explanations so future scoring can penalize using the same subscription pool.

## Acceptance

- Existing `CodexCliExecutor` call sites continue working.
- Existing `delegate launch` behavior remains unchanged.
- CLI subprocesses receive only the allowlisted environment.
- Known API key variables are absent from CLI Worker environments.
- Codex subscription auth can be checked explicitly:

  ```bash
  canto delegate profile check PROFILE --subscription-auth
  ```

- Full test suite passes without requiring installed Codex, Claude, Gemini,
  Ollama, network access, or subscription credentials.
