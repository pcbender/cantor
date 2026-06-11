from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from canto.core.delegation import DelegationService
from canto.core.delegation_executor import CodexCliExecutor, ExecutorError
from canto.core.delegation_workspace import DelegationWorkspaceService, inspect_repository
from canto.core.state import MemoryStateStore
from canto.models.delegation import (
    DelegationScope,
    DelegationTask,
    ExecutorProfile,
)


def git(repository: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repository), *args], check=True, capture_output=True)


def prepared_task(tmp_path, executable: Path):
    repository = tmp_path / "repository"
    repository.mkdir()
    git(repository, "init")
    git(repository, "config", "user.email", "test@example.com")
    git(repository, "config", "user.name", "Test User")
    (repository / "src").mkdir()
    (repository / "src" / "app.py").write_text("value = 1\n")
    git(repository, "add", ".")
    git(repository, "commit", "-m", "initial")

    service = DelegationService(MemoryStateStore())
    workspaces = DelegationWorkspaceService(service, tmp_path / "delegations")
    profile = ExecutorProfile(
        executor_id="codex_test",
        name="Codex test",
        harness="codex_cli",
        executable=str(executable),
        launch_mode="canto",
        permissions={"command_enforcement": "canto_observed"},
    )
    service.set_executor_profile(profile)
    service.create_task(
        DelegationTask(
            task_id="task_1",
            title="Update app",
            instructions="Change the fixture value.",
            repository=inspect_repository(repository),
            scope=DelegationScope(allowed_paths=["src"]),
        )
    )
    service.transition("task_1", "assigned", updates={"executor_id": profile.executor_id})
    workspaces.prepare("task_1")
    return service, workspaces


def test_codex_cli_launch_is_supervised_and_records_provenance(tmp_path):
    executable = tmp_path / "codex"
    executable.write_text(
        "#!/bin/sh\n"
        "cat >/dev/null\n"
        "printf 'value = 2\\n' > src/app.py\n"
        "printf 'executor complete\\n'\n"
    )
    executable.chmod(0o755)
    service, workspaces = prepared_task(tmp_path, executable)

    launch = CodexCliExecutor(service, workspaces, timeout_seconds=10).launch("task_1")

    assert launch.exit_code == 0
    assert launch.argv[1:4] == ["exec", "--sandbox", "workspace-write"]
    assert Path(launch.stdout_path).read_text() == "executor complete\n"
    assert Path(workspaces.get("task_1").path, "src", "app.py").read_text() == "value = 2\n"
    assert service.get_task("task_1").status == "executor_done"
    assert service.get_records("task_1", "sessions")[0]["enforcement"] == "canto_observed"


def test_codex_cli_profile_requires_available_executable(tmp_path):
    profile = ExecutorProfile(
        executor_id="missing",
        name="Missing",
        harness="codex_cli",
        executable=str(tmp_path / "missing-codex"),
        launch_mode="canto",
    )

    with pytest.raises(ExecutorError, match="unavailable"):
        CodexCliExecutor.available(profile)
