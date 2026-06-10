import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from canto.core.local_registry import (
    LocalRegistryPaths,
    Registry,
    RegistryEntry,
    RegistryStore,
)


def test_registry_index_entry_models_metadata():
    entry = RegistryEntry(
        name="source_inventory",
        version="1.0.0",
        installed=True,
        path="/home/example/.canto/installed/source_inventory/1.0.0",
        checksum="sha256:abc123",
        risk="low",
    )

    assert entry.model_dump() == {
        "name": "source_inventory",
        "version": "1.0.0",
        "installed": True,
        "path": "/home/example/.canto/installed/source_inventory/1.0.0",
        "checksum": "sha256:abc123",
        "risk": "low",
    }


def test_registry_index_entry_requires_all_metadata():
    with pytest.raises(ValidationError, match="checksum"):
        RegistryEntry.model_validate(
            {
                "name": "source_inventory",
                "version": "1.0.0",
                "installed": True,
                "path": "/tmp/source_inventory",
                "risk": "low",
            }
        )


def test_registry_index_entry_rejects_unknown_risk_level():
    with pytest.raises(ValidationError, match="risk"):
        RegistryEntry(
            name="source_inventory",
            version="1.0.0",
            installed=True,
            path="/tmp/source_inventory",
            checksum="sha256:abc123",
            risk="critical",
        )


def test_local_registry_paths_use_canto_directory(tmp_path):
    paths = LocalRegistryPaths.from_home(tmp_path)

    assert paths.root == tmp_path / ".canto"
    assert paths.registry == tmp_path / ".canto" / "registry"
    assert paths.installed == tmp_path / ".canto" / "installed"
    assert paths.cache == tmp_path / ".canto" / "cache"


def test_create_local_registry_layout_creates_directories(tmp_path):
    registry = Registry.local(tmp_path)
    paths = registry.store.paths

    assert paths.root.is_dir()
    assert paths.registry.is_dir()
    assert paths.installed.is_dir()
    assert paths.cache.is_dir()


def test_create_local_registry_layout_is_idempotent(tmp_path):
    first = Registry.local(tmp_path).store.paths
    second = Registry.local(tmp_path).store.paths

    assert first == second


def test_list_installed_capabilities_is_empty_without_index(tmp_path):
    registry = Registry.local(tmp_path)

    assert registry.list_installed() == []


def test_list_installed_capabilities_filters_and_sorts_index(tmp_path):
    registry = Registry.local(tmp_path)
    paths = registry.store.paths
    paths.index_file.write_text(
        json.dumps(
            [
                {
                    "name": "zeta",
                    "version": "1.0.0",
                    "installed": True,
                    "path": "/tmp/zeta",
                    "checksum": "sha256:zeta",
                    "risk": "medium",
                },
                {
                    "name": "available_only",
                    "version": "1.0.0",
                    "installed": False,
                    "path": "/tmp/available_only",
                    "checksum": "sha256:available",
                    "risk": "low",
                },
                {
                    "name": "alpha",
                    "version": "2.0.0",
                    "installed": True,
                    "path": "/tmp/alpha",
                    "checksum": "sha256:alpha",
                    "risk": "high",
                },
            ]
        ),
        encoding="utf-8",
    )

    entries = registry.list_installed()

    assert [entry.name for entry in entries] == ["alpha", "zeta"]


def test_search_local_registry_matches_names_case_insensitively(tmp_path):
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
                    "checksum": "sha256:source",
                    "risk": "low",
                },
                {
                    "name": "inventory_report",
                    "version": "2.0.0",
                    "installed": False,
                    "path": "/tmp/inventory_report",
                    "checksum": "sha256:report",
                    "risk": "medium",
                },
                {
                    "name": "html_parser",
                    "version": "1.0.0",
                    "installed": False,
                    "path": "/tmp/html_parser",
                    "checksum": "sha256:parser",
                    "risk": "low",
                },
            ]
        ),
        encoding="utf-8",
    )

    entries = registry.search("INVENTORY")

    assert [entry.name for entry in entries] == [
        "inventory_report",
        "source_inventory",
    ]


def test_search_local_registry_is_empty_without_index(tmp_path):
    registry = Registry.local(tmp_path)

    assert registry.search("inventory") == []


def test_registry_delegates_index_loading_to_store():
    entry = RegistryEntry(
        name="source_inventory",
        version="1.0.0",
        installed=True,
        path="/tmp/source_inventory",
        checksum="sha256:abc123",
        risk="low",
    )

    class StubStore:
        def load(self):
            return [entry]

    registry = Registry(StubStore())

    assert registry.list_installed() == [entry]


def test_registry_store_loads_index_metadata(tmp_path):
    paths = LocalRegistryPaths.from_home(tmp_path)
    store = RegistryStore(paths)
    store.initialize()
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

    assert store.load()[0].name == "source_inventory"


def test_registry_inspect_returns_entry_and_manifest(tmp_path):
    registry = Registry.local(tmp_path)
    install_dir = registry.store.paths.installed / "source_inventory" / "1.0.0"
    install_dir.mkdir(parents=True)
    (install_dir / "canto.yaml").write_text(
        "name: source_inventory\nversion: 1.0.0\ndescription: Inventory sites.\n",
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

    capability = registry.inspect("source_inventory")

    assert capability.entry.path == str(install_dir)
    assert capability.manifest.description == "Inventory sites."


def test_registry_inspect_requires_version_when_ambiguous():
    entries = [
        RegistryEntry(
            name="source_inventory",
            version=version,
            installed=True,
            path=f"/tmp/source_inventory/{version}",
            checksum=f"sha256:{version}",
            risk="low",
        )
        for version in ("1.0.0", "2.0.0")
    ]

    class StubStore:
        def load(self):
            return entries

    with pytest.raises(ValueError, match="specify --version"):
        Registry(StubStore()).inspect("source_inventory")


def test_registry_remove_deletes_directory_and_index_entry(tmp_path):
    registry = Registry.local(tmp_path)
    install_dir = registry.store.paths.installed / "source_inventory" / "1.0.0"
    install_dir.mkdir(parents=True)
    (install_dir / "canto.yaml").write_text(
        "name: source_inventory\nversion: 1.0.0\n",
        encoding="utf-8",
    )
    entry = RegistryEntry(
        name="source_inventory",
        version="1.0.0",
        installed=True,
        path=str(install_dir),
        checksum="sha256:abc123",
        risk="low",
    )
    registry.store.save([entry])

    removed = registry.remove("source_inventory")

    assert removed == entry
    assert not install_dir.exists()
    assert registry.store.load() == []


def test_registry_remove_rejects_path_outside_installed_root(tmp_path):
    registry = Registry.local(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    registry.store.save(
        [
            RegistryEntry(
                name="source_inventory",
                version="1.0.0",
                installed=True,
                path=str(outside),
                checksum="sha256:abc123",
                risk="low",
            )
        ]
    )

    with pytest.raises(ValueError, match="outside registry root"):
        registry.remove("source_inventory")

    assert outside.is_dir()


def test_registry_validates_installed_manifest_and_checksum(tmp_path):
    registry = Registry.local(tmp_path)
    install_dir = registry.store.paths.installed / "source_inventory" / "1.0.0"
    install_dir.mkdir(parents=True)
    (install_dir / "canto.yaml").write_text(
        "name: source_inventory\nversion: 1.0.0\nrisk:\n  level: low\n",
        encoding="utf-8",
    )
    entry = RegistryEntry(
        name="source_inventory",
        version="1.0.0",
        installed=True,
        path=str(install_dir),
        checksum=registry.store.checksum_directory(install_dir),
        risk="low",
    )
    registry.store.save([entry])

    result = registry.validate_installed("source_inventory")

    assert result.valid is True
    assert result.errors == []


def test_registry_reports_installed_manifest_mismatch(tmp_path):
    registry = Registry.local(tmp_path)
    install_dir = registry.store.paths.installed / "source_inventory" / "1.0.0"
    install_dir.mkdir(parents=True)
    (install_dir / "canto.yaml").write_text(
        "name: other_capability\nversion: 2.0.0\nrisk:\n  level: high\n",
        encoding="utf-8",
    )
    registry.store.save(
        [
            RegistryEntry(
                name="source_inventory",
                version="1.0.0",
                installed=True,
                path=str(install_dir),
                checksum="sha256:wrong",
                risk="low",
            )
        ]
    )

    result = registry.validate_installed("source_inventory")

    assert result.valid is False
    assert any("manifest name" in error for error in result.errors)
    assert any("manifest version" in error for error in result.errors)
    assert any("manifest risk" in error for error in result.errors)
    assert any("checksum" in error for error in result.errors)


def test_registry_installs_local_capability_directory(tmp_path):
    registry = Registry.local(tmp_path / "home")
    source = tmp_path / "source"
    source.mkdir()
    (source / "canto.yaml").write_text(
        """\
name: source_inventory
version: 1.0.0
dependencies:
  python:
    - requests
risk:
  level: medium
""",
        encoding="utf-8",
    )
    (source / "README.md").write_text("Source inventory\n", encoding="utf-8")

    result = registry.install_directory(source)

    destination = registry.store.paths.installed / "source_inventory" / "1.0.0"
    assert result.entry.path == str(destination.resolve())
    assert result.entry.risk == "medium"
    assert result.dependencies == {"python": ["requests"]}
    assert (destination / "README.md").read_text(encoding="utf-8") == "Source inventory\n"
    assert registry.validate_installed("source_inventory").valid is True


def test_registry_rejects_missing_execution_provider_binding(tmp_path):
    registry = Registry.local(tmp_path / "home")
    source = tmp_path / "source"
    source.mkdir()
    (source / "canto.yaml").write_text(
        """\
name: source_inventory
version: 1.0.0
execution:
  providers:
    - skill: source_inventory
      provider: missing
""",
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match=r"Missing execution provider binding \(source_inventory, missing\)",
    ):
        registry.install_directory(source)


def test_registry_install_rejects_duplicate_version(tmp_path):
    registry = Registry.local(tmp_path / "home")
    source = tmp_path / "source"
    source.mkdir()
    (source / "canto.yaml").write_text(
        "name: source_inventory\nversion: 1.0.0\n",
        encoding="utf-8",
    )
    registry.install_directory(source)

    with pytest.raises(ValueError, match="already installed"):
        registry.install_directory(source)


def test_registry_install_rejects_archive_file(tmp_path):
    registry = Registry.local(tmp_path / "home")
    archive = tmp_path / "source_inventory.canto"
    archive.write_bytes(b"not-an-archive")

    with pytest.raises(ValueError, match="must be a local directory"):
        registry.install_directory(archive)


def test_registry_install_rejects_source_directory_symlink(tmp_path):
    registry = Registry.local(tmp_path / "home")
    source = tmp_path / "source"
    source.mkdir()
    (source / "canto.yaml").write_text(
        "name: source_inventory\nversion: 1.0.0\n",
        encoding="utf-8",
    )
    source_link = tmp_path / "source-link"
    source_link.symlink_to(source, target_is_directory=True)

    with pytest.raises(ValueError, match="is a symbolic link"):
        registry.install_directory(source_link)


def test_execution_roots_reject_tampered_installed_capability(tmp_path):
    registry = Registry.local(tmp_path / "home")
    source = tmp_path / "source"
    source.mkdir()
    (source / "canto.yaml").write_text(
        "name: source_inventory\nversion: 1.0.0\n",
        encoding="utf-8",
    )
    installed = registry.install_directory(source)
    (Path(installed.entry.path) / "tampered.py").write_text(
        "VALUE = 1\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="Installed capability is invalid"):
        registry.execution_roots()
