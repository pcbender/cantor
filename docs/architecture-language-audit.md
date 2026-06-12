# CP-1402 — Public Terminology Audit

Status: complete

## Purpose

Inventory current user-visible language against the approved Architecture
Language Lexicon. This audit identifies migration work only. It does not rename
commands, models, schemas, persisted values, or runtime behavior.

## Method

The audit reviewed:

- `README.md`, `STATUS.md`, and `ROADMAP.md`;
- active guides, quickstarts, release notes, architecture records, API and
  package documentation under `docs/`;
- shell demos and examples;
- CLI command help and human-readable output in `canto/cli.py`;
- generated repository and agent instructions in `canto/core/repository.py`;
- the current bootstrapped `AGENTS.md` and `.canto/agents/` files;
- checked-in schemas and frozen contract artifacts.

Occurrences were classified as Public, Advanced, Internal, or Historical using
CP-1401. Search counts were used to locate concentrations, not as a mechanical
replacement list.

## Summary

The architecture already has stable internal identities. The mismatch is
primarily presentation:

1. The README opens with internal implementation terms rather than the public
   product model.
2. Active delegation guidance consistently says Orchestrator, Executor,
   Artifact, and Promotion where Developer, Worker, Result, and qualified
   Apply should lead.
3. Generated agent manuals expose internal role names as their primary titles
   and instructions.
4. CLI command names are compatible and should remain unchanged, but help and
   human-readable dashboard labels lead with internal terms.
5. API, schema, package-authoring, and diagnostic documents correctly require
   exact internal names. They need public framing where appropriate, not field
   renames.
6. Completed design records and release notes are historical evidence and
   should not be mechanically rewritten.

## Surface Findings

| Surface | Class | Current language | Preferred treatment | Owner |
| --- | --- | --- | --- | --- |
| README opening and product summary | Public | execution broker, skills, providers, jobs, artifacts, registry, policy | Lead with Developer, Worker, Toolbox, Operation, Run, Result, Catalog, and Guardrails; retain one advanced architecture paragraph | CP-1403 |
| README quickstart and examples | Public with Advanced commands | capability, registry, delegated executor, promotion | Explain Toolbox and Worker concepts around unchanged commands and identifiers | CP-1403 |
| README API summary and contract freeze | Advanced | skills, providers, jobs, discover, execute, observe | Preserve exact endpoint and contract language; add the public-loop mapping once | CP-1403 |
| README security boundaries | Public/Advanced | provider, policy, artifacts, executor, promotion | Lead with Worker, Guardrails, Result, and qualified Apply; retain exact implementation terms where needed | CP-1403 |
| `docs/delegated-executors.md` | Public operational guide | orchestrator, executor, artifact, promotion | Migrate prose to Developer, Worker, Result, and qualified Apply while preserving command names and model identifiers | CP-1405 |
| `docs/local-installation.md` delegation sections | Public operational guide | executor profile, delegated executor, artifacts, promotion | Introduce Worker profile and Apply language; retain literal commands, filenames, and recorded fields | CP-1405 |
| Generated `AGENTS.md` pointer | Public agent instruction | orchestrator, executor, artifact, promotion | Point to Developer and Worker manuals; explain internal filenames during compatibility period | CP-1405 |
| Generated `.canto/agents/*.md` manuals | Public agent instruction | Orchestrator and Executor as primary roles | Generate Developer and Worker-facing titles and authority rules; preserve existing paths initially | CP-1405 |
| `.canto/delegate.toml` keys and filenames | Internal/config compatibility | `orchestrator_instructions`, `executor_instructions` | Preserve keys and paths; public docs may call them Developer and Worker manuals | CP-1405/CP-1406 |
| Delegation CLI help | Public presentation over internal commands | executor, artifact, promotion | Keep command names; update help and summaries only after CP-1404 design approval | CP-1404 then implementation packet |
| Delegation dashboard text | Public presentation | TASK, EXECUTOR, Artifacts, Promotion ready | Design labels for assignment/work item, Worker, Results, and Apply readiness without changing JSON fields | CP-1404 |
| Core CLI `run`, `job`, and artifact commands | Public/Advanced | Job and Artifact are exposed established commands | Specify additive presentation and aliases; do not rename commands in this sprint | CP-1404 |
| `discover`, plan execution, and observation surfaces | Frozen contract | Discover, Execute, Observe | Preserve exactly; public prose may show Find, Run, Status/Timeline/Events mapping | CP-1403/CP-1406 |
| Capability validation, package, install, scaffold docs | Advanced/package authoring | Capability, manifest skills/providers/tools | Preserve exact package and field names; lead with Toolbox only in introductory prose | CP-1403 |
| OpenAPI and JSON Schemas | Frozen contract | capability, skill, provider, job, artifact fields | No terminology edits unless generated from a separately versioned contract change | CP-1406 |
| Runtime/provider/policy/vault docs | Advanced | Provider, Policy, Job, Artifact | Preserve precise terms; optionally add one public-language orientation paragraph | CP-1403 |
| `STATUS.md` completed milestones | Historical/status | original packet and implementation terms | Keep exact milestone names; use frozen language for current product summary and future status | CP-1403/CP-1407 |
| `ROADMAP.md` completed packets | Historical | original names | Preserve packet titles; apply frozen vocabulary to new public goals and deliverables | CP-1407 |
| `docs/Canto Delegated Executor Workspaces.md` | Historical/superseded | Cantor, Orchestrator, Executor, Promotion | Retain as historical source; add or preserve superseded classification rather than rewrite | No migration |
| Approved architecture and ADR documents | Internal/Historical | canonical internal concepts | Preserve precision; add links to the lexicon only where readers could mistake them for public naming guidance | CP-1403 |
| Shell demos and examples | Public commands plus fixtures | capability, provider, job, promotion | Preserve literal commands and fixture fields; update comments and narration where useful | CP-1403 |

## Term Decisions by Surface

### Developer

Public supervising guidance should use Developer. `Cantor` remains only in
historical material or a compatibility-reviewed role model. `Orchestrator`
remains valid for an external orchestration client and internal service
architecture, but should not be the default name for the supervising person in
delegation guides.

Current concentrations:

- historical delegated-executor design records;
- active generated orchestrator manual;
- active delegated-executor guide and installation smoke test;
- future MVP v2 role language in the roadmap.

The MVP v2 role model requires a separate compatibility decision. CP-1403 must
not silently rename a future persisted or authorization role.

### Worker

Public delegation surfaces should use Worker. Internal names including
`ExecutorProfile`, `executor_id`, `executor_working`, filenames, configuration
keys, event values, and Python classes remain unchanged.

Highest-priority public migrations:

- generated role manuals and launch prompts;
- delegation guide and installation smoke tests;
- CLI help and human-readable dashboard labels;
- README delegation and security sections.

### Toolbox and Operation

Toolbox and Operation should lead in product explanation and normal discovery
guidance. Capability, Skill, and Provider remain necessary in:

- manifest and package authoring;
- canonical `(skill, provider)` execution identity;
- `capability@version` provenance identity;
- existing command arguments and endpoint paths;
- errors and diagnostics naming exact identifiers.

No manifest key, package path, CLI argument, endpoint, schema, or internal
identifier should be changed by the language migration.

### Run and Result

Run and Result should lead in normal workflow narration. Job and Artifact remain
exact internal records and existing CLI/API identifiers.

The CLI currently exposes `job` and `artifacts` commands and prints JSON with
internal field names. CP-1404 must decide whether friendly aliases or only help
text are warranted. JSON output must remain stable.

### Catalog and Guardrails

Catalog is the public installed-inventory view. Registry remains correct for
package sources, internal stores, APIs, and advanced diagnostics. Marketplace
is not approved.

Guardrails describes enforced user-visible boundaries. Policy remains correct
for configuration files, schema fields, services, and diagnostics.

### Find, Review, and Apply

- Find is the public discovery action; Discover remains the frozen contract
  action and current command terminology.
- Review means human judgment. Passive views must say Status, Timeline, or
  Events.
- Apply must never appear without the exact Result and target. Existing
  `promote` commands remain compatible until additive alias design is approved.

## CLI Design Inputs

CP-1404 must address these concrete surfaces:

1. Whether `canto find` should be an additive alias for installed-capability
   discovery without conflicting with local Registry search.
2. Whether `job` commands retain advanced status while normal prose calls the
   record a Run.
3. Whether delegation commands remain under `delegate` while help text says
   Worker and Result.
4. How dashboard columns map `EXECUTOR` to Worker and `ARTIFACTS` to Results
   without changing `--json` output.
5. How `promote`, `queue-promote`, and write promotion are presented as
   qualified Apply actions without obscuring their different safety gates.
6. How errors show a public term followed by an exact internal identifier, for
   example `Run job_123 failed`.

No alias or presentation change is approved by this audit.

## Exceptions

The following uses are expected and should not be treated as migration debt:

- frozen HTTP endpoints, request/response fields, statuses, OpenAPI, and JSON
  Schemas;
- manifest fields and package layouts;
- Python classes, service names, event types, persisted records, and exact
  identifiers;
- CLI command names and JSON keys until separately approved;
- advanced package, runtime, Policy, Registry, and diagnostic documentation;
- completed packet titles, historical release notes, superseded designs, and
  ADRs where original terminology records the implemented architecture.

## Risks

- Mechanical replacement would corrupt command examples, schemas, and frozen
  contract language.
- Replacing Executor in prose while leaving unexplained `executor_id` output
  could make diagnostics less clear. Public-to-internal mapping must remain
  visible.
- Bare Apply language could collapse patch promotion, governed live writes,
  and recovery into one unsafe-looking action.
- Renaming Cantor in future authorization language without a role-model decision
  could create a contract mismatch.
- Calling the local Catalog a marketplace would imply remote acquisition and
  trust behavior that Canto does not implement.

## CP-1402 Acceptance

- Public surface categories are inventoried and classified.
- Each migration finding names its preferred treatment and owning packet.
- Frozen identifiers, advanced terms, and historical records are explicit
  exceptions.
- CLI alias questions are routed to CP-1404 rather than implemented.
- Agent/delegation language is routed to CP-1405.
- No runtime, schema, command, or contract behavior changed.
