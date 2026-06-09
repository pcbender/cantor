# Canto Roadmap

Canto v1 is complete. The next phase is not to prove that Canto can run a local skill; that has already been proven. The next phase is to prove that Canto capabilities can be packaged, validated, installed, reused, and eventually shared.

## Operating Model

Canto development uses an Orchestrator / Worker pattern.

- **Cantor**: human authority; approves direction, risk, registration, releases, and destructive actions.
- **Orchestrator**: maintains architectural intent, defines work packets, reviews changes, and controls sequencing.
- **Worker**: implements bounded tasks exactly as scoped.

The worker must not redesign the architecture unless a work packet explicitly authorizes an architecture change.

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

Workers may add capabilities inside this model. Workers may not rename, replace, or bypass this model.

## v1.1 — Capability Packaging

Goal: turn local skills/providers/tools into installable capability packages.

Deliverables:

- Capability manifest format
- Manifest validation
- Capability package layout
- Pack command
- Package checksum support
- Package metadata report
- Unit tests and CLI tests

Non-goals:

- No remote registry
- No marketplace
- No dependency auto-install unless separately approved
- No redesign of the current registry
- No autonomous package trust

Success condition:

A built-in capability can be packed into a deterministic local package and validated before install.

## v1.2 — Local Capability Registry

Goal: install, list, inspect, and remove packaged capabilities from a local registry.

Deliverables:

- Local registry directory layout
- Install command
- List command
- Inspect command
- Remove command
- Registry index
- Installed package validation

Non-goals:

- No public publishing
- No remote search
- No network dependency

Success condition:

A packed capability can be installed locally, inspected, and removed without corrupting the existing v1 registry.

## v1.3 — Import Capability

Goal: build the first showcase reusable capability package for CMS/content import planning.

Deliverables:

- `import_site` skill
- Static HTML provider
- WordPress REST provider
- Optional ProcessWire provider later
- Inventory artifact
- Normalized content artifact
- Migration plan artifact
- Dry-run report

Non-goals:

- No destructive import
- No production writes
- No credential storage

Success condition:

Canto can analyze an existing site and produce a migration-ready plan as durable artifacts.

## v1.3.5 — Capability Archives

Goal: complete the local package lifecycle before capability scaffolding.

Deliverables:

- Deterministic `.canto` archive creation
- Archive manifest, content, and checksum validation
- Installation from local `.canto` archives
- Export of installed capabilities
- End-to-end pack, install, inspect, and execution demo

Non-goals:

- No remote package download
- No public registry or publishing
- No dependency auto-install
- No package signing or autonomous trust

Success condition:

A local capability directory can be packed, validated, installed, listed,
inspected, executed, and exported without copying package files into the
source-controlled v1 registry directories.

## v1.4 — Capability Scaffolding Workflow

Goal: turn missing capability responses into approved capability creation workflows.

Deliverables:

- Missing capability recommendation
- Scaffold package structure
- Scaffold tests
- Scaffold manifest
- Approval gate before registration
- Local `canto scaffold NAME` command
- Validate, pack, and install workflow for generated scaffolds

Success condition:

When Echo requests a missing capability, Canto can propose and scaffold a package without automatically trusting or registering it.

The local scaffold command creates deterministic placeholder files only. It
does not use AI generation, contact a remote registry, install dependencies,
or automatically install the generated package.

## v2.0 — Orchestrated Capability Discovery

Goal: discover installed local capabilities, propose reviewable workflows, and
execute only explicitly approved plans.

Deliverables:

- Capability intent, input, and output metadata
- Deterministic installed-capability discovery
- Workflow candidate and execution plan models
- Local plan approval records
- Approved-only sequential execution
- Artifact dependency resolution
- Plan explanation

Non-goals:

- No remote registry or package discovery
- No AI-generated plans or capabilities
- No live credential handling or target writes
- No automatic dependency installation

Success condition:

Canto can discover installed local capabilities for a goal, save and approve a
deterministic plan, execute its steps through existing provider controls, and
explain every selection and dependency.

Remote registry and publishing work remains deferred beyond v2.0.
