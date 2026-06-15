# CP-1515 — Local Model Catalog Reconciliation Design

## Purpose

Canto already discovers exact endpoint model identifiers and requires a
versioned coding-Worker probe before implementation use. Local dogfooding
showed a remaining operational gap: after a Developer adds, replaces, or
removes an Ollama model, Canto needs an explicit way to reconcile current local
inventory with persisted model, probe, usage, and selection evidence.

This design extends the existing governed AI Worker catalog. It does not create
a second model registry, automatically load every model, or trust model
marketing as proof of Worker capability.

## Core Rule

Declared capabilities nominate a local model for testing. Observed Canto
evidence determines whether it may work.

Local model onboarding and refresh use three evidence layers:

1. **Runtime facts** from the configured local endpoint: exact model ID,
   digest, size, quantization, family, context metadata, declared capabilities,
   and discovery timestamp where available.
2. **Curated metadata** from model cards or official documentation: intended
   use, known tool format, recommended task shape, license, and source URL.
   This metadata is advisory and provenance-labeled.
3. **Observed Canto evidence** from versioned probes and governed Runs: tool
   execution, file editing, command execution, scope adherence, latency,
   reliability, and outcome quality.

Automatic implementation selection requires current runtime availability and
current successful Canto probe evidence. Curated metadata never grants
eligibility by itself.

## Identity And Lifecycle

The existing immutable execution provenance identity remains:

```text
(endpoint_id, provider_model_id, resolved_version)
```

The current catalog projection continues to use `model_key` as the stable
lookup key, normally `endpoint_id:provider_model_id`. A changed digest updates
that current projection while snapshots, probes, usage, sessions, and Results
retain the prior resolved version. For Ollama, `resolved_version` is the exact
digest when the endpoint supplies one. Tags are display or lookup aliases, not
stable execution provenance.

Availability and Worker classification are separate dimensions:

```text
availability: available | missing | endpoint_unreachable | unknown
classification: implementation | advisory | unavailable | unvalidated
probe_state: current | stale | absent
```

- `available` means the latest successful refresh returned that exact model.
- `missing` means a successful refresh no longer returned a previously known
  model.
- `endpoint_unreachable` means reconciliation could not determine inventory;
  Canto must not mark every model missing after an endpoint failure.
- `unknown` covers legacy records before their first reconciliation.
- Classification preserves the last observed Worker behavior.
- The existing `unavailable` classification remains readable for compatibility
  and means the last probe could not classify Worker behavior. It is not a
  substitute for current runtime availability.
- A missing model may retain `implementation` classification historically but
  is ineligible because it is not currently available.
- A digest or relevant runtime-metadata change marks prior probes stale.

Canto preserves historical model records, probes, usage, selection decisions,
and Result provenance. Refresh never hard-deletes referenced evidence.

## Refresh Command

The user-facing routine command is:

```bash
canto ai model refresh ENDPOINT_ID
```

`discover` remains the first-time endpoint/catalog operation. `refresh` is the
ongoing reconciliation operation and must:

1. validate that the endpoint exists, is enabled, and is local;
2. query current inventory once without loading or running each model;
3. normalize returned runtime metadata;
4. compare current inventory with the last successful snapshot;
5. add new records as `available`, `unvalidated`, and `probe_state=absent`;
6. update unchanged records without invalidating current probes;
7. mark changed digests or probe-relevant metadata as `probe_state=stale`;
8. mark previously known but absent models as `missing`;
9. preserve historical evidence and create an immutable reconciliation record;
10. print a deterministic change summary and recommended next commands.

An endpoint or authentication failure records endpoint health and exits
non-zero. It does not mark models missing because no authoritative inventory
was obtained.

Example output:

```text
Endpoint: local-ollama

Added:
  local-ollama:qwen3-coder:30b

Changed:
  local-ollama:qwen2.5-coder:14b
    digest changed; coding probe is stale

Missing:
  local-ollama:codestral:22b

Unchanged: 4

Next:
  canto ai model probe local-ollama:qwen3-coder:30b
```

Machine-readable JSON exposes the same categories, exact identifiers,
previous/current digests, reasons, snapshot IDs, and timestamps.

## Probe Behavior

Refresh is inventory-only by default. It must not serially load every local
model, consume large amounts of memory, or run paid/cloud probes.

An explicit convenience option may be added:

```bash
canto ai model refresh local-ollama --probe-new
```

Rules:

- only newly discovered local models are probed;
- each model is probed sequentially unless a later resource scheduler safely
  authorizes concurrency;
- failures are isolated per model and remain inspectable;
- changed models require explicit re-probe unless the Developer also supplies
  `--probe-stale`;
- no cloud fallback is permitted during local-model refresh or probing.

## Metadata Enrichment

Web research is optional enrichment, not refresh authority. A future
Orchestrator skill may search official model cards and vendor documentation and
produce a proposed metadata record containing:

- model family and intended use;
- coding and tool-calling claims;
- prompt/template requirements;
- context and resource guidance;
- license and redistribution constraints;
- source URLs, retrieval time, and content checksum;
- confidence and unresolved conflicts.

The Developer reviews the proposal before Canto stores it. Stored fields are
marked `declared` or `curated`; they never overwrite `observed` probe evidence.
Search snippets, community reports, and model-generated summaries cannot make a
model eligible for implementation work.

The first implementation may support manually supplied metadata files before
automating web research. Automated tests remain network-free.

## Status And Cleanup

Read-only inspection:

```bash
canto ai model status --endpoint local-ollama
canto ai model show local-ollama:qwen2.5-coder:14b
```

`status` groups models by availability, classification, and probe state and
shows the last successful refresh. It must distinguish an unreachable endpoint
from models confirmed missing.

Historical cleanup is explicit:

```bash
canto ai model forget local-ollama:codestral:22b
```

`forget` is refused when a model is available or referenced by retained probes,
usage, selection decisions, delegation sessions, or Results. A future archival
policy may compact unreferenced metadata, but refresh itself never deletes it.

## Selection Rules

A local model is eligible for automatic implementation selection only when:

- its endpoint is enabled and currently healthy;
- availability is `available`;
- its exact digest matches the current catalog;
- classification is `implementation`;
- probe state is `current` for the active probe/harness version;
- repository, task, resource, and budget policy allow it.

Advisory models may be selected only for explicitly advisory work. Missing,
unknown, stale, unavailable, or endpoint-unreachable models are rejected with
specific explain output. Canto does not silently fall back from local to cloud.

## State Additions

Extend existing records conservatively:

- `AIModelRecord`: availability, availability reason, last-seen timestamp,
  missing-since timestamp, runtime metadata, metadata provenance, and explicit
  probe state;
- `ModelCatalogSnapshot`: refresh mode, authoritative-success flag, added,
  changed, missing, and unchanged model keys;
- `ModelReconciliationRecord`: immutable previous/current snapshot comparison;
- optional `ModelMetadataRecord`: source-labeled declared/curated metadata.

Legacy records load with `availability=unknown`. Existing classifications,
probes, selections, usage, and exact model provenance remain unchanged.

## Security And Resource Boundaries

- Refresh contacts only the named configured endpoint.
- Local refresh never contacts cloud endpoints or performs web research.
- Metadata enrichment is a separate explicit network operation.
- Refresh does not pull, delete, load, run, or unload Ollama models.
- No model receives repository context during refresh.
- Probe work remains disposable, bounded, and separate from real repositories.
- Endpoint errors and metadata must not expose secrets or credential material.

## Work Packets

CP-1515 is this design packet and is complete when approved.

1. CP-1516 — Model Availability And Metadata Provenance Fields
2. CP-1517 — Local Endpoint Reconciliation Service
3. CP-1518 — `canto ai model refresh` And Change Summary
4. CP-1519 — Model Status, Explain, And Safe Forget
5. CP-1520 — Optional Local Probe Queue And Metadata Enrichment Boundary
6. CP-1521 — Dogfood, Compatibility, Security, And Documentation Pass

## Acceptance

- A newly installed Ollama model appears as available and unvalidated after one
  refresh.
- A removed model is marked missing without deleting historical evidence.
- A changed digest makes prior probe evidence stale.
- Endpoint failure does not falsely mark all models missing.
- Unchanged models retain current probes.
- Selection requires available plus current implementation evidence.
- Refresh performs no model execution unless explicitly requested.
- Status and JSON output explain every lifecycle state.
- Forget refuses referenced or currently available models.
- Tests use fake Ollama responses and require no network or downloaded model.
- Existing cloud discovery, model records, probes, tasks, and frozen
  orchestration contracts remain compatible.

## Non-Goals

- Pulling, deleting, loading, or unloading local models.
- Benchmark leaderboards or autonomous model promotion.
- Treating web search or model cards as proof of tool capability.
- Background polling, filesystem watchers, or an Ollama daemon manager.
- Silent probe execution or local-to-cloud fallback.
- Remote model registry, multi-user model administration, or shared hardware
  scheduling.
