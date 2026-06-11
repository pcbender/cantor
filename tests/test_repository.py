from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

import canto.cli as cli_module
from canto.core.local_registry import LocalRegistryError, LocalRegistryPaths, Registry
from canto.core.repository import (
    RepositoryConfigError,
    find_repository,
    initialize_repository,
    load_repository,
)


def git(repository: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repository), *args],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()


@pytest.fixture
def repository(tmp_path):
    root = tmp_path / "repository"
    root.mkdir()
    git(root, "init")
    git(root, "config", "user.email", "test@example.com")
    git(root, "config", "user.name", "Test User")
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text("value = 1\n")
    git(root, "add", ".")
    git(root, "commit", "-m", "initial")
    return root


def test_repo_init_creates_non_secret_repo_configuration(repository):
    config = initialize_repository(repository)

    assert config.repo_id.startswith("repo_")
    assert (repository / ".canto" / "repo.toml").is_file()
    assert (repository / ".canto" / "policy.toml").is_file()
    content = (repository / ".canto" / "repo.toml").read_text()
    assert "credential" not in content
    assert "task" not in content
    assert load_repository(repository).repo_id == config.repo_id


def test_repo_resolution_searches_from_nested_directory(repository):
    config = initialize_repository(repository)
    nested = repository / "src" / "nested"
    nested.mkdir()

    assert find_repository(nested) == repository
    assert load_repository(nested).repo_id == config.repo_id


def test_uninitialized_repo_has_clear_bootstrap_message(repository):
    with pytest.raises(RepositoryConfigError, match="canto repo init"):
        load_repository(repository)


def test_repo_init_requires_initial_commit(tmp_path):
    repository = tmp_path / "empty"
    repository.mkdir()
    git(repository, "init")

    with pytest.raises(RepositoryConfigError, match="rev-parse HEAD"):
        initialize_repository(repository)


def test_repo_identity_rejects_moved_repository(repository, tmp_path):
    initialize_repository(repository)
    moved = tmp_path / "moved"
    repository.rename(moved)

    with pytest.raises(RepositoryConfigError, match="path changed"):
        load_repository(moved)


def test_repo_cli_init_and_show_from_nested_directory(repository, monkeypatch):
    monkeypatch.chdir(repository)
    runner = CliRunner()

    initialized = runner.invoke(cli_module.app, ["repo", "init"])
    monkeypatch.chdir(repository / "src")
    shown = runner.invoke(cli_module.app, ["repo", "show"])

    assert initialized.exit_code == 0, initialized.output
    assert shown.exit_code == 0, shown.output
    assert '"repo_id": "repo_' in shown.output


def test_delegate_create_requires_bootstrap(repository, tmp_path, monkeypatch):
    registry = Registry.local(tmp_path / "home")
    monkeypatch.setattr(cli_module, "_capability_registry", lambda: registry)

    result = CliRunner().invoke(
        cli_module.app,
        ["delegate", "create", "Task", "--repo", str(repository), "--allow", "src"],
    )

    assert result.exit_code == 1
    assert "canto repo init" in result.output


def test_global_state_migrates_legacy_sqlite(tmp_path):
    paths = LocalRegistryPaths.from_home(tmp_path)
    paths.legacy_state_file.parent.mkdir(parents=True)
    with sqlite3.connect(paths.legacy_state_file) as connection:
        connection.execute("CREATE TABLE marker(value TEXT)")
        connection.execute("INSERT INTO marker VALUES ('preserved')")

    paths.create()

    assert paths.state_file.is_file()
    assert not paths.legacy_state_file.exists()
    with sqlite3.connect(paths.state_file) as connection:
        assert connection.execute("SELECT value FROM marker").fetchone() == (
            "preserved",
        )


def test_global_state_refuses_ambiguous_legacy_and_current_files(tmp_path):
    paths = LocalRegistryPaths.from_home(tmp_path)
    paths.legacy_state_file.parent.mkdir(parents=True)
    paths.legacy_state_file.touch()
    paths.state_file.parent.mkdir(parents=True, exist_ok=True)
    paths.state_file.touch()

    with pytest.raises(LocalRegistryError, match="Both legacy and current"):
        paths.create()


def test_canto_home_environment_is_global_root(tmp_path, monkeypatch):
    root = tmp_path / "custom-canto"
    monkeypatch.setenv("CANTO_HOME", str(root))

    assert LocalRegistryPaths.from_home().root == root
