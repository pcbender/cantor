# CP-1729 - Local Ollama Worker Reliability Hotfix

Status: implemented.

## Problem

Dogfooding showed that `codex --oss --local-provider ollama` can fail for two
different reasons:

- the nested Codex sandbox blocks the loopback HTTP call to Ollama;
- Codex OSS/Ollama compatibility can fail before producing Workspace changes.

Local Ollama is still the right zero-marginal-cost Worker target, but the
reliable Canto path should not depend on Codex OSS when Canto already owns a
direct HTTP/API Worker harness.

## Supported Local Path

Use Canto's direct local Ollama API Worker:

```bash
canto delegate launch-ai TASK_ID --local-only
```

`--local-only` narrows selection to:

- HTTP/API Worker transport only;
- provider `ollama` only;
- no cloud Worker selection;
- no cloud fallback;
- existing repository policy constraints for exact endpoints and models.

This path talks directly to the configured local Ollama endpoint and keeps
delegation inside the normal Canto Workspace, Result, review, and Apply flow.

## Codex-Ollama CLI Path

Codex-Ollama CLI remains available for explicit testing, but it is not the
preferred reliability path. Even though Ollama is local, Codex reaches it
through loopback HTTP, so Canto enables network access for nested Codex-Ollama
Workers.

This is a broad Codex sandbox toggle, not a loopback-only permission. Use the
direct API Worker path when strict local-worker reliability matters.

## Non-Goals

- No automatic cloud fallback.
- No remote Worker service.
- No replacement of the direct API Worker harness.
- No dependency on Codex OSS for local model execution.
- No change to the frozen orchestration contract.

