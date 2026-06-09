# Registry & Identifier Unification Plan

Status: **proposal / design** — no code changes implied by this document.
Audience: Canto maintainers deciding what to build before freezing the public contract.

---

## 1. Why this is the first thing to fix

Canto currently maintains **two registries with two different addressing schemes**, and the
orchestration layer reads one while the execution layer reads the other. Until a plan step
resolves deterministically to something the runner can execute, nothing downstream
(planning over HTTP, a single approval model, a frozen contract) can be built on solid
ground. This is the highest-leverage change.

### The two registries

| | Runtime registry | Capability registry |
|---|---|---|
| Class | `Registry` (`canto/core/registry.py:13`) | `Registry` (`canto/core/local_registry.py:210`) |
| Addresses by | `skill` name + `provider` name → `providers[(skill, provider)]` | capability `name` + semver `version` |
| Source of truth | YAML on disk: `skills/*/skill.yaml`, `skills/*/providers/*/provider.yaml`, `tools/*/tool.yaml` | installed `.canto` packages under `~/.canto/installed/<name>/<version>` indexed in `~/.canto/registry/index.json` |
| Read by | `JobService` (`jobs.py:84,96,112`), `GET /registry`, `GET /skills/...` | `CapabilityMatcher` / `WorkflowPlanner` / `Orchestrator` (`orchestration.py:163,196,276,284`) |
| Unit | executable provider (typed inputs/outputs, runner, permissions) | distributable capability (logical input/output names, dependencies, risk) |

### Where they already connect

The bridge exists but is only half-wired:

- The runtime `Registry` constructor accepts `capability_roots` and loads each installed
  capability's `skills/` and `tools/` subtrees into the runtime view
  (`registry.py:14–22`, `reload()` at `registry.py:46–49`).
- `CapabilityRegistry.execution_roots()` (`local_registry.py:428`) validates every installed
  capability (checksum + manifest) and returns their directory paths.
- The **CLI** wires these together: `_runtime()` passes
  `_capability_registry().execution_roots()` into the runtime `Registry` (`cli.py:51`).

So via the CLI, an installed capability's providers *do* become runnable jobs.

### Where they do NOT connect (the gaps to close)

1. **The HTTP server ignores installed capabilities.** `create_app()` builds
   `Registry(settings.skills_dir, settings.tools_dir)` with **no `capability_roots`**
   (`server.py:16`). Result: `POST /jobs` and `GET /registry` over HTTP can only see the
   repo's built-in `skills/` — the entire installed package ecosystem is invisible to the
   API. The CLI and the HTTP API therefore disagree about what exists.

2. **Plan steps don't carry a runnable identity.** A plan step addresses a `capability`
   (`orchestration.py` `WorkflowStep.capability`), and `create_plan()` records
   `capability_providers[capability] = sorted(manifest.providers)[0]` — a bare provider
   *name* (`orchestration.py:290`). To create a job, `JobService` needs a
   `(skill, provider)` pair (`jobs.py:96,112`). There is no defined mapping from a
   capability manifest's flat `providers: [str]` / `skills: [str]` lists to the
   `(skill, provider)` tuple the runner uses. The capability `name` is not guaranteed to
   equal any `skill` name.

3. **Plan I/O names ≠ job inputs.** Capability manifest `inputs`/`outputs` are **logical
   string lists** (`capability_manifest.py:27–30`), and the planner wires them as artifact
   names (`WorkflowStep.requires`/`produces`). But a job's `inputs` is a **typed key→value
   dict** validated against `provider.inputs` declarations (`jobs.py:55–81`). The executor
   callback hands a step `resolved: dict[str, str]` of artifact paths
   (`orchestration.py:325–344`), which is not the shape `JobService` validates.

4. **Two approval models.** Plans approve via `ExecutionPlan.status: draft → approved`
   (`orchestration.py:296`, in-process only). Jobs approve via a persisted `Approval` object
   and `POST /approvals/{id}/approve` (`jobs.py:179–195`, `server.py:93`). They share no
   code and neither is aware of the other.

---

## 2. Decision to make: the canonical identifier

Everything else follows from one choice. Three options:

| Option | Execution identity | Trade-off |
|---|---|---|
| **A. `(skill, provider)` is canonical; capability is packaging-only** (recommended) | jobs and plans both address `(skill, provider)` | Minimal change to the proven execution path; capability becomes a distribution/versioning wrapper that *contains* skills/providers. Requires capability manifests to expose their `(skill, provider)` pairs explicitly. |
| B. `capability@version` is canonical; (skill, provider) derived | plans address `capability@version`, runner resolves down | Cleaner for the package vision, but forces a rewrite of `JobService`/runner addressing and the HTTP job contract. |
| C. Keep both, add an explicit crosswalk table | a stored map `capability@version ⇄ [(skill, provider)]` | Lowest blast radius, but institutionalizes the dual model rather than resolving it. |

**Recommendation: Option A.** The execution path (`JobService` + `runner.py` + the
`(skill, provider)` model + the `Approval` flow) is the mature, tested, security-bearing
half of the system. Make it canonical. Treat a *capability* as the **unit of distribution,
versioning, checksums, and risk** that *packages* one or more `(skill, provider)`
executables — not as a competing execution address.

This means a capability manifest must make its contained `(skill, provider)` pairs and their
artifact wiring explicit, so a plan step can name exactly what to run.

---

## 3. Target data flow

```
install (.canto)  ──►  CapabilityRegistry (versioned, checksummed, risk)
                            │ execution_roots()  ← validated installed dirs
                            ▼
                       Runtime Registry  ──►  /registry, /skills, JobService, runner
                       (skills+providers from built-in dirs AND every installed capability)
                            ▲
discover / plan ────────────┘   plan steps reference (skill, provider) drawn from the SAME
                                runtime registry, so every planned step is runnable as a job.
```

One registry view feeds discovery, planning, inspection, **and** execution. Capability
metadata (version, checksum, risk) remains owned by `CapabilityRegistry` and is *attached*
to runtime entries, not duplicated.

---

## 4. Phased plan (documentation-level steps)

Each step lists the files it would touch so scope is visible. No code is changed by this doc.

### Phase 0 — Close the HTTP/CLI registry split (smallest, unblocks everything)
- Make `create_app()` build its runtime `Registry` with
  `capability_roots = CapabilityRegistry.local().execution_roots()`, mirroring `cli.py:51`.
  Touches: `canto/api/server.py:14–17`.
- Decide reload semantics: capabilities can be installed while the server runs, but the
  registry is built once at `create_app()`. Either (a) rebuild on demand, or (b) expose an
  authenticated `POST /registry/reload`. Recommend (a) lazy rebuild keyed off the
  `index.json` mtime to keep the contract simple.
- Acceptance: `GET /registry` over HTTP returns the same skills/providers the CLI sees after
  an `install`.

### Phase 1 — Make capability → (skill, provider) explicit and validated
- Extend the capability manifest so each contained provider declares the `(skill, provider)`
  it exposes and the artifact names it consumes/produces. Today `providers`/`skills` are
  flat `list[str]` (`capability_manifest.py:27–29`) and `inputs`/`outputs` are flat logical
  names (`capability_manifest.py:30`); there is no link between them.
  Touches: `canto/core/capability_manifest.py`, `docs/capability-manifest.md`.
- Add a manifest validation rule: every declared provider must resolve to a
  `skills/<skill>/providers/<provider>/provider.yaml` inside the package, and every logical
  `output` must be produced by exactly one contained provider. This makes the planner's
  output→input wiring (`orchestration.py:217–222`) resolvable to real providers.
- Acceptance: `canto capability validate` fails a package whose logical I/O cannot be mapped
  to a contained provider.

### Phase 2 — Plan steps carry a runnable reference
- Change plan construction so each `WorkflowStep` records the resolved `(skill, provider)`
  (and the capability `version` for provenance), instead of `sorted(manifest.providers)[0]`
  (`orchestration.py:290`). Keep `capability_versions` for audit.
  Touches: `canto/core/orchestration.py` (`WorkflowStep`, `ExecutionPlan`, `create_plan`).
- Define how planned logical artifact names map to a provider's typed `inputs`. Two
  sub-decisions: (a) artifact-name → input-name binding (explicit in the manifest, per
  Phase 1), and (b) where user-supplied scalar inputs (`missing_inputs`) enter — they should
  enter as job `inputs`, not as artifacts.
- Acceptance: given an approved plan, each step has enough information to build a valid
  `JobRequest` with no caller-supplied logic.

### Phase 3 — Replace the executor callback with the real runner
- `Orchestrator.execute()` currently delegates each step to a caller-supplied `executor`
  (`orchestration.py:305–344`), bypassing the runner and its bounds. Replace the default
  execution path with "create a job via `JobService` and run it," collecting declared
  outputs into the artifact map that feeds the next step.
  Touches: `canto/core/orchestration.py`, integration with `canto/core/jobs.py`.
- Keep a callable seam *internally* for tests/alternate executors, but it is no longer part
  of the public contract.
- Acceptance: executing a plan runs each provider in the bounded subprocess (`runner.py`),
  produces artifacts under `work/jobs/<job_id>/`, and honors policy.

### Phase 4 — One approval model
- Retire `ExecutionPlan.status` approval as a separate concept. When a plan step's underlying
  job triggers `evaluate_policy()` reasons (`policy.py:22–49`), surface that as the existing
  `Approval` object. A plan is "approved to run" when its gated steps' approvals are granted.
  Touches: `canto/core/orchestration.py`, `canto/core/jobs.py`, `canto/models/schemas.py`.
- Decide plan-level vs step-level granularity: recommend **step-level** approvals (reusing
  `Approval`) with a plan-level rollup status derived from them, so the auditable, atomic
  `Approval` flow (`state.py` CAS) stays the single source of truth.
- Acceptance: there is exactly one approval object type and one approve/reject endpoint in
  the system.

---

## 5. Backward compatibility & migration

- **Installed packages:** Phase 1 changes the manifest schema. Use the existing
  `extra="allow"` forward-compat posture (`capability_manifest.py:21`) — add the new
  provider-mapping fields as optional, validated only when present, so already-installed
  capabilities keep loading. Bump a manifest `schema_version` (does not exist today — see
  the contract doc) so consumers can detect the richer form.
- **CLI:** `canto plan` / `execute` / `explain` keep working; only their internal resolution
  changes. The `executor` argument to `Orchestrator.execute` becomes optional/internal.
- **HTTP:** Phase 0 is additive (the API simply sees more). The orchestration endpoints are
  new (see the contract doc) and don't alter `POST /jobs`.

## 6. Acceptance criteria for "registries unified"

1. CLI and HTTP API return identical `GET /registry` output for the same installed state.
2. Every `WorkflowStep` in a saved `ExecutionPlan` resolves to a runnable `(skill, provider)`
   with no caller-supplied mapping.
3. `Orchestrator.execute()` runs steps through `JobService`/`runner.py` by default.
4. There is one approval object type across jobs and plans.
5. `capability@version`, checksum, and risk are still attached to every executable surfaced
   from an installed package (provenance preserved).

## 7. Open questions for the maintainers

- Should a single capability be allowed to expose **multiple** `(skill, provider)` pairs, or
  is one capability = one provider the intended simplification?
- When two installed capabilities provide the same logical output artifact, how is the
  ambiguity resolved at plan time? (Today `create_plan` errors on >1 installed *version* of
  the same capability — `orchestration.py:279` — but not on two capabilities producing the
  same artifact.)
- Live registry reload on install: lazy mtime check vs explicit reload endpoint?
