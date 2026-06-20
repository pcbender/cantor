# CLI Executor Call-Site Audit

Status: CP-1702 read-only audit.

## Codex CLI Executor

Current implementation:

- `canto/core/delegation_executor.py` defines `CodexCliExecutor`.
- `CodexCliExecutor.launch()` creates `ExecutorSession` and `ExecutorLaunch`
  evidence, runs `codex exec`, writes prompt/stdout/stderr artifacts, and
  transitions the task to `executor_done` or `failed`.
- It does not produce `DelegationResult`; capture remains owned by
  `DelegationArtifactService`.

Current call sites:

- `canto/cli.py`:
  - `delegate show` uses `projected_sessions()`.
  - `delegate add-codex` checks executable availability.
  - `delegate launch` launches the assigned Codex CLI profile.
- `canto/core/delegation_dashboard.py`:
  - checks Codex profile availability and projects session status.
- `canto/core/delegation_pool.py`:
  - reports Codex profile availability in the Worker pool.
- `canto/core/delegation_demo.py`:
  - optionally launches a Codex CLI profile for the local delegation demo.
- `scripts/demo_delegated_executors.py`:
  - exercises manual/delegated workflow around existing delegation services.
- Tests:
  - `tests/test_delegation_executor.py`
  - `tests/test_delegation_ux_e2e.py`
  - dashboard, pool, CLI, and demo tests reference profile behavior.

## API Worker Harness Boundary

Current implementation:

- `canto/core/ai_worker.py` defines `AgentAdapter`, `HttpAgentAdapter`, and
  `APIWorkerHarness`.
- `APIWorkerHarness` owns the provider-neutral HTTP tool loop for API-backed
  Workers.

Current call sites:

- `canto/core/ai_assignment.py` uses `APIWorkerHarness` for
  `canto delegate launch-ai TASK_ID`.
- `canto/core/ai_probe.py` uses `APIWorkerHarness` for coding Worker probes.
- `canto/core/ai_worker_demo.py` uses a scripted adapter for the offline demo.
- Tests cover provider message normalization, tool execution, budgets, probes,
  and assignment.

Phase 1 must not change API Worker selection, probing, HTTP provider behavior,
or `launch-ai` semantics.

## Worker Selection Boundary

Current implementation:

- `canto/core/ai_selection.py` scores `AIModelRecord` candidates using endpoint
  health, local/cloud authority, allowed endpoints/providers/models, probe
  state, classification, context, pricing, and priority.
- `AIEndpointRecord` does not have a `transport` field.
- CLI profiles are not automatic AI selection candidates.

Phase 1 leaves selection unchanged.

## Memory Boundary

Current implementation:

- `canto/core/memory.py` owns governed memory lifecycle and retrieval.
- Repo bootstrap emits agent guidance that tells Workers how to use memory when
  assigned scope permits it.
- CLI Worker launch prompts do not currently materialize a memory context pack.
- Durable memory writes route through `MemoryService` and existing Approval
  objects.

Phase 1 does not add memory read/write bridging to CLI subprocesses.

## Phase 1 Implication

The safe seam is:

- extract subprocess command/env/prompt execution from `CodexCliExecutor`;
- keep `CodexCliExecutor` as the public compatibility wrapper;
- return `ExecutorLaunch` evidence, not `DelegationResult`;
- keep `delegate launch`, dashboards, pool views, demos, and tests behaviorally
  compatible.
