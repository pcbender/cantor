import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from typer.testing import CliRunner

import canto.cli as cli_module
from canto.core.capability_package import (
    CHECKSUMS_NAME,
    CapabilityPackageError,
    pack_capability,
    validate_package,
)
from canto.core.local_registry import Registry
from canto.core.jobs import JobService
from canto.core.registry import Registry as RuntimeRegistry
from canto.core.state import MemoryStateStore
from canto.config import Settings
from canto.models.schemas import JobRequest


def make_capability(tmp_path):
    source = tmp_path / "source_inventory"
    provider = source / "skills" / "source_inventory" / "providers" / "local"
    provider.mkdir(parents=True)
    (source / "canto.yaml").write_text(
        """\
name: source_inventory
version: 1.0.0
skills:
  - source_inventory
providers:
  - source_inventory.local
risk:
  level: low
""",
        encoding="utf-8",
    )
    (source / "skills" / "source_inventory" / "skill.yaml").write_text(
        "name: source_inventory\nproviders:\n  - local\n",
        encoding="utf-8",
    )
    (provider / "provider.yaml").write_text(
        "name: local\nskill: source_inventory\nrunner:\n  type: python\n  entrypoint: run.py\n",
        encoding="utf-8",
    )
    (provider / "run.py").write_text("VALUE = 1\n", encoding="utf-8")
    (source / "__pycache__").mkdir()
    (source / "__pycache__" / "skill.pyc").write_bytes(b"cache")
    (source / ".env").write_text("SECRET=value\n", encoding="utf-8")
    return source


def test_pack_capability_creates_deterministic_archive(tmp_path):
    source = make_capability(tmp_path)
    first = pack_capability(source, tmp_path / "first")
    second = pack_capability(source, tmp_path / "second")

    assert first.name == "source_inventory-1.0.0.canto"
    assert hashlib.sha256(first.read_bytes()).digest() == hashlib.sha256(
        second.read_bytes()
    ).digest()
    with zipfile.ZipFile(first) as archive:
        assert archive.namelist() == [
            CHECKSUMS_NAME,
            "canto.yaml",
            "skills/source_inventory/providers/local/provider.yaml",
            "skills/source_inventory/providers/local/run.py",
            "skills/source_inventory/skill.yaml",
        ]
        assert ".env" not in archive.namelist()
        assert "__pycache__/skill.pyc" not in archive.namelist()


def test_pack_command_creates_named_archive(tmp_path):
    source = make_capability(tmp_path)
    output = tmp_path / "dist"

    result = CliRunner().invoke(
        cli_module.app,
        ["pack", str(source), "--output", str(output)],
    )

    package = output / "source_inventory-1.0.0.canto"
    assert result.exit_code == 0
    assert f"Created {package.resolve()}" in result.output
    assert package.is_file()


def rewrite_archive(source, destination, replacements=None, excluded=None):
    replacements = replacements or {}
    excluded = excluded or set()
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(destination, "w") as changed:
        for info in original.infolist():
            if info.filename in excluded:
                continue
            changed.writestr(info, replacements.get(info.filename, original.read(info.filename)))


def test_validate_package_verifies_manifest_checksums_and_contents(tmp_path):
    package = pack_capability(make_capability(tmp_path), tmp_path / "dist")

    result = validate_package(package)

    assert result.valid is True
    assert result.errors == []
    assert result.manifest.name == "source_inventory"

    cli_result = CliRunner().invoke(
        cli_module.app, ["validate-package", str(package)]
    )
    assert cli_result.exit_code == 0
    assert f"Capability package is valid: {package}" in cli_result.output


def test_package_with_matching_execution_provider_binding_is_valid(tmp_path):
    source = make_capability(tmp_path)
    manifest = source / "canto.yaml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8")
        + "execution:\n"
        + "  providers:\n"
        + "    - skill: source_inventory\n"
        + "      provider: local\n",
        encoding="utf-8",
    )

    result = validate_package(pack_capability(source, tmp_path / "dist"))

    assert result.valid is True


def test_pack_rejects_missing_execution_provider_binding(tmp_path):
    source = make_capability(tmp_path)
    manifest = source / "canto.yaml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8")
        + "execution:\n"
        + "  providers:\n"
        + "    - skill: source_inventory\n"
        + "      provider: missing\n",
        encoding="utf-8",
    )

    with pytest.raises(
        CapabilityPackageError,
        match=r"Missing execution provider binding \(source_inventory, missing\)",
    ):
        pack_capability(source, tmp_path / "dist")


def test_validate_package_rejects_missing_execution_provider_binding(tmp_path):
    package = pack_capability(make_capability(tmp_path), tmp_path / "dist")
    invalid = tmp_path / "missing-binding.canto"
    with zipfile.ZipFile(package) as archive:
        manifest = archive.read("canto.yaml") + (
            b"execution:\n"
            b"  providers:\n"
            b"    - skill: source_inventory\n"
            b"      provider: missing\n"
        )
        checksums = archive.read(CHECKSUMS_NAME).decode("utf-8").splitlines()
    checksums = [
        f"{hashlib.sha256(manifest).hexdigest()}  canto.yaml"
        if line.endswith("  canto.yaml")
        else line
        for line in checksums
    ]
    rewrite_archive(
        package,
        invalid,
        {
            "canto.yaml": manifest,
            CHECKSUMS_NAME: ("\n".join(checksums) + "\n").encode("utf-8"),
        },
    )

    result = validate_package(invalid)
    cli_result = CliRunner().invoke(
        cli_module.app, ["validate-package", str(invalid)]
    )

    expected = "Missing execution provider binding (source_inventory, missing)"
    assert result.valid is False
    assert any(expected in error for error in result.errors)
    assert cli_result.exit_code == 1
    assert expected in cli_result.output


def test_validate_package_rejects_checksum_mismatch(tmp_path):
    package = pack_capability(make_capability(tmp_path), tmp_path / "dist")
    tampered = tmp_path / "tampered.canto"
    run_path = "skills/source_inventory/providers/local/run.py"
    rewrite_archive(package, tampered, {run_path: b"VALUE = 2\n"})

    result = validate_package(tampered)

    assert result.valid is False
    assert f"Checksum mismatch: {run_path}" in result.errors


def test_validate_package_rejects_missing_manifest(tmp_path):
    package = pack_capability(make_capability(tmp_path), tmp_path / "dist")
    incomplete = tmp_path / "incomplete.canto"
    rewrite_archive(package, incomplete, excluded={"canto.yaml"})

    result = validate_package(incomplete)

    assert result.valid is False
    assert "Package is missing canto.yaml" in result.errors


def test_install_command_installs_valid_archive(tmp_path, monkeypatch):
    package = pack_capability(make_capability(tmp_path), tmp_path / "dist")
    registry = Registry.local(tmp_path / "home")
    monkeypatch.setattr(cli_module, "_capability_registry", lambda: registry)

    result = CliRunner().invoke(cli_module.app, ["install", str(package)])

    assert result.exit_code == 0
    assert "Installed source_inventory 1.0.0" in result.output
    installed = registry.inspect("source_inventory")
    assert installed.manifest.name == "source_inventory"
    assert (tmp_path / "home" / ".canto" / "installed" / "source_inventory" / "1.0.0" / CHECKSUMS_NAME).is_file()


def test_install_command_rejects_directory_input(tmp_path, monkeypatch):
    source = make_capability(tmp_path)
    registry = Registry.local(tmp_path / "home")
    monkeypatch.setattr(cli_module, "_capability_registry", lambda: registry)

    result = CliRunner().invoke(cli_module.app, ["install", str(source)])

    assert result.exit_code == 1
    assert "must be a local .canto archive" in result.output


def test_export_round_trip_recreates_identical_package(tmp_path, monkeypatch):
    original = pack_capability(make_capability(tmp_path), tmp_path / "dist")
    registry = Registry.local(tmp_path / "home")
    registry.install_package(original)
    monkeypatch.setattr(cli_module, "_capability_registry", lambda: registry)

    result = CliRunner().invoke(
        cli_module.app,
        ["export", "source_inventory", "--output", str(tmp_path / "exported")],
    )

    exported = tmp_path / "exported" / original.name
    assert result.exit_code == 0
    assert f"Exported {exported.resolve()}" in result.output
    assert exported.read_bytes() == original.read_bytes()
    assert validate_package(exported).valid is True


def make_executable_capability(tmp_path):
    source = tmp_path / "demo_capability"
    provider = source / "skills" / "demo_capability" / "providers" / "local"
    provider.mkdir(parents=True)
    (source / "canto.yaml").write_text(
        """\
name: demo_capability
version: 1.0.0
skills:
  - demo_capability
providers:
  - demo_capability.local
risk:
  level: low
""",
        encoding="utf-8",
    )
    (source / "skills" / "demo_capability" / "skill.yaml").write_text(
        """\
name: demo_capability
providers:
  - local
outputs:
  demo_json:
    type: file
    format: json
""",
        encoding="utf-8",
    )
    (provider / "provider.yaml").write_text(
        """\
name: local
skill: demo_capability
runner:
  type: python
  entrypoint: run.py
inputs: {}
outputs:
  demo_json:
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
artifact.write_text(json.dumps({"executed": True}), encoding="utf-8")
print(json.dumps({"status": "completed", "summary": "Demo executed."}))
""",
        encoding="utf-8",
    )
    return source


def test_end_to_end_pack_install_list_inspect_execute(tmp_path, monkeypatch):
    source = make_executable_capability(tmp_path)
    runner = CliRunner()
    pack_result = runner.invoke(
        cli_module.app,
        ["pack", str(source), "--output", str(tmp_path / "dist")],
    )
    package = tmp_path / "dist" / "demo_capability-1.0.0.canto"
    assert pack_result.exit_code == 0
    local_registry = Registry.local(tmp_path / "home")
    monkeypatch.setattr(cli_module, "_capability_registry", lambda: local_registry)

    install_result = runner.invoke(cli_module.app, ["install", str(package)])
    assert install_result.exit_code == 0
    list_result = runner.invoke(cli_module.app, ["list"])
    assert list_result.exit_code == 0
    assert "demo_capability\t1.0.0" in list_result.output
    inspect_result = runner.invoke(cli_module.app, ["inspect", "demo_capability"])
    assert inspect_result.exit_code == 0
    assert '"name": "demo_capability"' in inspect_result.output
    installed = local_registry.inspect("demo_capability")

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
    runtime_registry = RuntimeRegistry(
        settings.skills_dir,
        settings.tools_dir,
        capability_roots=local_registry.execution_roots(),
    )
    store = MemoryStateStore()
    service = JobService(settings, runtime_registry, store)
    monkeypatch.setattr(
        cli_module,
        "_runtime",
        lambda: (settings, store, runtime_registry, service),
    )

    run_result = runner.invoke(
        cli_module.app,
        ["run", "demo_capability", "--provider", "local"],
    )

    assert run_result.exit_code == 0
    assert '"status": "completed"' in run_result.output
    completed_jobs = [event for event in store.events if event]
    assert completed_jobs
