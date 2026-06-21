# CP-1728 - Nested Codex Worker Sandbox Hotfix

Status: implemented.

## Problem

Dogfooding showed that a Canto delegation launched from inside another coding
agent can fail before the Worker does useful work:

- the parent sandbox may block access to `~/.canto/state.sqlite`;
- the nested Codex Worker sandbox may block network access for subscription or
  cloud-backed CLI Workers.

This is not specific to Claude or OpenAI auth. It is a sandbox composition
problem: parent agent sandbox, Canto state, and child Codex Worker sandbox all
need compatible permissions.

## Canto-Owned Fix

Canto-launched `codex_cli` Workers now include the global Canto state root in
the nested Codex workspace-write sandbox:

```bash
codex exec --sandbox workspace-write --add-dir ~/.canto --cd WORKSPACE -
```

When the Codex profile is cloud-backed, or when the profile explicitly grants
network permission, Canto also enables network access in the nested Codex
sandbox:

```bash
codex exec \
  --sandbox workspace-write \
  --add-dir ~/.canto \
  -c sandbox_workspace_write.network_access=true \
  --cd WORKSPACE \
  -
```

Local Ollama Codex profiles remain network-restricted unless the profile
explicitly sets `permissions.allow_network = true`.

## Parent Sandbox Requirement

This hotfix cannot override the sandbox of the agent process that is already
running Canto. If Codex or Claude Code launches Canto from inside a restricted
workspace, that parent session must also allow Canto state and any required
network access.

For a parent Codex session driving Canto delegation, the practical launch shape
is:

```bash
codex exec \
  --sandbox workspace-write \
  --add-dir /home/mrose/.canto \
  -c sandbox_workspace_write.network_access=true \
  --cd /path/to/repo
```

The exact path should follow `CANTO_HOME` when that environment variable is set.

## Non-Goals

- No broad bypass of Codex sandboxing.
- No network access for local-only Worker profiles by default.
- No credential handling changes.
- No new delegation transport.
- No change to the frozen orchestration contract.

