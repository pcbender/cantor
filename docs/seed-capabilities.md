# Reviewed Seed Capabilities

MVP v1 ships a small explicit catalogue of trusted built-in providers. List
the machine-readable review metadata with:

```bash
canto seed-capabilities
```

The seed set is:

| Execution identity | Purpose | Access |
| --- | --- | --- |
| `check_dependencies.manifest_dependency_checker` | Inspect declared dependencies without installing them. | Local read |
| `source_inventory.public_html_crawler` | Inventory public sites within approved domains. | Approved network read |
| `migration_report.local_markdown_report` | Create local migration assessment artifacts. | Local artifact read/write |
| `managed_json.local_document` | Demonstrate governed dry run, promotion, verification, and rollback. | Governed local write |

The catalogue is checked in at `canto/seed-capabilities.yaml`, included in the
wheel, and audited against the runtime registry in tests. “Trusted” means the
code is reviewed and distributed with Canto for the single-user local threat
model. It does not mean hostile-code isolation or permission to bypass policy,
approval, credential, runtime-limit, or artifact controls.

Scaffolding providers are distributed developer tools but are deliberately not
part of the reviewed release seed set. Additional `.canto` packages remain
explicit local installations and do not become trusted merely by installation.
