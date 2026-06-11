from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from canto.core.delegation import DelegationService
from canto.core.delegation_workspace import (
    DelegationWorkspaceService,
    WorkspaceError,
    inspect_repository,
)
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
    (root / "src" / "app.py").write_text("print('hello')\n")
    (root / "tests").mkdir()
    (root / "tests" / "test_app.py").write_text("def test_app(): pass\n")
    (root / "secrets").mkdir()
    (root / "secrets" / "token.txt").write_text("not-a-real-secret\n")
    git(root, "add", ".")
    git(root, "commit", "-m", "initial")
    return root


def assigned_service(repository: Path, tmp_path, *, allowed=None, denied=None):
    delegation = DelegationService(MemoryStateStore())
    task = DelegationTask(
        task_id="task_1",
        title="Scoped task",
        repository=inspect_repository(repository),
        scope=DelegationScope(
            allowed_paths=allowed or ["src", "tests"],
            denied_paths=denied or ["secrets"],
        ),
    )
    delegation.create_task(task)
    delegation.transition("task_1", "assigned", updates={"executor_id": "manual"})
    return delegation, DelegationWorkspaceService(delegation, tmp_path / "delegations")


def test_prepare_creates_sparse_worktree_and_durable_record(repository, tmp_path):
    delegation, workspaces = assigned_service(repository, tmp_path)

    workspace = workspaces.prepare("task_1")

    path = Path(workspace.path)
    assert (path / "src" / "app.py").is_file()
    assert (path / "tests" / "test_app.py").is_file()
    assert not (path / "secrets").exists()
    assert delegation.get_task("task_1").status == "workspace_ready"
    assert workspaces.inspect("task_1")["head"] == workspace.base_commit


def test_prepare_rejects_overlapping_denied_path(repository, tmp_path):
    _, workspaces = assigned_service(
        repository, tmp_path, allowed=["src"], denied=["src/private"]
    )

    with pytest.raises(WorkspaceError, match="overlap"):
        workspaces.prepare("task_1")


def test_prepare_rejects_stale_repository_identity(repository, tmp_path):
    _, workspaces = assigned_service(repository, tmp_path)
    (repository / "README.md").write_text("changed\n")
    git(repository, "add", "README.md")
    git(repository, "commit", "-m", "advance")

    with pytest.raises(WorkspaceError, match="HEAD changed"):
        workspaces.prepare("task_1")


def test_remove_deletes_only_managed_worktree(repository, tmp_path):
    _, workspaces = assigned_service(repository, tmp_path)
    workspace = workspaces.prepare("task_1")

    removed = workspaces.remove("task_1")

    assert removed.status == "removed"
    assert not Path(workspace.path).exists()
    assert repository.exists()
