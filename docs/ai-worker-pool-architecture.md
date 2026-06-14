# CP-1501 — Governed AI Worker Pool Architecture

Status: approved

## Purpose

Canto needs a durable, governed pool of local and cloud AI Workers so a
Developer does not have to load models one at a time or manually discover
whether they can perform implementation work. Canto must discover available
models, validate their actual Worker behavior, rank eligible candidates, and
select the least-cost candidate that satisfies task policy.

This is a single-user local architecture. It must migrate to MVP v2 without
changing the central identities or authority model:

- the Developer authorizes policy and cloud use;
- Canto selects, launches, observes, and records the Worker;
- the Worker performs only bounded assigned work;
- Canto captures the Result;
- the Developer reviews and authorizes Apply.

The existing delegation lifecycle, Workspace, Result, review, promotion, vault,
and `StateStore` remain canonical. This workstream does not create a second
delegation or execution lifecycle.

## Design Decisions

1. Endpoint configuration is global. Repository bootstrap may guide a
   Developer to select configured endpoints, but it never receives or stores
   API keys.
2. API keys live only in the existing Canto vault. Endpoint records store a
   `vault:` reference.
3. Initial cloud adapters are OpenAI, Anthropic, Google, and a generic
   OpenAI-compatible endpoint. Ollama is the initial local adapter.
4. API keys are the only cloud authentication mechanism in this workstream.
   External CLI sessions, browser login, OAuth, and inherited cloud sessions
   are deferred from the governed pool. Existing CLI-authenticated profiles
   remain manual compatibility adapters and may be selected explicitly by the
   Developer as a last resort, but they are excluded from automatic selection,
   ranking, budget-based fallback, and endpoint/model discovery.
5. Canto automatically selects a Worker from eligible candidates. Selection is
   deterministic for the same catalog snapshot, probe evidence, task, and
   policy.
6. A model is eligible for implementation work only after passing a versioned
   coding-Worker probe. A successful text response is not sufficient.
7. Local-to-cloud fallback is never implicit. Cloud candidates are eligible
   only when global and repository/task policy explicitly authorize cloud use.
8. Budget enforcement can be globally enabled or disabled. When enabled,
   global, repository, and task limits compose by taking the most restrictive
   value.
9. Canto persists the exact provider model identifier and discovery metadata.
   Alias changes invalidate validation until the resolved model is re-probed.
10. Automatic cross-provider selection requires Canto to own a provider-neutral
    API Worker harness. Provider CLIs remain compatibility adapters. MVP v2
    moves the same harness behind authenticated server execution rather than
    introducing another execution path.

## Terms

### AI Endpoint

A configured local or cloud service that exposes models. Identity is
`endpoint_id`. Examples are an OpenAI account, an Anthropic account, a Google
Gemini project, an internal OpenAI-compatible gateway, or local Ollama.

### Model Record

A discovered model at one endpoint. Canonical identity is:

```text
(endpoint_id, provider_model_id, resolved_version)
```

The user-facing display name and aliases are metadata, not identity.

### Worker Classification

- `implementation`: passed the coding probe and may edit a delegated
  Workspace.
- `advisory`: may produce analysis or proposed text but is not eligible for
  implementation assignments.
- `unavailable`: endpoint, authentication, model, or quota validation failed.
- `unvalidated`: discovered but not probed for the current probe version.

### Priority Level

Developer-selected ranking posture:

- `economy`: prioritize expected dollar cost and local execution.
- `balanced`: balance cost, capability, latency, and validated reliability.
- `quality`: prioritize capability and historical task success within budget.
- `urgent`: prioritize availability and latency within budget.

Priority levels select configurable weights. They do not hard-code provider or
model preferences.

### Selection Decision

An immutable record of candidates considered, candidates rejected, policy and
budget checks, score components, selected Worker, catalog/probe versions, and
the reason for selection.

## Storage And Ownership

Global durable state remains under `~/.canto`:

```text
~/.canto/state.sqlite
~/.canto/vault/
~/.canto/config/ai-endpoints.yaml
~/.canto/work/probes/
~/.canto/work/delegations/
```

`ai-endpoints.yaml` contains non-secret connection intent only. Endpoint,
model, probe, price, selection, and usage records are persisted through
`StateStore`. Large probe evidence remains under `~/.canto/work/probes/` and is
checksum-bound from its state record.

Repository configuration remains non-secret:

```toml
# .canto/delegate.toml
[worker_selection]
priority = "balanced"
allowed_endpoints = ["local-ollama", "openai-primary"]
allowed_providers = ["ollama", "openai"]
cloud_allowed = true
local_first = true

[worker_selection.budget]
enabled = true
max_estimated_usd = 2.00
max_input_tokens = 200000
max_output_tokens = 40000
```

Repository config stores endpoint IDs and constraints only. It never stores a
key, plaintext credential, provider session, or copied vault value.

## Endpoint Model

Conservative endpoint configuration:

```yaml
version: 1
endpoints:
  - endpoint_id: openai-primary
    provider: openai
    base_url: https://api.openai.com
    credential_ref: vault:ai/openai-primary
    enabled: true
  - endpoint_id: anthropic-primary
    provider: anthropic
    base_url: https://api.anthropic.com
    credential_ref: vault:ai/anthropic-primary
    enabled: true
  - endpoint_id: google-primary
    provider: google
    base_url: https://generativelanguage.googleapis.com
    credential_ref: vault:ai/google-primary
    enabled: true
  - endpoint_id: internal-gateway
    provider: openai_compatible
    base_url: https://models.example.internal/v1
    credential_ref: vault:ai/internal-gateway
    enabled: true
  - endpoint_id: local-ollama
    provider: ollama
    base_url: http://127.0.0.1:11434
    enabled: true
```

Rules:

- `endpoint_id` is stable and unique.
- Cloud endpoint URLs require HTTPS. Loopback local endpoints may use HTTP.
- Redirects to another origin are rejected during discovery and execution.
- Generic OpenAI-compatible behavior is explicitly capability-negotiated; Canto
  does not assume every nominally compatible endpoint supports every API or
  tool behavior.
- Vault references are resolved only for the duration of a connection or Run
  and are redacted from logs, errors, prompts, artifacts, and state.

## Discovery And Versioning

`canto ai endpoint validate ENDPOINT_ID` verifies endpoint configuration,
authentication, TLS/origin policy, and the provider's model-list operation.

`canto ai models refresh [ENDPOINT_ID]` performs explicit network discovery and
stores a catalog snapshot containing:

- endpoint and provider;
- provider model ID;
- display name and aliases where supplied;
- provider-reported creation/version metadata where supplied;
- supported API surfaces and tool declarations that can be discovered;
- context/output limits when provider-reported;
- discovery timestamp and response checksum;
- pricing source/version and whether cost is known;
- validation and probe status.

Provider APIs expose different metadata. Missing values remain unknown; Canto
does not guess them. Unknown context limits, pricing, or tool support may make a
candidate ineligible under policy.

Aliases are resolved during refresh. If an alias resolves to a different model
identifier or provider version, Canto marks the prior probe stale. Existing
Results retain their original model provenance.

Network discovery is explicit global configuration work. `canto repo init`
never discovers models and remains network-free.

## Coding-Worker Probe

The probe is versioned independently from Canto. `probe_version` is stored with
every result. A model change, endpoint change, harness change, or probe-version
change requires revalidation.

The implementation probe runs in a disposable Git repository and requires the
model to:

1. inspect bounded repository instructions;
2. use the approved file and command tools rather than print tool-call JSON;
3. modify one allowed file correctly;
4. leave a denied file unchanged;
5. run one allowed validation command;
6. produce a structured completion summary;
7. remain within token, cost, time, and output limits;
8. leave a patch Canto can capture and checksum.

Probe outcomes record each assertion separately. A model that responds usefully
but cannot execute tools is classified `advisory`, not failed globally.

Probes never use a real repository, real credentials beyond the endpoint key,
or external target systems. Automated tests use fake adapters and fixtures; no
CI test requires paid API access, Ollama, or a downloaded model.

## Provider-Neutral Worker Harness

The API Worker harness owns the bounded agent loop for all direct API adapters:

- construct the role and assignment prompt;
- expose only Canto-approved repository and command tools;
- validate tool arguments before execution;
- execute tools within the delegated Workspace and existing Guardrails;
- bound turns, tokens, wall time, output, and estimated cost;
- record provider requests without secrets or unrestricted prompt bodies;
- collect usage and provider request IDs;
- stop on policy, budget, tool, endpoint, or model errors;
- produce the existing session, launch, command, Result, review, and promotion
  evidence.

Provider adapters translate between this internal tool/event contract and each
provider's API. They do not implement separate lifecycle or promotion logic.

Initial adapters:

- OpenAI API-key adapter;
- Anthropic API-key adapter;
- Google Gemini API-key adapter;
- generic OpenAI-compatible API-key adapter;
- local Ollama adapter.

The generic adapter must pass endpoint conformance and coding probes. Provider
differences are explicit adapter capabilities, not conditionals spread through
delegation services.

## Selection Eligibility

A candidate is eligible only when all are true:

- endpoint and model are enabled;
- endpoint validation is current;
- model resolution has not changed since its probe;
- required Worker classification is satisfied;
- provider/endpoint/model are allowed by global, repo, and task policy;
- cloud/local policy permits its location;
- required context, output, tool, and file-edit capabilities are known;
- estimated tokens, cost, and wall time fit enabled budgets;
- no active cooldown, quota, or health failure blocks the endpoint;
- the task's risk and data constraints permit sending its bounded context to
  that endpoint.

Cloud eligibility is authorization decided before selection. It is not a
post-selection approval prompt and never silently widens a local-only task.

## Ranking

Ranking is deterministic and explainable. Each eligible candidate receives
normalized components:

- `capability`: probe assertions and task-class compatibility;
- `reliability`: version-scoped observed success for comparable tasks;
- `estimated_cost`: prompt plus predicted output cost;
- `latency`: validated endpoint/model latency estimate;
- `locality`: local/no-marginal-cost preference;
- `size_fit`: preference for the smallest validated model with adequate
  context and capability;
- `availability`: health, quota, cooldown, and concurrency state.

Example score shape:

```text
score =
  capability_weight * capability
  + reliability_weight * reliability
  + latency_weight * latency_score
  + locality_weight * locality
  + size_fit_weight * size_fit
  - cost_weight * estimated_cost_score
```

Hard constraints are evaluated before scoring. A high score cannot bypass a
budget, cloud restriction, failed probe, stale version, or missing capability.
Ties use stable ordering by `endpoint_id`, model ID, and resolved version.

Historical experience may adjust version-scoped reliability and observed cost
or latency. It may not silently alter policy, authorize cloud use, or make an
unprobed model implementation-eligible.

## Budget Policy

Budget policy has a top-level `enabled` switch. When disabled, Canto still
records usage and estimates but does not reject solely on configured spend or
token limits. Security, cloud authorization, tool, context, and runtime limits
remain enforced.

Supported constraints:

- maximum estimated and actual USD per task;
- maximum input, cached-input, and output tokens;
- maximum turns and tool calls;
- maximum wall time;
- allowed providers, endpoints, and models;
- local-only;
- local-first;
- cloud allowed;
- cloud fallback allowed;
- optional endpoint/model concurrency limits.

If pricing is unknown and an enabled dollar budget applies, the model is
ineligible unless policy explicitly permits unknown pricing with a separate
hard token limit.

Actual usage crossing a hard budget stops further model turns safely. Existing
Workspace changes remain untrusted evidence and do not become an accepted
Result automatically.

## Selection And Fallback Flow

1. Developer defines global endpoint records and vault-backed credentials.
2. Canto validates endpoints, discovers models, and runs approved probes.
3. Repository bootstrap references allowed endpoint IDs and selection policy.
4. Developer creates a bounded delegation task with a priority and optional
   stricter task budget.
5. Canto filters and ranks the current eligible pool.
6. Canto persists a Selection Decision and assigns the top candidate.
7. The API Worker harness performs the task under existing delegation controls.
8. If execution fails before producing a Result, Canto may select the next
   eligible candidate only when task policy permits fallback.
9. Local-to-cloud fallback occurs only when `cloud_allowed` and
   `cloud_fallback_allowed` were already true. The event and reason are
   persisted and shown to the Developer.
10. Capture, Review, acceptance, and Apply remain unchanged.

Fallback never means accepting partial work from one Worker and silently
continuing it with another. Each attempt has separate session, selection,
launch, usage, and evidence records. The task Workspace and revision history
remain explicit.

## Cost And Usage Records

Every attempt records:

- endpoint, provider, exact model ID, resolved version, and adapter version;
- selection decision ID and priority level;
- input, cached-input, output, and reasoning tokens when reported;
- provider request IDs where safe;
- estimated and actual cost with currency and pricing-table version;
- start/end time, first-token latency where available, and total latency;
- turns, tool calls, retries, and terminal reason;
- budget remaining and any limit that stopped execution.

Provider-reported usage is preferred. Derived estimates are marked as
estimates. Canto never invents a precise actual cost when provider data or
pricing is unavailable.

## Security And Privacy

- API keys are accepted through credential commands or secure prompt input,
  never command-line arguments that appear in process listings or shell
  history.
- Keys are stored only in the encrypted vault and injected only into the
  adapter request boundary.
- Endpoint configuration, repo config, task records, prompts, logs, and
  artifacts contain vault references or redacted values only.
- Repository context sent to a cloud model is limited to declared task scope
  and the files/tool results requested through the bounded harness.
- A repo policy can deny cloud use for all tasks or restrict particular paths
  and data classes from cloud context.
- Model output and tool requests remain untrusted until Canto validates and
  executes them.
- No endpoint may grant itself tools, network scope, credentials, approval, or
  Apply authority.

## CLI Shape

Proposed commands:

```text
canto ai endpoint add
canto ai endpoint list
canto ai endpoint show ENDPOINT_ID
canto ai endpoint validate ENDPOINT_ID
canto ai endpoint disable ENDPOINT_ID
canto ai models refresh [ENDPOINT_ID]
canto ai models list
canto ai model probe ENDPOINT_ID MODEL_ID
canto ai model show ENDPOINT_ID MODEL_ID
canto ai pool explain --repo . [--priority balanced]
canto delegate create ... --priority balanced --max-cost 2.00
canto delegate select TASK_ID
canto delegate launch TASK_ID
```

`endpoint add` may securely prompt for an API key and store it in the vault. It
prints and persists only the resulting vault reference. Model refresh, endpoint
validation, and real probes are explicit network operations.

`pool explain` is read-only and shows eligibility, rejection reasons, score
components, estimated budget impact, and the candidate Canto would select.

## State Model Additions

Additive records behind `StateStore`:

- `AIEndpointRecord`
- `AIModelRecord`
- `ModelCatalogSnapshot`
- `WorkerProbeResult`
- `WorkerSelectionPolicy`
- `WorkerSelectionDecision`
- `WorkerUsageRecord`
- `EndpointHealthRecord`

Existing `ExecutorProfile` remains readable. Migration maps manual and
Codex-CLI profiles to compatibility candidates but does not treat them as
API-key endpoint records. Compatibility candidates are never considered by the
automatic pool selector. A Developer may explicitly assign one as a last-resort
Worker under the existing delegation controls. Existing tasks keep their
recorded executor IDs and provenance.

## MVP v2 Migration

The single-user implementation uses SQLite, the local vault, and local
delegation Workspaces. MVP v2 changes ownership boundaries, not identities:

- endpoint/model/probe/selection/usage records move to the server-tier
  `StateStore`;
- vault references become per-user or granted secrets;
- endpoint administration and cloud authorization require authenticated roles;
- the same provider-neutral harness runs in server-controlled job isolation;
- concurrency, quotas, rate limits, and audit become per-user/team;
- API and MCP surfaces expose selection and evidence without accepting keys in
  ordinary orchestration payloads.

No repository migration should be required beyond compatibility-reviewed
policy additions.

## Non-Goals

- OAuth, browser login, inherited CLI sessions, or external provider CLI auth.
- Automatic selection or fallback to CLI-authenticated compatibility Workers.
- Automatic key creation, purchasing, billing administration, or credit
  replenishment.
- Silent cloud fallback or policy widening.
- Unprobed implementation Workers.
- Model training, fine-tuning, prompt self-modification, or autonomous policy
  tuning.
- Remote Worker machines, multi-user endpoint sharing, or public endpoints in
  the single-user implementation.
- Replacing delegation Results, reviews, promotion, Approval, JobService, or the
  frozen orchestration HTTP contract.

## Implementation Sequence

CP-1501 is this approved architecture packet and is complete.

1. CP-1502 — Endpoint, Model, Probe, Selection, and Usage Models
2. CP-1503 — Vault-Backed Endpoint Configuration
3. CP-1504 — Provider Discovery Adapters
4. CP-1505 — Versioned Coding-Worker Probe Harness
5. CP-1506 — Worker Classification and Compatibility Evidence
6. CP-1507 — Priority, Budget, and Eligibility Policy
7. CP-1508 — Deterministic Worker Ranking and Explain Output
8. CP-1509 — Provider-Neutral API Worker Harness
9. CP-1510 — Automatic Assignment and Explicit Fallback
10. CP-1511 — Usage, Cost, Health, and Reliability Records
11. CP-1512 — Repo Bootstrap Integration and Migration
12. CP-1513 — End-to-End Single-User Worker Pool Demo
13. CP-1514 — Security, Stability, and Documentation Pass

Provider adapters may be implemented incrementally, but no adapter is declared
complete until discovery, probe, execution, redaction, usage, budget, and
failure-path tests pass.

## Acceptance

- A Developer configures cloud endpoints without placing keys in a repository.
- Canto discovers local and cloud model versions and detects alias changes.
- Models that print tool-call text instead of using tools are classified
  advisory and excluded from implementation selection.
- Canto deterministically selects the least-cost eligible Worker according to
  priority and policy.
- Local-only tasks never contact cloud endpoints.
- Cloud selection and fallback occur only under prior explicit policy.
- Budget enforcement can be disabled globally or constrained by task.
- Selection, probe, usage, cost, fallback, and exact model provenance survive
  restart.
- API-backed Workers use the existing Workspace, Result, Review, and Apply
  lifecycle.
- Automated tests require no network, paid provider account, Ollama runtime, or
  downloaded model.
- Existing profiles, tasks, manifests, delegation records, and orchestration
  contract remain compatible.

## Reference API Surfaces

The implementation must verify provider behavior against current official
documentation during each adapter packet:

- OpenAI model listing: <https://platform.openai.com/docs/api-reference/models/list>
- Anthropic model listing: <https://docs.anthropic.com/en/api/models-list>
- Google Gemini model listing: <https://ai.google.dev/api/models>

Generic OpenAI-compatible endpoints are validated by observed conformance, not
by brand or URL shape.
