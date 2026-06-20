# CP-1727 - Phase 5 CLI Worker UX Hardening

Status: implemented.

## Goal

Phase 5 makes explicit CLI Worker selection easier and reduces repo-local
duplication. The architecture remains:

- Global/shared state owns endpoints, discovered models, probes, saved executor
  profiles, and named profile pools.
- Repository policy owns which shared Workers are allowed for that repository.
- Task or command options may narrow selection further, but cannot silently
  widen repo authority.

## Direct Profile Launch

`launch-ai` supports an explicit CLI profile override:

```bash
canto delegate launch-ai TASK_ID --profile website-codex-cloud
```

The override narrows selection to the named CLI profile and CLI transport. It
does not authorize HTTP/API fallback.

## Named Shared Profile Pools

Named pools live in the global executor profile config:

```yaml
profile_pools:
  subscription-cli:
    profiles:
      - website-codex-cloud
      - claude-subscription
      - gemini-subscription
```

Repository policy can reference the pool instead of copying every profile ID:

```toml
[selection]
allowed_transports = ["cli", "http"]
allowed_cli_profile_pools = ["subscription-cli"]
preferred_cli_profile_pools = ["subscription-cli"]
prefer_subscription_cli = true
api_fallback_requires_approval = true
```

Explicit profile lists still work. If both pools and direct profile lists are
present, Canto treats the union as the allowed or preferred profile set for that
repository policy layer.

## Commands

```bash
canto delegate profile pool list
canto delegate profile pool show subscription-cli
canto delegate profile pool save subscription-cli \
  --profile website-codex-cloud \
  --profile claude-subscription \
  --profile gemini-subscription
```

Pool save requires every referenced profile to already exist. Canto rejects
credentials in profile-pool config.

## Non-Goals

- No automatic performance learning.
- No remote Worker service.
- No hidden API fallback.
- No broad migration of all model allowlists out of repositories.
- No multi-user identity or shared-server authorization model.
