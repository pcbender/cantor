import json
import subprocess
import sys

import yaml
from typer.testing import CliRunner

import canto.cli as cli_module
from canto.core.capability_manifest import (
    CapabilityManifest,
    CapabilityManifestValidator,
)
from canto.core.capability_scaffold import SCAFFOLD_FILES
from canto.core.local_registry import Registry


def test_scaffold_command_creates_structure_and_manifest(tmp_path):
    result = CliRunner().invoke(
        cli_module.app,
        ["scaffold", "example_capability", "--output", str(tmp_path)],
    )

    destination = tmp_path / "example_capability"
    assert result.exit_code == 0
    assert f"Created scaffold {destination.resolve()}" in result.output
    for template in SCAFFOLD_FILES:
        path = destination / template.format(name="example_capability")
        assert path.is_file()
        assert path.read_text(encoding="utf-8")

    manifest = CapabilityManifest.load(destination / "manifest.yaml")
    validation = CapabilityManifestValidator.validate(manifest)
    assert validation.valid is True
    assert manifest.name == "example_capability"
    assert manifest.version == "0.1.0"
    assert manifest.skills == ["example_capability"]
    assert manifest.providers == ["example_capability.local"]

    skill = yaml.safe_load(
        (destination / "skills/example_capability/skill.yaml").read_text(
            encoding="utf-8"
        )
    )
    provider = yaml.safe_load(
        (
            destination
            / "skills/example_capability/providers/local/provider.yaml"
        ).read_text(encoding="utf-8")
    )
    assert skill["providers"] == ["local"]
    assert provider["runner"] == {"type": "python", "entrypoint": "run.py"}
    assert provider["permissions"]["network_read"] is False


def test_generated_provider_and_test_are_runnable(tmp_path):
    result = CliRunner().invoke(
        cli_module.app,
        ["scaffold", "example_capability", "--output", str(tmp_path)],
    )
    assert result.exit_code == 0
    destination = tmp_path / "example_capability"
    runner = destination / "skills/example_capability/providers/local/run.py"
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps({"inputs": {}, "artifact_dir": str(tmp_path)}),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [sys.executable, str(runner), str(request)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["status"] == "completed"

    generated_tests = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "tests"],
        cwd=destination,
        capture_output=True,
        text=True,
        check=False,
    )
    assert generated_tests.returncode == 0, generated_tests.stdout + generated_tests.stderr


def test_scaffold_command_rejects_existing_destination(tmp_path):
    destination = tmp_path / "example_capability"
    destination.mkdir()

    result = CliRunner().invoke(
        cli_module.app,
        ["scaffold", "example_capability", "--output", str(tmp_path)],
    )

    assert result.exit_code == 1
    assert "already exists" in result.output


def test_scaffold_validate_pack_install_flow(tmp_path, monkeypatch):
    runner = CliRunner()
    scaffold_result = runner.invoke(
        cli_module.app,
        ["scaffold", "example_capability", "--output", str(tmp_path)],
    )
    assert scaffold_result.exit_code == 0
    destination = tmp_path / "example_capability"

    validate_result = runner.invoke(
        cli_module.app,
        ["capability", "validate", str(destination / "manifest.yaml")],
    )
    assert validate_result.exit_code == 0
    assert "Capability manifest is valid" in validate_result.output

    dist = tmp_path / "dist"
    monkeypatch.chdir(destination)
    pack_result = runner.invoke(
        cli_module.app,
        ["pack", ".", "--output", str(dist)],
    )
    package = dist / "example_capability-0.1.0.canto"
    assert pack_result.exit_code == 0
    assert package.is_file()

    registry = Registry.local(tmp_path / "home")
    monkeypatch.setattr(cli_module, "_capability_registry", lambda: registry)
    install_result = runner.invoke(cli_module.app, ["install", str(package)])

    assert install_result.exit_code == 0
    assert "Installed example_capability 0.1.0" in install_result.output
    assert registry.inspect("example_capability").manifest.name == "example_capability"
