# ADR 0001: Canonical Execution Identity

Status: Accepted

## Context

Canto has two related registries. The runtime registry loads skills, providers,
and tools for `JobService` and the runner. The capability registry tracks
installed capability packages by name, version, path, checksum, and risk.

The planner currently discovers capability packages and later resolves their
provider declarations. Execution ultimately requires a concrete provider lookup
in the runtime registry. A stable distinction is needed between the identity of
something runnable and the identity of the package that distributed it.

## Decision

`(skill, provider)` is the canonical execution identity.

The planner must resolve every executable step to an exact skill and provider.
`JobService` uses that pair for validation, policy and dependency checks, and
provider lookup. The runner receives the provider manifest selected by that
same pair.

`capability@version` is the canonical packaging and provenance identity.
Capability packages use it to identify an installed distribution and retain its
manifest, checksum, risk, and source path. Package provenance remains attached
to planned and executed work but does not replace `(skill, provider)` at the
execution boundary.

## Consequences

- The runtime registry remains authoritative for whether a `(skill, provider)`
  pair can execute.
- Capability packages may expose one or more runnable provider bindings.
- Planner output must carry both the runnable identity and package provenance.
- CLI and HTTP surfaces must derive availability from the same executable
  registry view.
- `JobService` and the runner do not need a package-oriented execution path.
- Package validation must ensure declared provider bindings exist in package
  contents before they are added to the executable registry view.

## Rejected Alternatives

### `capability@version` as execution identity

This would require `JobService`, the runtime registry, and the runner to resolve
packages during every execution. It would also obscure which provider inside a
package is being run and would duplicate the mature `(skill, provider)` path.

### Permanent dual crosswalk

Maintaining separate capability-to-provider and provider-to-capability
crosswalks as the permanent architecture would create two sources of truth.
Drift would make planning, HTTP visibility, approvals, and execution disagree.
Provider bindings belong in capability package metadata, and executable plans
must persist the resolved pair directly.

## Migration Notes

1. Add optional explicit provider bindings to capability manifests while
   preserving existing flat provider declarations.
2. Validate bindings against capability package contents.
3. Resolve planner steps to `(skill, provider)` and retain
   `capability@version` as provenance.
4. Route orchestration through `JobService` and the existing runner.
5. Unify CLI and HTTP around one refreshable runtime registry view.
6. Retire compatibility crosswalk fields only after existing manifests and
   saved plans have a supported migration path.
