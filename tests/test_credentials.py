from __future__ import annotations

import json
import os
from pathlib import Path

from canto.core.credentials import CredentialVault, resolve_credential_inputs
from canto.core.jobs import JobService
from canto.core.registry import Registry
from canto.core.state import MemoryStateStore
from canto.models.schemas import JobRequest


def test_vault_encrypts_records_and_uses_private_permissions(tmp_path):
    vault = CredentialVault(tmp_path / "vault")

    reference = vault.set("wordpress", "api_token", "not-plaintext")

    record = next((tmp_path / "vault" / "records").glob("*.json"))
    assert reference == "vault:wordpress/api_token"
    assert "not-plaintext" not in record.read_text(encoding="utf-8")
    assert vault.get("wordpress", "api_token") == "not-plaintext"
    assert os.stat(tmp_path / "vault").st_mode & 0o777 == 0o700
    assert os.stat(tmp_path / "vault" / "master.key").st_mode & 0o777 == 0o600
    assert os.stat(record).st_mode & 0o777 == 0o600


def test_vault_replaces_and_deletes_records(tmp_path):
    vault = CredentialVault(tmp_path / "vault")
    vault.set("default", "token", "first")
    vault.rotate("default", "token", "second")

    assert vault.list() == ["vault:default/token"]
    assert vault.get("default", "token") == "second"
    assert vault.generation("default", "token") == 2
    vault.delete("default", "token")
    assert vault.list() == []


def test_resolves_environment_and_vault_references(tmp_path, monkeypatch):
    vault = CredentialVault(tmp_path / "vault")
    vault.set("demo", "token", "vault-secret")
    monkeypatch.setenv("DEMO_PASSWORD", "env-secret")

    resolved, values = resolve_credential_inputs(
        {
            "api_token_ref": "vault:demo/token",
            "password_ref": "env:DEMO_PASSWORD",
        },
        vault,
    )

    assert resolved == {
        "api_token_ref": "vault-secret",
        "password_ref": "env-secret",
    }
    assert values == [
        "vault:demo/token",
        "vault-secret",
        "env:DEMO_PASSWORD",
        "env-secret",
    ]


def test_job_persists_reference_but_provider_receives_secret(runtime, tmp_path):
    settings, registry, store, _ = runtime
    provider_dir = settings.skills_dir / "secret_demo" / "providers" / "local"
    provider_dir.mkdir(parents=True)
    (settings.skills_dir / "secret_demo" / "skill.yaml").write_text(
        "name: secret_demo\nproviders: [local]\n", encoding="utf-8"
    )
    (provider_dir / "provider.yaml").write_text(
        """name: local
skill: secret_demo
inputs:
  api_token_ref: {type: string, required: true}
outputs:
  proof: {path: proof.json, required: true}
runner: {type: python, entrypoint: run.py}
permissions: {network_read: false, filesystem_write: true, destructive: false}
risk_level: 1
""",
        encoding="utf-8",
    )
    (provider_dir / "run.py").write_text(
        """import json, sys
from pathlib import Path
request = json.loads(Path(sys.argv[1]).read_text())
Path(request['artifact_dir'], 'proof.json').write_text(json.dumps({'received': request['inputs']['api_token_ref'] == 'secret-value'}))
print(json.dumps({'status': 'completed', 'summary': 'done'}))
""",
        encoding="utf-8",
    )
    registry = Registry(settings.skills_dir, settings.tools_dir)
    vault = CredentialVault(tmp_path / "vault")
    vault.set("demo", "token", "secret-value")
    service = JobService(settings, registry, store, vault=vault)

    job = service.create_job(
        JobRequest(
            skill="secret_demo",
            provider="local",
            inputs={"api_token_ref": "vault:demo/token"},
        )
    )
    completed = service.process_job(job.job_id)

    persisted = json.dumps(store.get_job(job.job_id))
    assert completed.status == "completed"
    assert "vault:demo/token" in persisted
    assert "secret-value" not in persisted
    assert not Path(job.artifact_dir, "provider_request.json").exists()
    assert json.loads(Path(job.artifact_dir, "proof.json").read_text()) == {
        "received": True
    }


def test_provider_outputs_and_artifacts_are_redacted(runtime, tmp_path):
    settings, _, store, _ = runtime
    provider_dir = settings.skills_dir / "leak_demo" / "providers" / "local"
    provider_dir.mkdir(parents=True)
    (settings.skills_dir / "leak_demo" / "skill.yaml").write_text(
        "name: leak_demo\nproviders: [local]\n", encoding="utf-8"
    )
    (provider_dir / "provider.yaml").write_text(
        """name: local
skill: leak_demo
inputs:
  api_token_ref: {type: string, required: true}
outputs:
  leak: {path: leak.txt, required: true}
runner: {type: python, entrypoint: run.py}
permissions: {network_read: false, filesystem_write: true, destructive: false}
risk_level: 1
""",
        encoding="utf-8",
    )
    (provider_dir / "run.py").write_text(
        """import json, sys
from pathlib import Path
request = json.loads(Path(sys.argv[1]).read_text())
secret = request['inputs']['api_token_ref']
Path(request['artifact_dir'], 'leak.txt').write_text('artifact=' + secret)
print(json.dumps({'status': 'completed', 'summary': 'result=' + secret, 'stderr': 'error=' + secret}))
""",
        encoding="utf-8",
    )
    registry = Registry(settings.skills_dir, settings.tools_dir)
    vault = CredentialVault(tmp_path / "vault")
    vault.set("demo", "token", "secret-value")
    service = JobService(settings, registry, store, vault=vault)
    job = service.create_job(
        JobRequest(
            skill="leak_demo",
            provider="local",
            inputs={"api_token_ref": "vault:demo/token"},
        )
    )

    completed = service.process_job(job.job_id)

    persisted = json.dumps(store.get_job(job.job_id))
    events = json.dumps(store.get_events(job.job_id))
    artifact = Path(job.artifact_dir, "leak.txt").read_text()
    assert "secret-value" not in persisted + events + artifact
    assert "vault:demo/token" in persisted
    assert "[REDACTED]" in persisted
    assert artifact == "artifact=[REDACTED]"


def test_failed_provider_details_and_partial_artifacts_are_redacted(
    runtime, tmp_path
):
    settings, _, store, _ = runtime
    provider_dir = settings.skills_dir / "failed_leak" / "providers" / "local"
    provider_dir.mkdir(parents=True)
    (settings.skills_dir / "failed_leak" / "skill.yaml").write_text(
        "name: failed_leak\nproviders: [local]\n", encoding="utf-8"
    )
    (provider_dir / "provider.yaml").write_text(
        """name: local
skill: failed_leak
inputs:
  api_token_ref: {type: string, required: true}
outputs: {}
runner: {type: python, entrypoint: run.py}
permissions: {network_read: false, filesystem_write: true, destructive: false}
risk_level: 1
""",
        encoding="utf-8",
    )
    (provider_dir / "run.py").write_text(
        """import json, sys
from pathlib import Path
request = json.loads(Path(sys.argv[1]).read_text())
secret = request['inputs']['api_token_ref']
Path(request['artifact_dir'], 'partial.log').write_text(secret)
print(secret)
print(secret, file=sys.stderr)
raise SystemExit(2)
""",
        encoding="utf-8",
    )
    registry = Registry(settings.skills_dir, settings.tools_dir)
    vault = CredentialVault(tmp_path / "vault")
    vault.set("demo", "token", "failure-secret")
    service = JobService(settings, registry, store, vault=vault)
    job = service.create_job(
        JobRequest(
            skill="failed_leak",
            provider="local",
            inputs={"api_token_ref": "vault:demo/token"},
        )
    )

    failed = service.process_job(job.job_id)

    serialized = json.dumps(failed.model_dump(mode="json"))
    events = json.dumps(store.get_events(job.job_id))
    assert failed.status == "failed"
    assert "failure-secret" not in serialized + events
    assert Path(job.artifact_dir, "partial.log").read_text() == "[REDACTED]"
