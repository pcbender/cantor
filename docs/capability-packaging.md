# Canto Capability Packaging Design

This document describes the implemented local `.canto` package format.

## Package format

A capability package will use the `.canto` extension and contain a ZIP archive.
The proposed filename is `<name>-<version>.canto`, using the validated manifest
`name` and `version`.

Packaging must first run the existing manifest validation equivalent to:

```bash
canto capability validate path/to/canto.yaml
```

Validation errors must stop packaging. Warnings may be displayed without
stopping it.

## Package contents

The archive will contain relative POSIX paths with no leading slash:

- One package manifest at the archive root, named `canto.yaml`.
- Declared skill directories under `skills/`.
- Declared tool directories under `tools/`.
- Provider files within their owning skill directories.
- `CHECKSUMS.sha256`, generated during packaging.

Only files belonging to components declared by the manifest will be included.
Archive entries must not escape the package root, and symbolic links will not
be followed or stored in the initial format.

## Determinism

Files will be added in lexicographic order by archive path. The packer will use
fixed timestamps, normalized file permissions, POSIX path separators, and a
fixed compression configuration. Repacking identical input bytes and manifest
data with the same Canto version should produce identical archive bytes.

## Checksums

`CHECKSUMS.sha256` will contain the lowercase SHA-256 digest and archive path
for every packaged file except `CHECKSUMS.sha256` itself. Its records will use
the same lexicographic path order as the archive. A future installer must
verify all listed checksums before using package contents.

Checksums provide integrity detection, not publisher identity. Package signing
and trust policy are separate future design work.

## Excluded files

The initial packer will exclude:

- `.git/`, `.venv/`, `.env`, and editor or operating-system metadata.
- `__pycache__/`, `*.pyc`, `.pytest_cache/`, and other generated caches.
- Canto job output and scaffold work directories.
- Existing `.canto` archives.
- Files outside declared skill and tool component directories.

Secrets and credentials must never be packaged. A later implementation should
reject known credential files rather than relying only on exclusion patterns.

## Commands

Create a deterministic package from a local capability directory:

```bash
canto pack path/to/capability-directory --output dist/
```

Validate package structure, manifest semantics, component completeness, and
checksums:

```bash
canto validate-package dist/name-version.canto
```

Install a validated local archive:

```bash
canto install dist/name-version.canto
```

Export an installed capability back to a deterministic archive:

```bash
canto export name --output dist/
```

Installed package roots are exposed to runtime discovery without copying files
into the source-controlled v1 registry directories. Duplicate skill, provider,
or tool names are rejected.

Remote registry discovery, publishing, download, and trust distribution remain
future Canto v2.0 work.

## Deferred work

- Which executable permission bits, if any, should be retained after
  normalization.
- How package signing and publisher trust should be represented in a later
  format revision.
