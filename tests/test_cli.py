from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

import canto.cli as cli_module
from canto.core.local_registry import Registry, RegistryEntry
from canto.models.schemas import JobRequest

FIXTURES = Path(__file__).parent / "fixtures" / "capabilities"


def test_run_prints_job_id_before_processing(runtime, monkeypatch):
    settings, registry, store, service = runtime
    job = service.create_job(
        JobRequest(
            skill="scaffold_tool",
            provider="local_scaffolder",
            inputs={"name": "sample_tool"},
        )
    )
    monkeypatch.setattr(cli_module, "_runtime", lambda: (settings, store, registry, service))
    monkeypatch.setattr(service, "create_job", lambda request: job)
    monkeypatch.setattr(service, "process_job", lambda job_id: job)

    result = CliRunner().invoke(
        cli_module.app,
        ["run", "scaffold_tool", "--provider", "local_scaffolder", "--input", "name=sample_tool"],
    )

    assert result.exit_code == 0
    assert f"Created {job.job_id} (queued); processing..." in result.output
    assert f'"job_id": "{job.job_id}"' in result.output


def test_capability_validate_succeeds_and_prints_warnings():
    path = FIXTURES / "unknown_top_level_field.yaml"
    result = CliRunner().invoke(
        cli_module.app, ["capability", "validate", str(path)]
    )

    assert result.exit_code == 0
    assert "Warning: Unknown top-level field: future_option" in result.output
    assert f"Capability manifest is valid: {path}" in result.output


def test_capability_validate_fails_with_clear_errors():
    path = FIXTURES / "invalid_version.yaml"
    result = CliRunner().invoke(
        cli_module.app, ["capability", "validate", str(path)]
    )

    assert result.exit_code == 1
    assert "Error: version must use semantic version format" in result.output


def test_list_shows_empty_installed_capability_state(tmp_path, monkeypatch):
    registry = Registry.local(tmp_path)
    monkeypatch.setattr(cli_module, "_capability_registry", lambda: registry)

    result = CliRunner().invoke(cli_module.app, ["list"])

    assert result.exit_code == 0
    assert result.output == "No capabilities installed.\n"


def test_list_displays_installed_capabilities(tmp_path, monkeypatch):
    registry = Registry.local(tmp_path)
    paths = registry.store.paths
    paths.index_file.write_text(
        json.dumps(
            [
                {
                    "name": "source_inventory",
                    "version": "1.0.0",
                    "installed": True,
                    "path": "/tmp/source_inventory",
                    "checksum": "sha256:abc123",
                    "risk": "low",
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(cli_module, "_capability_registry", lambda: registry)

    result = CliRunner().invoke(cli_module.app, ["list"])

    assert result.exit_code == 0
    assert "NAME\tVERSION\tRISK\tPATH" in result.output
    assert "source_inventory\t1.0.0\tlow\t/tmp/source_inventory" in result.output


def test_search_displays_local_registry_matches(tmp_path, monkeypatch):
    registry = Registry.local(tmp_path)
    paths = registry.store.paths
    paths.index_file.write_text(
        json.dumps(
            [
                {
                    "name": "source_inventory",
                    "version": "1.0.0",
                    "installed": False,
                    "path": "/tmp/source_inventory",
                    "checksum": "sha256:abc123",
                    "risk": "low",
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(cli_module, "_capability_registry", lambda: registry)

    result = CliRunner().invoke(cli_module.app, ["search", "inventory"])

    assert result.exit_code == 0
    assert "NAME\tVERSION\tINSTALLED\tRISK\tPATH" in result.output
    assert "source_inventory\t1.0.0\tno\tlow\t/tmp/source_inventory" in result.output


def test_search_reports_no_local_matches(tmp_path, monkeypatch):
    registry = Registry.local(tmp_path)
    monkeypatch.setattr(cli_module, "_capability_registry", lambda: registry)

    result = CliRunner().invoke(cli_module.app, ["search", "inventory"])

    assert result.exit_code == 0
    assert result.output == "No local capabilities found matching: inventory\n"


def test_inspect_displays_registry_entry_and_manifest(tmp_path, monkeypatch):
    registry = Registry.local(tmp_path)
    install_dir = registry.store.paths.installed / "source_inventory" / "1.0.0"
    install_dir.mkdir(parents=True)
    (install_dir / "canto.yaml").write_text(
        "name: source_inventory\nversion: 1.0.0\n",
        encoding="utf-8",
    )
    registry.store.paths.index_file.write_text(
        json.dumps(
            [
                {
                    "name": "source_inventory",
                    "version": "1.0.0",
                    "installed": True,
                    "path": str(install_dir),
                    "checksum": "sha256:abc123",
                    "risk": "low",
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(cli_module, "_capability_registry", lambda: registry)

    result = CliRunner().invoke(cli_module.app, ["inspect", "source_inventory"])

    assert result.exit_code == 0
    assert '"name": "source_inventory"' in result.output
    assert '"checksum": "sha256:abc123"' in result.output


def test_remove_deletes_installed_capability(tmp_path, monkeypatch):
    registry = Registry.local(tmp_path)
    install_dir = registry.store.paths.installed / "source_inventory" / "1.0.0"
    install_dir.mkdir(parents=True)
    registry.store.paths.index_file.write_text(
        json.dumps(
            [
                {
                    "name": "source_inventory",
                    "version": "1.0.0",
                    "installed": True,
                    "path": str(install_dir),
                    "checksum": "sha256:abc123",
                    "risk": "low",
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(cli_module, "_capability_registry", lambda: registry)

    result = CliRunner().invoke(cli_module.app, ["remove", "source_inventory"])

    assert result.exit_code == 0
    assert result.output == "Removed source_inventory 1.0.0\n"
    assert not install_dir.exists()


def test_validate_installed_reports_success(tmp_path, monkeypatch):
    registry = Registry.local(tmp_path)
    install_dir = registry.store.paths.installed / "source_inventory" / "1.0.0"
    install_dir.mkdir(parents=True)
    (install_dir / "canto.yaml").write_text(
        "name: source_inventory\nversion: 1.0.0\n",
        encoding="utf-8",
    )
    registry.store.save(
        [
            RegistryEntry(
                name="source_inventory",
                version="1.0.0",
                installed=True,
                path=str(install_dir),
                checksum=registry.store.checksum_directory(install_dir),
                risk="low",
            )
        ]
    )
    monkeypatch.setattr(cli_module, "_capability_registry", lambda: registry)

    result = CliRunner().invoke(
        cli_module.app, ["validate-installed", "source_inventory"]
    )

    assert result.exit_code == 0
    assert result.output == "Installed capability is valid: source_inventory\n"


def test_install_rejects_non_archive_file(tmp_path, monkeypatch):
    registry = Registry.local(tmp_path / "home")
    archive = tmp_path / "source_inventory.txt"
    archive.write_bytes(b"not-an-archive")
    monkeypatch.setattr(cli_module, "_capability_registry", lambda: registry)

    result = CliRunner().invoke(cli_module.app, ["install", str(archive)])

    assert result.exit_code == 1
    assert "must be a local .canto archive" in result.output
