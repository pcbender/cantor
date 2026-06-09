# Canto Capability Scaffolding

The local scaffold command creates a minimal capability source directory that
can be edited, validated, packed, and installed through the existing package
workflow. It does not generate domain logic or activate the capability.

## Command

```bash
canto scaffold NAME
```

By default, the command creates `./NAME/`. An alternate parent directory may
be selected with `--output DIRECTORY`.

`NAME` must follow capability manifest naming rules. The destination must not
already exist; scaffolding never merges with or overwrites existing files.

## Generated layout

```text
NAME/
├── manifest.yaml
├── README.md
├── skills/
│   └── NAME/
│       ├── skill.yaml
│       └── providers/
│           └── local/
│               ├── provider.yaml
│               └── run.py
└── tests/
    └── test_provider.py
```

`manifest.yaml` is a package manifest and is canonicalized to `canto.yaml`
when packed. The skill and provider manifests use the existing v1 runtime
formats. `run.py` is a deterministic placeholder that returns a completed
result without network access, dependencies, or generated artifacts. The test
invokes that placeholder with a local request fixture.

## Workflow

A new scaffold is expected to pass:

```bash
canto capability validate NAME/manifest.yaml
canto pack NAME --output dist/
canto install dist/NAME-0.1.0.canto
```

Installation remains an explicit separate action. Scaffolding does not modify
the local capability registry or the source-controlled v1 registry.

## Non-goals

- No AI-generated implementation or prompts.
- No remote registry access, publishing, or package download.
- No dependency detection or automatic dependency installation.
- No credentials, network policy, or target-system configuration.
- No automatic install, registration, approval, or execution.
- No replacement for the existing approval-gated skill/provider/tool scaffold
  capabilities used by jobs.
