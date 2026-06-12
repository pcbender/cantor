# Architecture Language Sprint

Status: complete; CP-1401 through CP-1407 complete

## Goal

Freeze a small, intuitive public vocabulary for Canto without renaming its
internal architecture or breaking established interfaces.

The approved vocabulary and authority model are defined in
`docs/architecture-language-lexicon.md`:

> Canto assigns an approved Toolbox and bounded Operation to a Worker. The
> Worker performs the work under Guardrails, Canto records the Result, and the
> Developer decides whether that exact Result may be Applied.

## Boundaries

- Public language may change in documentation, prompts, help text, and future
  presentation aliases.
- Internal concepts remain `Capability`, `Skill`, `Provider`, `Tool`, `Plan`,
  `Job`, `Registry`, `Policy`, and `Approval`.
- Canonical execution identity remains `(skill, provider)`.
- Package and provenance identity remains `capability@version`.
- Existing manifests, persisted records, Python APIs, CLI commands, HTTP
  fields, endpoint paths, status values, and `contract_version: 1.0` remain
  compatible.
- Public aliases must be additive before any separate deprecation decision.
- This sprint does not implement remote Registry behavior, a marketplace, AI
  generation, or a universal Task model.

## Sequence

CP-1401 is the approved vocabulary design packet. The migration sequence
begins with CP-1402.

### CP-1401 — Public Architecture Lexicon

Freeze public roles, objects, actions, authority boundaries, internal
mappings, discouraged terms, and compatibility constraints.

Acceptance:

- `Developer`, `Worker`, `Toolbox`, `Operation`, `Run`, `Result`, `Guardrails`,
  `Catalog`, and qualified `Apply` are defined.
- `Find -> Plan -> Approve -> Run -> Review` is the preferred public loop.
- The frozen API loop remains `Discover -> Plan -> Approve -> Execute ->
  Observe`.
- Internal and public terms have explicit mappings.
- The Developer authorizes Apply; Canto verifies and performs it; a Worker
  cannot self-approve or self-apply.

Status: approved.

### CP-1402 — Public Terminology Audit

Inventory user-visible terminology across README, current documentation, CLI
help, routine messages, generated agent instructions, demos, examples, and
status output. Classify each occurrence as Public, Advanced, Internal, or
Historical using CP-1401.

Deliverable: `docs/architecture-language-audit.md`.

Acceptance:

- Every current user-facing surface category is covered.
- Findings identify the existing term, preferred term, surface, risk, and
  recommended packet.
- Frozen identifiers and historical records are distinguished from prose that
  should change.
- The audit changes no runtime behavior.

Status: complete. See `docs/architecture-language-audit.md`.

### CP-1403 — Public Documentation Migration

Update current public documentation to lead with the frozen vocabulary while
retaining precise internal terms where package authoring, API compatibility,
or diagnostics require them.

Acceptance:

- README, quickstarts, installation guidance, current roadmap/status language,
  and active user guides use the public vocabulary consistently.
- Package-authoring and API documents preserve exact field and command names.
- Historical design records are not mechanically rewritten.
- Links, documented commands, and documentation checks remain valid.

Status: complete for general product and advanced guidance. Delegation role
manuals and the active delegated-work guide remain explicitly owned by
CP-1405.

### CP-1404 — CLI, Help, and Message Language Design

Specify additive public aliases and presentation changes before implementation.
Define which existing commands remain primary compatibility surfaces and where
friendly terms such as `find`, `run`, `result`, and qualified `apply` should
appear.

Deliverable: `docs/architecture-language-cli-design.md`.

Acceptance:

- Existing command names and exit behavior remain supported.
- Every proposed alias maps to one existing action without semantic drift.
- Passive observation uses Status, Timeline, or Events rather than Review.
- No interface presents a bare Apply action; labels name the exact Result and
  target.
- Implementation and deprecation work are explicitly deferred to separately
  approved packets.

Status: complete. See `docs/architecture-language-cli-design.md`. The design
approves a future additive `find` alias and explicitly defers implementation.

### CP-1405 — Agent and Delegation Language Migration

Update active agent manuals, launch prompts, demos, and delegated-work guidance
to present Developer and Worker roles while preserving internal
`DelegationTask`, `ExecutorProfile`, event, command, and schema identifiers.

Acceptance:

- Generated shared, Developer, and Worker instructions state distinct
  authorities.
- Worker instructions prohibit self-assignment, scope expansion,
  self-approval, and self-application.
- Developer instructions require review of the exact Result before Apply.
- Existing persisted delegation models and commands remain compatible.
- A disposable bootstrapped repository demonstrates the generated language.

Status: complete. Generated manuals and launch prompts use Developer and Worker
authority language while retaining compatibility filenames, model names,
statuses, commands, and JSON fields.

### CP-1406 — Compatibility and Contract Audit

Verify that the language migration did not rename or reinterpret frozen or
persisted interfaces.

Deliverable: `docs/architecture-language-compatibility-audit.md`.

Acceptance:

- Manifest and package fields are unchanged.
- CLI commands remain valid unless an additive alias was separately approved.
- HTTP endpoints, wire fields, status values, schemas, OpenAPI, and
  `contract_version: 1.0` are unchanged.
- Internal execution and provenance identities remain unchanged.
- Full tests and documentation command checks pass.

Status: complete. See `docs/architecture-language-compatibility-audit.md`.

### CP-1407 — Language Freeze and Adoption Record

Record the final vocabulary, exceptions, verification results, and rules for
future public surfaces.

Acceptance:

- README, ROADMAP, and STATUS identify the frozen public vocabulary.
- Remaining uses of discouraged public terms are documented exceptions,
  advanced/internal identifiers, or historical records.
- New public terminology requires an Architecture Language decision record and
  compatibility review.
- Verification results and known deferred alias work are recorded.

Status: complete. See `docs/architecture-language-freeze.md`.

## Implementation Gate

The design gate is satisfied. CP-1404 approves only the future additive `find`
alias; its implementation remains a separate packet. No generic Apply alias is
approved.
