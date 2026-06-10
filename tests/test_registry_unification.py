import json
from pathlib import Path

from fastapi.testclient import TestClient
from typer.testing import CliRunner

import canto.cli as cli_module
from canto.api.server import create_app
from canto.config import Settings
from canto.core.capability_package import pack_capability
from canto.core.jobs import JobService
from canto.core.local_registry import Registry as CapabilityRegistry
from canto.core.registry import Registry as RuntimeRegistry
from canto.core.state import MemoryStateStore


def test_v21_registry_unification_end_to_end(tmp_path, monkeypatch):
    source = tmp_path / "source" / "demo_package"
    provider = source / "skills" / "demo_skill" / "providers" / "local"
    provider.mkdir(parents=True)
    (source / "canto.yaml").write_text(
        """\
name: demo_package
version: 1.0.0
description: Produce a local registry unification demo artifact.
skills:
  - demo_skill
providers:
  - demo_skill.local
intents:
  - registry_demo
outputs:
  - demo.json
execution:
  providers:
    - skill: demo_skill
      provider: local
      produces:
        demo_file: demo.json
risk:
  level: low
  requires_approval: false
""",
        encoding="utf-8",
    )
    (source / "skills" / "demo_skill" / "skill.yaml").write_text(
        "name: demo_skill\nproviders:\n  - local\n", encoding="utf-8"
    )
    (provider / "provider.yaml").write_text(
        """\
name: local
skill: demo_skill
runner:
  type: python
  entrypoint: run.py
inputs: {}
outputs:
  demo_file:
    path: demo.json
    type: file
    format: json
permissions:
  network_read: false
  network_write: false
  filesystem_write: []
  destructive: false
risk_level: 1
""",
        encoding="utf-8",
    )
    (provider / "run.py").write_text(
        """\
import json
import sys
from pathlib import Path

request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
artifact = Path(request["artifact_dir"]) / "demo.json"
artifact.write_text(json.dumps({"unified": True}), encoding="utf-8")
print(json.dumps({"status": "completed", "summary": "Demo complete."}))
""",
        encoding="utf-8",
    )
    package = pack_capability(source, tmp_path / "dist")

    runtime_root = tmp_path / "runtime"
    (runtime_root / "skills").mkdir(parents=True)
    (runtime_root / "tools").mkdir()
    settings = Settings(
        root_dir=runtime_root,
        redis_url="redis://unused",
        host="127.0.0.1",
        port=8765,
        provider_timeout_seconds=10,
        max_provider_output_bytes=1_048_576,
    )
    capability_registry = CapabilityRegistry.local(tmp_path / "home")
    state = MemoryStateStore()

    # Both views are alive before installation; lazy registry refresh must expose it.
    http_app = create_app(settings, state, capability_registry)
    cli_runtime_registry = RuntimeRegistry(
        settings.skills_dir,
        settings.tools_dir,
        capability_registry=capability_registry,
    )
    cli_job_service = JobService(settings, cli_runtime_registry, state)
    monkeypatch.setattr(
        cli_module, "_capability_registry", lambda: capability_registry
    )
    monkeypatch.setattr(
        cli_module,
        "_runtime",
        lambda: (settings, state, cli_runtime_registry, cli_job_service),
    )
    runner = CliRunner()

    install_result = runner.invoke(cli_module.app, ["install", str(package)])
    assert install_result.exit_code == 0
    assert "Installed demo_package 1.0.0" in install_result.output

    http_registry = TestClient(http_app).get("/registry")
    assert http_registry.status_code == 200
    assert any(
        provider["skill"] == "demo_skill" and provider["name"] == "local"
        for provider in http_registry.json()["providers"]
    )

    cli_registry = runner.invoke(cli_module.app, ["registry"])
    assert cli_registry.exit_code == 0
    assert json.loads(cli_registry.output) == http_registry.json()

    discover = runner.invoke(
        cli_module.app, ["discover", "run the registry demo"]
    )
    assert discover.exit_code == 0
    assert json.loads(discover.output)[0]["name"] == "demo_package"

    planned = runner.invoke(
        cli_module.app,
        ["plan", "run the registry demo", "--approve"],
    )
    assert planned.exit_code == 0
    plan = json.loads(planned.output)
    assert plan["status"] == "approved"
    step = plan["candidate"]["steps"][0]
    assert (step["capability"], step["version"]) == ("demo_package", "1.0.0")
    assert (step["skill"], step["provider"]) == ("demo_skill", "local")
    assert step["artifact_outputs"] == {"demo_file": "demo.json"}
    assert step["requires"] == []
    assert step["produces"] == ["demo.json"]

    executed = runner.invoke(cli_module.app, ["execute", plan["plan_id"]])
    assert executed.exit_code == 0
    execution = json.loads(executed.output)
    assert execution["status"] == "completed"
    artifact_path = Path(execution["artifacts"]["demo.json"])
    assert artifact_path.is_relative_to(settings.jobs_dir)
    assert json.loads(artifact_path.read_text(encoding="utf-8")) == {
        "unified": True
    }

    explained = runner.invoke(cli_module.app, ["explain", plan["plan_id"]])
    assert explained.exit_code == 0
    explanation = json.loads(explained.output)
    assert explanation["status"] == "completed"
    assert explanation["steps"][0]["skill"] == "demo_skill"
    assert explanation["steps"][0]["provider"] == "local"
    assert len(state.jobs) == 1
