from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path

from typer.testing import CliRunner

import canto.cli as cli_module
from canto.core.delegation import DelegationService
from canto.core.executor_profiles import ExecutorProfileManager
from canto.core.delegation_workspace import (
    DelegationWorkspaceService,
    inspect_repository,
)
from canto.core.state import SqliteStateStore
from canto.core.repository import initialize_repository
from canto.models.delegation import (
    DelegationScope,
    DelegationTask,
    ExecutorProfile,
    RepositoryIdentity,
)


def git(repository: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repository), *args], capture_output=True, check=True
    )


def test_manual_delegation_cli_workflow(tmp_path, monkeypatch):
    repository = tmp_path / "repository"
    repository.mkdir()
    git(repository, "init")
    git(repository, "config", "user.email", "test@example.com")
    git(repository, "config", "user.name", "Test User")
    (repository / "src").mkdir()
    (repository / "src" / "app.py").write_text("value = 1\n")
    (repository / "private").mkdir()
    (repository / "private" / "secret.txt").write_text("fixture\n")
    git(repository, "add", ".")
    git(repository, "commit", "-m", "initial")
    initialize_repository(repository)

    store = SqliteStateStore(tmp_path / "state" / "canto.db")
    service = DelegationService(store)
    workspaces = DelegationWorkspaceService(service, tmp_path / "delegations")
    monkeypatch.setattr(
        cli_module, "_delegation_runtime", lambda: (service, workspaces)
    )
    runner = CliRunner()

    created = runner.invoke(
        cli_module.app,
        [
            "delegate",
            "create",
            "Update app",
            "--repo",
            str(repository),
            "--allow",
            "src",
            "--deny",
            "private",
            "--instruction",
            "Change only src/app.py",
        ],
    )
    assert created.exit_code == 0, created.output
    task_id = json.loads(created.output)["task_id"]

    for args in (
        ["delegate", "assign", task_id, "--executor", "manual-reviewer"],
        ["delegate", "prepare", task_id],
        ["delegate", "start", task_id],
        ["delegate", "message", task_id, "Implementation underway"],
        ["delegate", "block", task_id, "Need a decision"],
        ["delegate", "resume", task_id],
        ["delegate", "done", task_id, "--summary", "Implementation complete"],
    ):
        result = runner.invoke(cli_module.app, args)
        assert result.exit_code == 0, result.output

    shown = runner.invoke(cli_module.app, ["delegate", "show", task_id])
    value = json.loads(shown.output)
    assert value["status"] == "executor_done"
    assert value["sessions"][0]["enforcement"] == "manual_unverified"
    assert [message["kind"] for message in value["messages"]] == [
        "assignment",
        "progress",
        "blocker",
        "done",
    ]


def test_launch_ai_missing_task_reports_clean_cli_error(tmp_path, monkeypatch):
    service = DelegationService(SqliteStateStore(tmp_path / "state" / "canto.db"))
    workspaces = DelegationWorkspaceService(service, tmp_path / "delegations")
    monkeypatch.setattr(
        cli_module, "_delegation_runtime", lambda: (service, workspaces)
    )

    result = CliRunner().invoke(
        cli_module.app, ["delegate", "launch-ai", "missing-task", "--allow-cloud"]
    )

    assert result.exit_code == 1
    assert "Error: Delegation task not found: missing-task" in result.output
    assert "Traceback" not in result.output


def test_delegate_create_accepts_task_allowed_commands(tmp_path, monkeypatch):
    repository = tmp_path / "repository"
    repository.mkdir()
    git(repository, "init")
    git(repository, "config", "user.email", "test@example.com")
    git(repository, "config", "user.name", "Test User")
    (repository / "docs").mkdir()
    (repository / "docs" / "index.md").write_text("fixture\n")
    git(repository, "add", ".")
    git(repository, "commit", "-m", "initial")
    initialize_repository(repository)
    service = DelegationService(SqliteStateStore(tmp_path / "state" / "canto.db"))
    workspaces = DelegationWorkspaceService(service, tmp_path / "delegations")
    monkeypatch.setattr(
        cli_module, "_delegation_runtime", lambda: (service, workspaces)
    )

    result = CliRunner().invoke(
        cli_module.app,
        [
            "delegate",
            "create",
            "Memory command smoke",
            "--repository",
            str(repository),
            "--allow",
            "docs",
            "--allow-command",
            "/home/mrose/canto/.venv/bin/canto memory recall",
            "--allow-command",
            "/home/mrose/canto/.venv/bin/canto memory propose",
        ],
    )

    assert result.exit_code == 0, result.output
    scope = json.loads(result.output)["scope"]
    assert scope["allowed_commands"] == [
        "/home/mrose/canto/.venv/bin/canto memory propose",
        "/home/mrose/canto/.venv/bin/canto memory recall",
    ]


def test_launch_ai_uses_explicitly_allowed_cli_profile(tmp_path, monkeypatch):
    repository = tmp_path / "repository"
    repository.mkdir()
    git(repository, "init")
    git(repository, "config", "user.email", "test@example.com")
    git(repository, "config", "user.name", "Test User")
    (repository / "src").mkdir()
    (repository / "src" / "app.py").write_text("value = 1\n")
    git(repository, "add", ".")
    git(repository, "commit", "-m", "initial")
    initialize_repository(repository)
    (repository / ".canto" / "workers.toml").write_text(
        """\
version = 1

[selection]
allowed_transports = ["cli"]
allowed_cli_profiles = ["local-codex"]
preferred_cli_profiles = ["local-codex"]
""",
        encoding="utf-8",
    )
    executable = tmp_path / "codex"
    executable.write_text(
        "#!/bin/sh\n"
        "cat >/dev/null\n"
        "printf 'value = 2\\n' > src/app.py\n"
        "printf 'cli worker complete\\n'\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    service = DelegationService(SqliteStateStore(tmp_path / "state" / "canto.db"))
    workspaces = DelegationWorkspaceService(service, tmp_path / "delegations")
    service.set_executor_profile(
        ExecutorProfile(
            executor_id="local-codex",
            name="Local Codex",
            harness="codex_cli",
            executable=str(executable),
            model_provider="ollama",
            launch_mode="canto",
        )
    )
    service.create_task(
        DelegationTask(
            task_id="task_cli",
            title="Use CLI",
            repository=inspect_repository(repository),
            scope=DelegationScope(allowed_paths=["src"]),
            instructions="Change src/app.py",
        )
    )
    service.transition("task_cli", "assigned")
    workspaces.prepare("task_cli")
    monkeypatch.setattr(
        cli_module, "_delegation_runtime", lambda: (service, workspaces)
    )

    def api_assignment_should_not_run():
        raise AssertionError("API Worker assignment should not run")

    monkeypatch.setattr(
        cli_module, "_ai_assignment_service", api_assignment_should_not_run
    )

    result = CliRunner().invoke(cli_module.app, ["delegate", "launch-ai", "task_cli"])

    assert result.exit_code == 0, result.output
    launch = json.loads(result.output)
    assert launch["executor_id"] == "local-codex"
    assert launch["outcome"] == "completed_work"
    assert service.get_task("task_cli").selected_model_key == "cli:local-codex"


def test_launch_ai_profile_option_forces_one_cli_profile(tmp_path, monkeypatch):
    repository = tmp_path / "repository"
    repository.mkdir()
    git(repository, "init")
    git(repository, "config", "user.email", "test@example.com")
    git(repository, "config", "user.name", "Test User")
    (repository / "src").mkdir()
    (repository / "src" / "app.py").write_text("value = 1\n")
    git(repository, "add", ".")
    git(repository, "commit", "-m", "initial")
    initialize_repository(repository)
    (repository / ".canto" / "workers.toml").write_text(
        """\
version = 1

[selection]
allowed_transports = ["cli", "http"]
""",
        encoding="utf-8",
    )
    executable = tmp_path / "codex"
    executable.write_text(
        "#!/bin/sh\n"
        "cat >/dev/null\n"
        "printf 'value = 5\\n' > src/app.py\n"
        "printf 'forced profile complete\\n'\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    service = DelegationService(SqliteStateStore(tmp_path / "state" / "canto.db"))
    workspaces = DelegationWorkspaceService(service, tmp_path / "delegations")
    service.set_executor_profile(
        ExecutorProfile(
            executor_id="forced-codex",
            name="Forced Codex",
            harness="codex_cli",
            executable=str(executable),
            model_provider="ollama",
            launch_mode="canto",
        )
    )
    service.create_task(
        DelegationTask(
            task_id="task_forced_cli",
            title="Use forced CLI",
            repository=inspect_repository(repository),
            scope=DelegationScope(allowed_paths=["src"]),
            instructions="Change src/app.py",
        )
    )
    service.transition("task_forced_cli", "assigned")
    workspaces.prepare("task_forced_cli")
    monkeypatch.setattr(
        cli_module, "_delegation_runtime", lambda: (service, workspaces)
    )

    result = CliRunner().invoke(
        cli_module.app,
        ["delegate", "launch-ai", "task_forced_cli", "--profile", "forced-codex"],
    )

    assert result.exit_code == 0, result.output
    launch = json.loads(result.output)
    assert launch["executor_id"] == "forced-codex"
    assert service.get_task("task_forced_cli").selected_model_key == "cli:forced-codex"


def test_launch_ai_profile_option_respects_repository_profile_allowlist(
    tmp_path, monkeypatch
):
    repository = tmp_path / "repository"
    repository.mkdir()
    git(repository, "init")
    git(repository, "config", "user.email", "test@example.com")
    git(repository, "config", "user.name", "Test User")
    (repository / "src").mkdir()
    (repository / "src" / "app.py").write_text("value = 1\n")
    git(repository, "add", ".")
    git(repository, "commit", "-m", "initial")
    initialize_repository(repository)
    (repository / ".canto" / "workers.toml").write_text(
        """\
version = 1

[selection]
allowed_transports = ["cli"]
allowed_cli_profiles = ["allowed-codex"]
""",
        encoding="utf-8",
    )
    service = DelegationService(SqliteStateStore(tmp_path / "state" / "canto.db"))
    workspaces = DelegationWorkspaceService(service, tmp_path / "delegations")
    service.set_executor_profile(
        ExecutorProfile(
            executor_id="blocked-codex",
            name="Blocked Codex",
            harness="codex_cli",
            executable=str(tmp_path / "codex"),
            model_provider="ollama",
            launch_mode="canto",
        )
    )
    service.create_task(
        DelegationTask(
            task_id="task_blocked_cli",
            title="Use blocked CLI",
            repository=inspect_repository(repository),
            scope=DelegationScope(allowed_paths=["src"]),
        )
    )
    service.transition("task_blocked_cli", "assigned")
    workspaces.prepare("task_blocked_cli")
    monkeypatch.setattr(
        cli_module, "_delegation_runtime", lambda: (service, workspaces)
    )

    result = CliRunner().invoke(
        cli_module.app,
        ["delegate", "launch-ai", "task_blocked_cli", "--profile", "blocked-codex"],
    )

    assert result.exit_code == 1
    assert "not allowed by repository Worker policy" in result.output


def test_launch_ai_balanced_cli_exhaustion_requires_approval_before_api(tmp_path, monkeypatch):
    repository = tmp_path / "repository"
    repository.mkdir()
    git(repository, "init")
    git(repository, "config", "user.email", "test@example.com")
    git(repository, "config", "user.name", "Test User")
    (repository / "src").mkdir()
    (repository / "src" / "app.py").write_text("value = 1\n")
    git(repository, "add", ".")
    git(repository, "commit", "-m", "initial")
    initialize_repository(repository)
    (repository / ".canto" / "workers.toml").write_text(
        """\
version = 1

[selection]
priority = "balanced"
allowed_transports = ["cli", "http"]
allowed_cli_profiles = ["missing-profile"]
""",
        encoding="utf-8",
    )
    service = DelegationService(SqliteStateStore(tmp_path / "state" / "canto.db"))
    workspaces = DelegationWorkspaceService(service, tmp_path / "delegations")
    service.create_task(
        DelegationTask(
            task_id="task_cli_spill",
            title="Use CLI",
            repository=inspect_repository(repository),
            scope=DelegationScope(allowed_paths=["src"]),
        )
    )
    service.transition("task_cli_spill", "assigned")
    workspaces.prepare("task_cli_spill")
    monkeypatch.setattr(
        cli_module, "_delegation_runtime", lambda: (service, workspaces)
    )

    def api_assignment_should_not_run():
        raise AssertionError("API Worker assignment should not run without approval")

    monkeypatch.setattr(
        cli_module, "_ai_assignment_service", api_assignment_should_not_run
    )

    result = CliRunner().invoke(
        cli_module.app, ["delegate", "launch-ai", "task_cli_spill"]
    )

    assert result.exit_code == 1
    assert "API Worker fallback requires approval" in result.output


def test_assign_accepts_registered_codex_profile(tmp_path, monkeypatch):
    service = DelegationService(SqliteStateStore(tmp_path / "state" / "canto.db"))
    workspaces = DelegationWorkspaceService(service, tmp_path / "delegations")
    service.set_executor_profile(
        ExecutorProfile(
            executor_id="cloud-codex",
            name="Cloud Codex",
            harness="codex_cli",
            executable="codex",
            model="gpt-5.4-mini",
            launch_mode="canto",
        )
    )
    service.create_task(
        DelegationTask(
            task_id="task_codex",
            title="Assign Codex",
            repository=RepositoryIdentity(canonical_path="/repository"),
        )
    )
    monkeypatch.setattr(
        cli_module, "_delegation_runtime", lambda: (service, workspaces)
    )

    result = CliRunner().invoke(
        cli_module.app,
        ["delegate", "assign", "task_codex", "--executor", "cloud-codex"],
    )

    assert result.exit_code == 0, result.output
    assert service.get_task("task_codex").executor_id == "cloud-codex"
    assert service.get_task("task_codex").status == "assigned"


def test_delegate_profile_pool_cli_save_show_and_list(tmp_path, monkeypatch):
    service = DelegationService(SqliteStateStore(tmp_path / "state" / "canto.db"))
    manager = ExecutorProfileManager(service, tmp_path / "config" / "executors.yaml")
    service.set_executor_profile(
        ExecutorProfile(
            executor_id="cloud-codex",
            name="Cloud Codex",
            harness="codex_cli",
            executable="codex",
            launch_mode="canto",
        )
    )
    monkeypatch.setattr(cli_module, "_profile_manager", lambda: manager)
    runner = CliRunner()

    saved = runner.invoke(
        cli_module.app,
        [
            "delegate",
            "profile",
            "pool",
            "save",
            "subscription",
            "--profile",
            "cloud-codex",
        ],
    )
    shown = runner.invoke(
        cli_module.app, ["delegate", "profile", "pool", "show", "subscription"]
    )
    listed = runner.invoke(cli_module.app, ["delegate", "profile", "pool", "list"])

    assert saved.exit_code == 0, saved.output
    assert json.loads(saved.output)["profiles"] == ["cloud-codex"]
    assert json.loads(shown.output)["profiles"] == ["cloud-codex"]
    assert json.loads(listed.output) == {"subscription": ["cloud-codex"]}


def test_delegate_pool_reports_read_only_state_error_without_traceback(monkeypatch):
    def unavailable_runtime(*, read_only=False):
        assert read_only is True
        raise sqlite3.OperationalError("attempt to write a readonly database")

    monkeypatch.setattr(cli_module, "_delegation_runtime", unavailable_runtime)

    result = CliRunner().invoke(cli_module.app, ["delegate", "pool"])

    assert result.exit_code == 1
    assert "Cannot read Canto state for delegate pool" in result.output
    assert "Traceback" not in result.output


def test_delegate_status_uses_read_only_state(tmp_path, monkeypatch):
    state_path = tmp_path / "state" / "canto.db"
    writable = SqliteStateStore(state_path)
    service = DelegationService(writable)
    workspaces = DelegationWorkspaceService(service, tmp_path / "delegations")
    calls = []

    def runtime(*, read_only=False):
        calls.append(read_only)
        return service, workspaces

    monkeypatch.setattr(cli_module, "_delegation_runtime", runtime)

    result = CliRunner().invoke(cli_module.app, ["delegate", "status"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == []
    assert calls == [True]


def test_delegate_revise_recovers_executor_done_task_without_result(tmp_path, monkeypatch):
    service = DelegationService(SqliteStateStore(tmp_path / "state" / "canto.db"))
    workspaces = DelegationWorkspaceService(service, tmp_path / "delegations")
    service.create_task(
        DelegationTask(
            task_id="task_empty",
            title="Empty Worker result",
            repository=RepositoryIdentity(canonical_path="/repository"),
        )
    )
    service.store.set_delegation_task(
        "task_empty",
        {
            **service.get_task("task_empty").model_dump(mode="json"),
            "status": "executor_done",
        },
    )
    monkeypatch.setattr(
        cli_module, "_delegation_runtime", lambda: (service, workspaces)
    )

    result = CliRunner().invoke(
        cli_module.app,
        [
            "delegate",
            "revise",
            "task_empty",
            "--note",
            "Make a concrete repository change.",
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["result_revision"] is None
    assert service.get_task("task_empty").status == "revision_requested"


def test_delegate_wait_returns_when_worker_finishes(tmp_path, monkeypatch):
    service = DelegationService(SqliteStateStore(tmp_path / "state" / "canto.db"))
    workspaces = DelegationWorkspaceService(service, tmp_path / "delegations")
    service.create_task(
        DelegationTask(
            task_id="task_wait",
            title="Wait for Worker",
            repository=RepositoryIdentity(canonical_path="/repository"),
        )
    )
    service.store.set_delegation_task(
        "task_wait",
        {
            **service.get_task("task_wait").model_dump(mode="json"),
            "status": "executor_working",
        },
    )
    monkeypatch.setattr(
        cli_module,
        "_delegation_runtime",
        lambda *, read_only=False: (service, workspaces),
    )

    def finish(_seconds):
        service.transition("task_wait", "executor_done")

    monkeypatch.setattr(cli_module.time, "sleep", finish)

    result = CliRunner().invoke(
        cli_module.app,
        ["delegate", "wait", "task_wait", "--timeout", "5", "--interval", "1"],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["status"] == "executor_done"


def test_delegate_wait_times_out_with_current_status(tmp_path, monkeypatch):
    service = DelegationService(SqliteStateStore(tmp_path / "state" / "canto.db"))
    workspaces = DelegationWorkspaceService(service, tmp_path / "delegations")
    service.create_task(
        DelegationTask(
            task_id="task_wait",
            title="Wait for Worker",
            repository=RepositoryIdentity(canonical_path="/repository"),
        )
    )
    service.store.set_delegation_task(
        "task_wait",
        {
            **service.get_task("task_wait").model_dump(mode="json"),
            "status": "executor_working",
        },
    )
    monkeypatch.setattr(
        cli_module,
        "_delegation_runtime",
        lambda *, read_only=False: (service, workspaces),
    )
    monotonic_values = iter((0.0, 1.0))
    monkeypatch.setattr(cli_module.time, "monotonic", lambda: next(monotonic_values))

    result = CliRunner().invoke(
        cli_module.app,
        ["delegate", "wait", "task_wait", "--timeout", "0.5"],
    )

    assert result.exit_code == 1
    assert "current status is executor_working" in result.output
