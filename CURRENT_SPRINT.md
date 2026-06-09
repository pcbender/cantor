# Current Sprint — v1.1 Capability Packaging

## Sprint Goal

Create the first layer of Canto capability packaging: a manifest schema and validator. Do not implement pack/install behavior until manifest validation is stable.

## Architecture Rule

This sprint must not change the v1 execution model. Skills, providers, tools, artifacts, jobs, approvals, and the current registry remain intact.

## Tasks

| ID | Status | Task |
| --- | --- | --- |
| CP-001 | READY | Add capability manifest model and schema rules. |
| CP-002 | BLOCKED | Add manifest validation service. Depends on CP-001. |
| CP-003 | BLOCKED | Add CLI validation command. Depends on CP-002. |
| CP-004 | BLOCKED | Add valid and invalid fixture manifests. Depends on CP-001. |
| CP-005 | BLOCKED | Add unit and CLI tests. Depends on CP-003 and CP-004. |
| CP-006 | BLOCKED | Write packaging design notes from implementation. Depends on CP-005. |

## Definition of Done

- Existing tests still pass.
- New tests cover valid and invalid manifests.
- CLI returns clear errors for invalid manifests.
- No unrelated files are refactored.
- No remote registry behavior is introduced.
