# Canto Capability Installation Design

This document defines local installation from validated `.canto` archives.

## Initial command

```bash
canto install path/to/name-version.canto
```

The source must be a local `.canto` file. The command does not download
packages, query a remote registry, or resolve a name to a package.

## Validation

Before changing local state, the installer will:

1. Validate ZIP paths, entry types, and duplicate names.
2. Load and validate the root `canto.yaml`.
3. Verify exact `CHECKSUMS.sha256` coverage and every file digest.
4. Verify declared skill, provider, and tool manifests are present.
5. Reject an existing installation with the same name and version.

Manifest warnings are displayed but do not stop installation. Validation
errors stop installation without changing local state.

## Local installation

Validated content is safely extracted under `~/.canto/cache/` and then moved
to:

```text
~/.canto/installed/<name>/<version>/
```

After the move succeeds, the installer writes a `RegistryEntry` to
`~/.canto/registry/index.json` with:

- Manifest `name` and `version`.
- `installed: true`.
- The canonical installed path.
- The installed directory SHA-256 digest.
- Manifest `risk.level`.

The index update uses the `RegistryStore` abstraction and an atomic file
replacement. If copying or movement fails, temporary files are removed and the
index is unchanged. If index writing fails after movement, the new installed
directory is removed so the operation does not leave unindexed content.

## Dependencies

The command reports manifest dependency declarations but does not resolve,
download, or install Python or system dependencies. Dependency cleanup is also
outside removal behavior.

Dependency resolution, environment isolation, version conflict handling, and
system package approval remain future work.

## Runtime boundary

Installation stores verified content and local registry metadata only. It does
not merge files into the source-controlled v1 `skills/` or `tools/`
directories, reload the v1 runtime registry, execute providers, or alter job,
policy, and approval behavior.

Inspection and installed validation read `canto.yaml` from the installed
directory. Removal deletes that version directory and its registry entry.

Remote registry discovery, package download, publishing, and distributed trust
remain future Canto v2.0 work.
