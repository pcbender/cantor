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

## v1.4 — Capability Scaffolding Workflow

Goal: turn missing capability responses into approved capability creation workflows.

Deliverables:

- Missing capability recommendation
- Scaffold package structure
- Scaffold tests
- Scaffold manifest
- Approval gate before registration

Success condition:

When Echo requests a missing capability, Canto can propose and scaffold a package without automatically trusting or registering it.

## v2.0 — Remote Registry

Goal: enable a remote capability registry with trust metadata.

Deliverables:

- Remote manifest index
- Capability search
- Capability fetch
- Signature/checksum verification
- Risk metadata
- Compatibility metadata

Non-goals:

- No fully open marketplace at first
- No unreviewed autonomous installs

Success condition:

Canto can discover a remote capability, inspect its metadata, verify integrity, and install only with Cantor approval.
