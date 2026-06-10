# Canto Roadmap

Status: updated after completion of v1.x, v2.0, v2.1 Registry Unification, and v2.2 Contract Freeze.

Canto has moved beyond proof-of-concept. The system can now package capabilities, install them, discover them, compose approved plans, execute those plans through the bounded JobService/runner path, expose orchestration over HTTP, and publish a frozen v1.0 orchestration contract.

The next phase begins with **v3.0 — External Orchestrator Integration**.

---

## Operating Model

Canto development uses an Orchestrator / Worker pattern.

- **Cantor**: human authority; approves direction, risk, registration, releases, and destructive actions.
- **Orchestrator**: maintains architectural intent, defines work packets, reviews changes, and controls sequencing.
- **Worker**: implements bounded tasks exactly as scoped.

The worker must not redesign the architecture unless a work packet explicitly authorizes an architecture change.

---

## Architecture Lock

The following concepts are locked unless changed by an explicit architecture ticket:

- Skill
- Provider
- Tool
- Artifact
- Job
- Approval
- Registry
- Policy
- Dependency checking
- Bounded local execution
- Capability package
- Execution plan
- Orchestration contract

Workers may add capabilities and integrations inside this model. Workers may not rename, replace, or bypass this model.

---

## Canonical Identity Decision

Canto uses two identities for two different purposes:

- **`(skill, provider)`** is the canonical execution identity.
- **`capability@version`** is the packaging, provenance, checksum, risk, and distribution identity.

A capability may expose one or more executable `(skill, provider)` pairs. The package identity never replaces the runner identity.

---

# Completed Phases

## v1.1 — Capability Packaging

Goal: turn local skills/providers/tools into installable capability packages.

Delivered:

- Capability manifest format
- Manifest validation
- Capability package layout
- Validation command
- Package design documentation
- Fixtures and CLI/unit tests

Success condition met:

A local capability can be described, validated, and prepared for deterministic packaging.

---

## v1.2 — Local Capability Registry

Goal: install, list, inspect, validate, and remove packaged capabilities from a local registry.

Delivered:

- Local registry directory layout
- Registry API
- Registry index model
- Local list/search
- Inspect command
- Remove command
- Installed package validation
- Directory-first install design and implementation

Success condition met:

A capability can be installed locally, discovered in the local registry, inspected, validated, and removed safely.

---

## v1.3 — Import Capability

Goal: build the first showcase reusable capability for CMS/content import planning.

Delivered:

- Import capability skeleton
- Static HTML provider
- WordPress REST inventory provider
- ProcessWire exported-JSON provider
- SQL dump inventory and CMS detection
- Inventory artifact
- Content artifact
- Schema artifact
- Migration plan artifact
- Crosswalk mappings
- Artifact-only transformation rules

Non-goals preserved:

- No destructive import
- No production writes
- No credential storage
- No live database connections

Success condition met:

Canto can analyze content sources and produce migration-ready artifacts without writing to a target system.

---

## v1.3.5 — Capability Archives

Goal: complete the local package lifecycle before capability scaffolding.

Delivered:

- Deterministic `.canto` archive creation
- Archive validation
- Installation from `.canto` archives
- Export of installed capabilities
- Pack → install → list → inspect → execute → export lifecycle
- Installed checksum validation
- Collision rejection

Success condition met:

A capability directory can be packed, validated, installed, executed, and exported as a deterministic `.canto` archive.

---

## v1.4 — Capability Scaffolding Workflow

Goal: create deterministic local capability scaffolds that can be validated, packed, and installed.

Delivered:

- Scaffold design documentation
- `canto scaffold NAME`
- Manifest generation
- Skill/provider/test templates
- Scaffold → validate → pack → install flow

Non-goals preserved:

- No AI generation
- No remote registry
- No dependency installation
- No automatic trust

Success condition met:

Canto can create a valid placeholder capability package that fits the local capability lifecycle.

---

## v2.0 — Orchestrated Capability Discovery

Goal: discover installed local capabilities, propose reviewable workflows, and execute only approved plans.

Delivered:

- Capability intent/input/output metadata
- Deterministic local discovery
- Workflow candidate model
- Persisted plan model
- Draft and approved plans
- Approved-only sequential execution
- Exact artifact dependency resolution
- Plan explanation
- Full discover → plan → approve → execute → explain demo

Non-goals preserved:

- No remote registry
- No AI-generated capabilities
- No credential handling
- No target writes
- No dependency auto-installation

Success condition met:

Canto can discover installed capabilities for a goal, create a deterministic plan, approve it, execute it, and explain it.

---

## v2.1 — Registry Unification

Goal: unify discovery, planning, execution, approvals, and HTTP visibility around one executable registry view.

Delivered:

- Registry audit
- Canonical execution identity ADR
- HTTP/CLI registry parity
- Capability manifest provider bindings
- Provider binding validation
- Plan steps carrying runnable `(skill, provider)` identity
- Artifact-to-input binding model
- JobService-backed orchestration execution
- Single approval model unification
- Lazy registry reload semantics
- End-to-end unification test

Success condition met:

The same installed capability is visible to CLI registry, HTTP registry, discovery, planning, approval, JobService execution, explanation, and artifact production.

---

## v2.2 — Contract Freeze

Goal: freeze the v1.0 orchestration API contract for external callers.

Delivered:

- Contract freeze audit
- `contract_version` field on orchestration-facing responses
- OpenAPI export
- JSON Schemas
- HTTP orchestration endpoints:
  - `POST /discover`
  - `POST /plans`
  - `GET /plans/{plan_id}`
  - `GET /plans/{plan_id}/explain`
  - `POST /plans/{plan_id}/approve`
  - `POST /plans/{plan_id}/execute`
  - `GET /plans/{plan_id}/events`
- Polling semantics
- Auth placeholder documentation
- Contract compatibility statement
- HTTP contract integration coverage

Success condition met:

The external orchestration loop is frozen as:

```text
Discover → Plan → Approve → Execute → Observe
```

Canto owns execution. External orchestrators call Canto through the contract; they do not supply executors or bypass policy.

---

# Forward Roadmap

## v3.0 — External Orchestrator Integration

Goal: prove that an external orchestrator can use Canto through the frozen HTTP contract without in-process access.

Primary users:

- ChatGPT / Echo
- Claude
- Codex
- Hermes
- Local model agents
- Lightweight scripts

Deliverables:

- External client reference implementation
- CLI-backed smoke demo for the HTTP contract
- Orchestrator request/response examples
- Safe approval workflow for human-in-the-loop use
- Error-handling examples for missing inputs, missing capabilities, rejected approvals, failed steps, and missing artifacts
- Example workflow: `import my WordPress site and generate a migration report`
- External orchestrator README

Non-goals:

- No remote registry
- No AI-generated capability implementation
- No autonomous approval
- No credential storage
- No target writes
- No multi-user server deployment

Success condition:

An external process can discover capabilities, create a plan, approve it, execute it, poll until terminal state, retrieve explanations, and inspect artifacts using only the HTTP contract.

Recommended work packets:

- CP-1001 — External Orchestrator Integration Design
- CP-1002 — Python Client Library
- CP-1003 — Contract Smoke Test Script
- CP-1004 — External Orchestrator Example Prompts
- CP-1005 — Human Approval Demo
- CP-1006 — Error Scenario Examples
- CP-1007 — End-to-End External Demo
- CP-1008 — v3.0 Documentation Pass

---

## v3.1 — MCP / Tool Adapter Layer

Goal: expose Canto to model clients through a tool-friendly adapter without changing the core HTTP contract.

Deliverables:

- MCP adapter design
- Tool definitions for:
  - discover
  - plan
  - approve
  - execute
  - observe
  - explain
  - list artifacts
- Local-only MCP server or bridge
- Mapping from MCP calls to frozen HTTP endpoints
- Safety notes for approval and execution boundaries
- Adapter tests using mock capabilities

Non-goals:

- No changes to the frozen HTTP contract
- No remote tool marketplace
- No autonomous package install
- No model-specific hard dependency

Success condition:

A model client can call Canto as a local tool runtime while Canto continues to enforce approval, policy, registry, and execution boundaries.

---

## v3.2 — Orchestrator UX and Developer Experience

Goal: make Canto easy for humans and orchestrators to understand, debug, and demonstrate.

Deliverables:

- Improved `canto demo` command family
- Human-readable plan display
- Artifact summary views
- Plan timeline / event display
- Better missing-input prompts
- Better missing-capability suggestions
- Troubleshooting guide
- `examples/` directory with complete workflows

Non-goals:

- No new execution architecture
- No remote registry
- No autonomous decision-making

Success condition:

A developer can install Canto, install a capability, run a demo plan, understand what happened, and inspect the artifacts without reading source code.

---

## v4.0 — Remote Registry and Publishing

Goal: allow capabilities to be shared through a remote registry while preserving local trust boundaries.

Deliverables:

- Remote registry design
- Registry metadata schema
- `canto registry add/remove/list`
- `canto registry search`
- `canto publish` design
- Package download flow
- Trust and provenance metadata
- Checksum verification
- Registry cache
- Local install from downloaded archive

Non-goals:

- No autonomous install by default
- No marketplace payments
- No automatic dependency execution
- No unreviewed remote code execution

Success condition:

A user can search a configured remote registry, review package metadata, download a `.canto` archive, validate it, and install it locally with explicit approval.

---

## v4.1 — Package Trust, Signing, and Provenance

Goal: strengthen capability trust before any ecosystem grows.

Deliverables:

- Package signing design
- Signature verification
- Publisher identity metadata
- Provenance fields
- Trust policy document
- `canto verify` command
- Clear handling for unsigned, invalid, revoked, and unknown packages

Non-goals:

- No blockchain or heavyweight trust infrastructure unless explicitly justified
- No silent trust escalation
- No automatic install of unsigned packages

Success condition:

Canto can distinguish local, unsigned, signed, verified, and untrusted capabilities and enforce policy before install or execution.

---

## v5.0 — AI-Assisted Capability Authoring

Goal: let an orchestrator help create or modify capabilities while Canto enforces scaffold, validation, tests, packaging, approval, and install boundaries.

Deliverables:

- Authoring workflow design
- Missing-capability-to-scaffold workflow
- Orchestrator-generated implementation proposal format
- Test generation guidelines
- Review gates
- Pack/install only after validation and approval
- Audit trail for AI-assisted changes

Non-goals:

- No autonomous code trust
- No self-installing generated capabilities
- No bypass of tests or approval
- No production writes by generated capabilities unless separately approved

Success condition:

A missing capability can be scaffolded, implemented with AI assistance, tested, packed, reviewed, approved, and installed without bypassing Canto's safety model.

---

## v6.0 — Advanced Workflow Orchestration

Goal: support richer workflows after the linear, approved, artifact-based model has proven stable.

Potential deliverables:

- Branching plans
- Conditional steps
- Parallel-safe execution
- Retry policy
- Plan cancellation
- Resume from failed step
- Artifact versioning
- Plan templates

Non-goals:

- No uncontrolled autonomy
- No hidden execution
- No background mutation without explicit approval

Success condition:

Canto can express and execute richer workflows while maintaining explainability, artifact traceability, approval gates, and bounded execution.

---

## Deferred Until Explicitly Approved

The following remain intentionally deferred:

- Remote registry trust automation
- Autonomous package installation
- Full multi-user authentication and authorization
- Hosted public Canto service
- Credential vaulting
- Target-system writes
- Dependency auto-installation
- Non-Python runners
- Parallel execution
- Marketplace/payment features

---

## Release Status Summary

Current completed milestone:

```text
v2.2 — Orchestration Contract Freeze
```

Next recommended milestone:

```text
v3.0 — External Orchestrator Integration
```

Strategic direction:

```text
Canto is not the AI.
Canto is the governed capability runtime that AIs and humans can call.
```
