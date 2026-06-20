from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

import canto.cli as cli_module
from canto.core.local_registry import LocalRegistryError, LocalRegistryPaths, Registry
from canto.core.repository import (
    CANTO_AGENTS_MARKER_START,
    RepositoryConfigError,
    doctor_repository,
    find_repository,
    initialize_repository,
    load_repository,
    load_repository_worker_policy,
)
from canto.core.delegation import DelegationService
from canto.core.delegation_workspace import DelegationWorkspaceService, inspect_repository
from canto.core.state import MemoryStateStore
from canto.models.delegation import DelegationScope, DelegationTask


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
    assert (repository / ".canto" / "delegate.toml").is_file()
    assert (repository / ".canto" / "workers.toml").is_file()
    assert (repository / ".canto" / "agents" / "shared.md").is_file()
    assert (repository / ".canto" / "agents" / "orchestrator.md").is_file()
    assert (repository / ".canto" / "agents" / "executor.md").is_file()
    assert CANTO_AGENTS_MARKER_START in (repository / "AGENTS.md").read_text()
    assert "Developer sessions" in (repository / "AGENTS.md").read_text()
    assert "# Canto Developer Instructions" in (
        repository / ".canto" / "agents" / "orchestrator.md"
    ).read_text()
    assert "# Canto Delegated Worker Instructions" in (
        repository / ".canto" / "agents" / "executor.md"
    ).read_text()
    content = (repository / ".canto" / "repo.toml").read_text()
    assert "credential" not in content
    assert "task" not in content
    assert load_repository(repository).repo_id == config.repo_id
    worker_policy = load_repository_worker_policy(repository)
    assert worker_policy.cloud_allowed is False
    assert worker_policy.allowed_transports == []
    assert worker_policy.allowed_cli_profiles == []
    assert worker_policy.api_fallback_requires_approval is True
    assert worker_policy.orchestrator_provider == ""


def test_repository_worker_policy_can_explicitly_allow_cli_transport(repository):
    initialize_repository(repository)
    (repository / ".canto" / "workers.toml").write_text(
        """\
version = 1

[selection]
allowed_transports = ["cli"]
allowed_cli_profiles = ["codex-subscription"]
preferred_cli_profiles = ["codex-subscription"]
prefer_subscription_cli = true
""",
        encoding="utf-8",
    )

    policy = load_repository_worker_policy(repository)

    assert policy.allowed_transports == ["cli"]
    assert policy.allowed_cli_profiles == ["codex-subscription"]
    assert policy.preferred_cli_profiles == ["codex-subscription"]
    assert policy.prefer_subscription_cli is True


def test_repo_init_preserves_existing_agents_content_and_is_idempotent(repository):
    original = "# Human Instructions\n\nKeep this section unchanged.\n"
    (repository / "AGENTS.md").write_text(original)

    first = initialize_repository(repository)
    once = (repository / "AGENTS.md").read_text()
    second = initialize_repository(repository)

    assert once.startswith(original)
    assert once.count(CANTO_AGENTS_MARKER_START) == 1
    assert (repository / "AGENTS.md").read_text() == once
    assert second.repo_id == first.repo_id


def test_repo_init_refreshes_only_canto_owned_agents_section(repository):
    human_prefix = "# Human Instructions\n\nKeep before.\n\n"
    human_suffix = "\n\nKeep after.\n"
    (repository / "AGENTS.md").write_text(
        human_prefix
        + CANTO_AGENTS_MARKER_START
        + "\nOld generated guidance.\n"
        + "<!-- canto-agent-instructions:end -->"
        + human_suffix
    )

    initialize_repository(repository)
    content = (repository / "AGENTS.md").read_text()

    assert content.startswith(human_prefix)
    assert content.endswith(human_suffix)
    assert "Old generated guidance" not in content
    assert "Do not bypass Canto assignment" in content


def test_repo_init_upgrades_existing_bootstrap_with_agent_files(repository):
    config = initialize_repository(repository)
    (repository / ".canto" / "delegate.toml").unlink()
    (repository / ".canto" / "agents" / "executor.md").unlink()
    (repository / "AGENTS.md").unlink()

    upgraded = initialize_repository(repository)

    assert upgraded.repo_id == config.repo_id
    assert (repository / ".canto" / "delegate.toml").is_file()
    assert (repository / ".canto" / "agents" / "executor.md").is_file()
    assert (repository / "AGENTS.md").is_file()


def test_repo_init_refreshes_canto_owned_role_manuals(repository):
    initialize_repository(repository)
    developer_manual = repository / ".canto" / "agents" / "orchestrator.md"
    worker_manual = repository / ".canto" / "agents" / "executor.md"
    developer_manual.write_text("Old orchestrator language.\n")
    worker_manual.write_text("Old executor language.\n")

    initialize_repository(repository)

    assert "# Canto Developer Instructions" in developer_manual.read_text()
    assert "Authorize Canto to Apply" in developer_manual.read_text()
    assert "`canto delegate launch-ai TASK_ID`" in developer_manual.read_text()
    assert "explicitly allows CLI transport" in developer_manual.read_text()
    assert "`canto delegate wait TASK_ID`" in developer_manual.read_text()
    assert "# Canto Delegated Worker Instructions" in worker_manual.read_text()
    assert "Do not self-assign" in worker_manual.read_text()


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


def test_repo_doctor_requires_instruction_files_in_git_base(repository, monkeypatch):
    initialize_repository(repository)
    before = doctor_repository(repository)
    assert before.valid is False
    assert next(
        item for item in before.checks if item.name == "instruction_files_git_state"
    ).valid is False

    git(repository, "add", "AGENTS.md", ".canto")
    git(repository, "commit", "-m", "Bootstrap Canto agent instructions")
    after = doctor_repository(repository)
    assert after.valid is True

    monkeypatch.chdir(repository / "src")
    result = CliRunner().invoke(cli_module.app, ["repo", "doctor", "--json"])
    assert result.exit_code == 0, result.output
    assert '"valid": true' in result.output


def test_repo_doctor_reports_unavailable_ai_state_without_traceback(
    repository, monkeypatch
):
    initialize_repository(repository)
    git(repository, "add", "AGENTS.md", ".canto")
    git(repository, "commit", "-m", "Bootstrap Canto agent instructions")

    class BrokenStore:
        def list_ai_records(self, record_type):
            raise sqlite3.OperationalError("read-only state unavailable")

    monkeypatch.setattr(cli_module, "_ai_readiness_store", lambda: BrokenStore())
    result = CliRunner().invoke(
        cli_module.app, ["repo", "doctor", "--repository", str(repository)]
    )

    assert result.exit_code == 0
    assert "WARN ai_worker_state: global AI state is unavailable" in result.output
    assert "Traceback" not in result.output


def test_delegated_sparse_workspace_includes_committed_role_instructions(repository, tmp_path):
    initialize_repository(repository)
    git(repository, "add", "AGENTS.md", ".canto")
    git(repository, "commit", "-m", "Bootstrap Canto agent instructions")
    service = DelegationService(MemoryStateStore())
    service.create_task(
        DelegationTask(
            task_id="task_instructions",
            title="Instruction visibility",
            repository=inspect_repository(repository),
            scope=DelegationScope(allowed_paths=["src"]),
        )
    )
    service.transition("task_instructions", "assigned", updates={"executor_id": "manual"})
    workspace = DelegationWorkspaceService(service, tmp_path / "delegations").prepare(
        "task_instructions"
    )
    root = Path(workspace.path)
    assert (root / "AGENTS.md").is_file()
    assert (root / ".canto" / "agents" / "shared.md").is_file()
    assert (root / ".canto" / "agents" / "executor.md").is_file()


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
