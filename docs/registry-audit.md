# Registry Audit

This audit describes the current registry, orchestration, execution, and approval
boundaries before the v2.1 registry unification work. It documents existing
behavior; it does not define a refactor or change runtime ownership.

## Identity Decision

`(skill, provider)` is the canonical execution identity. `JobService`, provider
lookup, policy evaluation, dependency checks, and the runner all use this pair.

`capability@version` is the packaging and provenance identity. It identifies an
installed distribution, its manifest, checksum, risk metadata, and filesystem
location. A capability may expose one or more executable `(skill, provider)`
pairs, but its package identity is not itself a runnable job identity.

## Component Ownership

| Component | Owns | Identifiers | Read by | Written by |
| --- | --- | --- | --- | --- |
| Runtime Registry (`canto.core.registry.Registry`) | Loaded skill, provider, and tool manifests; provider lookup used for execution | Skill name, tool name, and `(skill, provider)` | `JobService`, CLI registry inspection, HTTP registry and skill/provider endpoints | Rebuilt from configured source directories and optional installed capability roots during construction or reload |
| Capability Registry (`canto.core.local_registry.Registry`) | Installed package metadata, manifest inspection, package integrity, install/remove/export operations, and executable package roots | `capability@version`; persisted as separate `name` and `version` fields | CLI list/search/inspect/install/remove/export commands, matcher, planner, orchestrator, CLI runtime construction | Capability install/remove operations through `RegistryStore` |
| `RegistryStore` | The local registry index and installed capability directories | `capability@version`; index entries also carry path, checksum, risk, and installed state | Capability Registry | Capability Registry operations |
| `JobService` | Job lifecycle, input validation, dependency and policy checks, provider execution, artifacts, and job-level approvals | `job_id`, `(skill, provider)`, and `approval_id` | CLI execution adapter and HTTP job/approval routes | Jobs, events, artifacts, approval records, and a Runtime Registry snapshot through `StateStore` |
| `WorkflowPlanner` | Deterministic capability matching and artifact-based workflow candidate construction | Capability name in each `WorkflowStep` | `Orchestrator` and CLI plan flow | In-memory `PlanPreview` and `WorkflowCandidate` values only |
| `Orchestrator` | Plan creation, package-version/provider resolution, approval status, ordered step dispatch, and plan explanation | `plan_id`, capability name, plus separate capability-to-version and capability-to-provider maps | CLI plan/execute/explain commands | Saved plans through `PlanStore` |
| `PlanStore` | JSON persistence for orchestration plans under the local Canto home | `plan_id` | `Orchestrator` | `Orchestrator` |
| Job approval | Policy-gated authorization for a specific job before provider execution | `approval_id` linked to `job_id` and therefore to `(skill, provider)` | `JobService` and HTTP approval routes | `JobService` through `StateStore` |
| Plan approval | Authorization intent for an orchestration plan; currently represented by plan status and `approved_at` | `plan_id` | `Orchestrator` and CLI execute/explain flows | `Orchestrator` through `PlanStore` |

## Current Data Flow

### Capability installation and discovery

The Capability Registry reads `~/.canto/registry/index.json` through
`RegistryStore`. Installed entries point to versioned directories and carry the
package checksum and risk level. Discovery and planning inspect the installed
capability manifest and rank packages using manifest metadata such as name,
description, intents, inputs, and outputs.

This path uses `capability@version` because it is reasoning about installed
packages and their provenance, not directly invoking a provider.

### CLI execution

The CLI obtains validated installed package directories from the Capability
Registry and passes those directories as `capability_roots` when constructing
the Runtime Registry. The Runtime Registry scans their skill, provider, and tool
manifests together with the built-in manifests.

For an approved plan, the CLI adapter reads the provider identifier saved by the
Orchestrator, splits it into `skill` and `provider`, creates a `JobRequest`, and
delegates execution to `JobService`. From that point onward, execution is keyed
by `(skill, provider)`.

### HTTP execution

The HTTP application constructs the Runtime Registry from only the configured
built-in skills and tools directories. Its registry endpoints and `JobService`
therefore use that runtime view. HTTP jobs directly accept `skill` and
`provider`, which already matches the canonical execution identity.

### Approvals

There are two independent approval representations:

- A job approval is a persisted `Approval` record created after provider policy
  evaluation. It is linked to a job and gates provider execution.
- A plan approval is the `approved` status and timestamp on an `ExecutionPlan`.
  It records authorization intent for the plan and gates orchestration dispatch.

Neither approval representation currently provides a unified registry view.
Plan approval does not replace the provider-level policy approval that may be
created later by `JobService`.

## Current Mismatches

### CLI and HTTP registry views

The CLI runtime includes validated installed capability roots. The HTTP runtime
does not. As a result, `canto registry`, CLI plan execution, and HTTP `/registry`
or `/jobs` can disagree about which `(skill, provider)` pairs are available.
`JobService` snapshots whichever Runtime Registry instance it receives, so the
stored snapshot also depends on the construction path.

### Plan steps and runnable job identity

`WorkflowStep` identifies a step by capability name and artifact requirements.
`ExecutionPlan` stores package versions and provider identifiers in separate
maps keyed by capability name. At execution time, the CLI parses the selected
provider string into the `(skill, provider)` pair required by `JobService`.

This creates an indirect contract between package metadata, plan persistence,
the CLI adapter, and the Runtime Registry. A plan step does not itself preserve
the exact canonical execution identity, and the package name is not guaranteed
to equal the skill name. Multiple providers are reduced to the first sorted
manifest declaration during plan creation.

## Unification Boundary

The unified executable registry view must answer which `(skill, provider)` pairs
can run and retain their `capability@version` provenance, checksum, path, and
risk metadata when they originate from an installed package. Discovery and
planning may select packages, but an executable plan step must resolve to an
exact `(skill, provider)` before dispatch. The package identity remains attached
for traceability and validation; it does not replace the runner identity.

This boundary preserves the existing `JobService` and runner contract while
allowing CLI, HTTP, planning, execution, and approvals to refer to the same set
of executable providers.
