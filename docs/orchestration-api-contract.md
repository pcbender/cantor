# Canto Orchestration API Contract v1.0

Status: **frozen and implemented as of v2.2**, subject to the deferred items in
`docs/contract-freeze-audit.md`.
Purpose: define the single HTTP contract an external orchestrator uses to talk to Canto,
spanning **discover → plan → approve → execute → observe**. The registry unification this
contract depends on shipped in v2.1 (`docs/registry-unification-plan.md`); all endpoints
below are live in `canto/api/server.py`.

> **Authoritative artifacts.** The machine-readable contract is `docs/openapi.json` and
> `docs/schemas/*.json`. This document is the human-readable design narrative. The inline
> `file:line` citations are illustrative references to the implementing modules and are not
> kept in lockstep with the source; when they disagree with the code, the code and the
> OpenAPI export win.

---

## 1. Problem this contract solved

Before v2.1/v2.2, the execution half was on HTTP (`POST /jobs`, `GET /jobs/...`,
`POST /approvals/...`) but the **orchestration half was in-process only**: `CapabilityMatcher`,
`WorkflowPlanner`, and `Orchestrator` had no endpoints. An out-of-process orchestrator — the
model-agnostic caller the project targets — could inspect the static registry and fire one
capability at a time, but could not discover, plan multi-step work, or drive a governed
workflow over the wire.

This contract put the whole loop on HTTP, reuses the existing `Approval` object as the one
approval model, and makes Canto (not the caller) execute the steps. As of v2.2 it is
implemented and frozen.

## 2. Principles

1. **One registry view.** Discovery, planning, and execution read the unified runtime
   registry (per the unification plan). What you can discover, you can run.
2. **Canto owns execution.** The caller never supplies an executor. Plans run through
   `JobService`/`runner.py` under policy and bounds.
3. **One approval model.** The persisted `Approval` object (`schemas.py:68–78`) and
   `/approvals/{id}/...` endpoints are the only gate. Plans reference approvals; they don't
   invent a second mechanism.
4. **Self-describing misses.** A miss returns a `suggested_action` that is itself a
   submittable request, preserving the existing `missing_capability()` ergonomics
   (`jobs.py:83–109`).
5. **Read before write.** `discover` and `plan` are side-effect free. Only `approve` and
   `execute` change state.
6. **Versioned and machine-readable.** Every response carries a contract version; the API
   ships an OpenAPI document and the manifests ship JSON Schemas.

## 3. Resource model

```
Capability (versioned, installed)         ── discovery surface
Plan        (draft → approved → running → completed/failed)  ── orchestration unit
  └─ Step   (resolved to skill+provider, requires/produces artifacts)
Job         (one step's execution; existing model)           ── execution unit
Approval    (gate shared by jobs and plans; existing model)
Artifact    (files under work/jobs/<job_id>/; existing model)
```

A Plan is the new top-level orchestration resource. Each approved Plan, when executed,
creates one Job per Step. Jobs, Approvals, Artifacts, and their endpoints are unchanged from
today.

---

## 4. Endpoints

### Existing (unchanged, retained)
- `GET /health`
- `GET /registry`
- `GET /skills/{skill}` · `GET /skills/{skill}/providers/{provider}`
- `POST /jobs` · `GET /jobs/{id}` · `GET /jobs/{id}/events` · `GET /jobs/{id}/artifacts` · `GET /jobs/{id}/artifacts/{name}`
- `POST /approvals/{id}/approve` · `POST /approvals/{id}/reject`

### Orchestration (added in v2.2, live in `canto/api/server.py`)
- `POST /discover` — rank capabilities for a goal (read-only)
- `POST /plans` — build a plan from a goal (read-only persistence of a draft)
- `GET /plans/{plan_id}` — fetch a plan and its status
- `GET /plans/{plan_id}/explain` — why each step was chosen, with risk
- `POST /plans/{plan_id}/approve` — approve a plan for execution (creates/links `Approval`s)
- `POST /plans/{plan_id}/execute` — run an approved plan (Canto executes the steps)
- `GET /plans/{plan_id}/events` — merged lifecycle + per-step job events
- `GET /plans` *(not shipped in v1.0; reserved for a future list endpoint)* — list plans

---

## 5. Schemas

All examples are JSON. Field names mirror existing Pydantic models where they already exist
(`CapabilityMatch`, `WorkflowStep`, `ExecutionPlan`, `PlanExplanation`,
`orchestration.py:20–66, 368–392`) so the contract is close to the in-process shapes.

### 5.1 `POST /discover`

Request:
```json
{ "goal": "inventory my wordpress site", "limit": 10 }
```

Response `200` (maps to `CapabilityMatcher.discover`, `orchestration.py:161`):
```json
{
  "contract_version": "1.0",
  "goal": "inventory my wordpress site",
  "matches": [
    {
      "name": "wordpress_inventory",
      "version": "1.0.0",
      "score": 120,
      "reasons": ["intent matched: inventory, site", "name matched: wordpress"],
      "intents": ["site_inventory"],
      "inputs": ["website_url"],
      "outputs": ["inventory.json"],
      "risk": "low"
    }
  ]
}
```
Empty `matches` is a normal `200`, not an error.

### 5.2 `POST /plans`

Request:
```json
{
  "goal": "inventory my wordpress site then build a migration report",
  "inputs": { "website_url": "https://example.com" }
}
```

Response `200` — a persisted draft `ExecutionPlan` (maps to `WorkflowPlanner.plan` +
`Orchestrator.create_plan`, `orchestration.py:188,266`):
```json
{
  "contract_version": "1.0",
  "plan_id": "plan_20260609_a1b2c3",
  "status": "draft",
  "goal": "inventory my wordpress site then build a migration report",
  "steps": [
    {
      "index": 0,
      "capability": "wordpress_inventory",
      "version": "1.0.0",
      "skill": "site_inventory",
      "provider": "wordpress_crawler",
      "reason": "intent matched: inventory, site",
      "requires": ["website_url"],
      "produces": ["inventory.json"],
      "risk": "low"
    },
    {
      "index": 1,
      "capability": "migration_report",
      "version": "0.1.0",
      "skill": "migration_report",
      "provider": "local_markdown_report",
      "reason": "produces report.md; consumes inventory.json from step 0",
      "requires": ["inventory.json"],
      "produces": ["report.md"],
      "risk": "low"
    }
  ],
  "missing_inputs": [],
  "produced_artifacts": ["inventory.json", "report.md"],
  "created_at": "2026-06-09T12:00:00Z"
}
```
`skill`/`provider`/`version` on each step are resolved from the capability's execution
bindings (the v2.1 unification; see `WorkflowStep` and `resolve_provider_binding` in
`orchestration.py`). If required inputs aren't satisfied, they appear in `missing_inputs` and
execution is refused until provided.

If the goal matches nothing or names an uninstalled capability, return a miss with a
submittable action (mirrors `missing_capability`, `jobs.py:83`):
```json
{
  "contract_version": "1.0",
  "status": "missing_capability",
  "message": "No installed capability satisfies: deploy to netlify",
  "suggested_action": {
    "skill": "scaffold_skill",
    "provider": "local_scaffolder",
    "inputs": { "skill": "netlify_deploy" },
    "requires_approval": true
  }
}
```

### 5.3 `GET /plans/{plan_id}`
Returns the same object as `POST /plans`, with current `status` and any
`approval_ids`, `error`, `completed_at`.

### 5.4 `GET /plans/{plan_id}/explain`
Maps to `Orchestrator.explain` (`orchestration.py:368`):
```json
{
  "contract_version": "1.0",
  "plan_id": "plan_20260609_a1b2c3",
  "goal": "...",
  "status": "approved",
  "steps": [
    {
      "capability": "wordpress_inventory",
      "version": "1.0.0",
      "skill": "site_inventory",
      "provider": "wordpress_crawler",
      "reason": "intent matched: inventory, site",
      "inputs": ["website_url"],
      "outputs": ["inventory.json"],
      "risk": "low",
      "missing_values": []
    }
  ]
}
```

### 5.5 `POST /plans/{plan_id}/approve`

Request:
```json
{ "approved_by": "cantor", "note": "reviewed scope" }
```

Behavior (one approval model, unified in v2.1): for each step whose underlying job would
trigger `evaluate_policy()` reasons, an `Approval` is created/granted. Steps with no triggers
need no approval.

Response `200`:
```json
{
  "contract_version": "1.0",
  "plan_id": "plan_20260609_a1b2c3",
  "status": "approved",
  "approved_at": "2026-06-09T12:01:00Z",
  "approvals": [
    { "approval_id": "approval_20260609_77aa10", "step_index": 0,
      "status": "approved", "reason": "Network access to non-approved domain example.com" }
  ]
}
```
`409` if the plan is not in `draft`, or if a referenced approval is already decided
(mirrors the job approval CAS semantics, `jobs.py:240`).

### 5.6 `POST /plans/{plan_id}/execute`

Request: empty body (or `{ "mode": "live" | "dry_run" }`, default inherits the plan's policy).

Behavior: refuses unless `status == "approved"` and `missing_inputs == []`
(mirrors `orchestration.py:311,317`). Canto executes each step **as a Job** through
`JobService`/`runner.py`, threading each step's `produces` into the next step's `requires`.
The caller supplies **no executor**.

Response `202 Accepted` (async, see §6):
```json
{
  "contract_version": "1.0",
  "plan_id": "plan_20260609_a1b2c3",
  "status": "running",
  "step_jobs": [
    { "step_index": 0, "job_id": "job_20260609_aa01bb" }
  ]
}
```

Terminal state via `GET /plans/{plan_id}` (maps to `PlanExecutionResult`,
`orchestration.py:362`):
```json
{
  "plan_id": "plan_20260609_a1b2c3",
  "status": "completed",
  "artifacts": { "inventory.json": "work/jobs/job_.../inventory.json",
                 "report.md": "work/jobs/job_.../report.md" },
  "step_jobs": [
    { "step_index": 0, "job_id": "job_20260609_aa01bb", "status": "completed" },
    { "step_index": 1, "job_id": "job_20260609_cc22dd", "status": "completed" }
  ],
  "completed_at": "2026-06-09T12:05:00Z"
}
```
On failure: `status: "failed"`, `error: {code, message}`, and the failing `step_index`.

### 5.7 `GET /plans/{plan_id}/events`
Merged, time-ordered stream of plan lifecycle events plus the per-step job events already
emitted today (`jobs.py` event types). Each event carries `step_index` and `job_id` when it
originates from a step. See §6 for the streaming form.

---

## 6. Async & completion semantics

The current job model is **fire-and-poll**: `POST /jobs` returns `queued` and the only way to
learn the result is to poll `GET /jobs/{id}` (`server.py:52–62`). Plans inherit this.

The frozen baseline is:

- Keep `202 + poll` as the completion model.
- Document the polling contract explicitly: terminal statuses are
  `completed | failed | rejected | cancelled`; clients poll until terminal.

Server-Sent Events are deferred. Adding an SSE representation later is
additive; it does not replace polling in contract v1.0.

## 7. Authentication (placeholder)

There is **no auth today** (`server.py` has none; `requested_by`/`approved_by` are
unauthenticated free strings — `schemas.py`). The approval model assumes a trusted human
"Cantor" the API cannot currently authenticate.

Contract v1.0 reserves the following surface without implementing authentication:
- A bearer token (`Authorization: Bearer …`) on all mutating endpoints (`/plans`,
  `/plans/*/approve`, `/plans/*/execute`, `/jobs`, `/approvals/*`).
- An authenticated identity that populates `requested_by` / `approved_by` server-side,
  rather than trusting client-supplied strings.
- Default binding remains `127.0.0.1`; auth is required the moment the bind address is not
  loopback.

The operational boundary and deferred work are documented in
`docs/auth-placeholder.md`.

## 8. Versioning & freeze artifacts

- **`contract_version`** on every response body (start at `"1.0"`). Independent of the app
  `__version__` (`0.1.0`) and of capability/manifest versions.
- **Manifest `schema_version`** remains deferred. Capability manifests retain
  their current forward-compatible optional-field policy.
- **Published OpenAPI** document generated from the FastAPI app, checked into `docs/`.
- **Published JSON Schemas** for the capability/skill/provider/tool manifests and for the
  package layout (`docs/capability-manifest.md`, `docs/capability-packaging.md` describe these
  informally today; freeze means machine-readable).
- **Compatibility statement:** additive fields are minor; removing/renaming fields or
  changing status enums is a major `contract_version` bump.

## 9. Mapping to implementing internals

| Contract endpoint | Backing code |
|---|---|
| `POST /discover` | `CapabilityMatcher.discover` |
| `POST /plans`, `GET /plans/{id}` | `WorkflowPlanner.plan` + `Orchestrator.create_plan` + `PlanStore` |
| `GET /plans/{id}/explain` | `Orchestrator.explain` |
| `POST /plans/{id}/execute` | `Orchestrator.prepare_execution` + `Orchestrator.execute`, backed by `JobService`/`runner.py` (the v2.1 unification replaced the caller-supplied executor with `JobService`) |
| `POST /plans/{id}/approve` | `Orchestrator` approval glue over the existing `Approval` flow (`jobs.py`, `state.py` CAS) |
| step execution, artifacts, events | `JobService` + `runner.py` + `artifacts.py` |

## 10. Explicitly deferred (not in v1.0 freeze)

- Remote registry browse/download/trust (install is local-only today).
- Package signing / provenance beyond SHA-256 checksums.
- Dependency version-range resolution (current dependency checking is presence-only —
  `dependencies.py`).
- Parallel / branching plans (execution is linear today — `orchestration.py:324`).
- Non-Python runners (`runner.py:21` is Python-only); the runner field is in the contract but
  only `type: python` is guaranteed in v1.0.
