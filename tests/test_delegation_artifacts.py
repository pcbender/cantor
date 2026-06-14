from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from canto.core.delegation import DelegationService
from canto.core.delegation_artifacts import ArtifactCaptureError, DelegationArtifactService
from canto.core.delegation_workspace import DelegationWorkspaceService, inspect_repository
from canto.core.state import MemoryStateStore
from canto.models.delegation import DelegationScope, DelegationTask


def git(repository: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repository), *args], check=True, capture_output=True)


def executor_done(tmp_path):
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
    service = DelegationService(MemoryStateStore())
    workspaces = DelegationWorkspaceService(service, tmp_path / "delegations")
    service.create_task(
        DelegationTask(
            task_id="task_1",
            title="Update app",
            repository=inspect_repository(repository),
            scope=DelegationScope(allowed_paths=["src"], denied_paths=["private"]),
        )
    )
    service.transition("task_1", "assigned", updates={"executor_id": "manual"})
    workspace = workspaces.prepare("task_1")
    service.transition("task_1", "executor_working")
    service.transition("task_1", "executor_done")
    return service, workspaces, Path(workspace.path)


def test_capture_creates_immutable_hashed_result_revision(tmp_path):
    service, workspaces, workspace = executor_done(tmp_path)
    (workspace / "src" / "app.py").write_text("value = 2\n")
    (workspace / "src" / "new.py").write_text("created = True\n")

    result = DelegationArtifactService(service, workspaces).capture("task_1")

    assert result.revision == 1
    assert [artifact.name for artifact in result.artifacts] == [
        "proposal.diff",
        "changed_files.json",
        "commands.log",
        "summary.md",
    ]
    artifact_root = workspace.parent / "artifacts"
    for artifact in result.artifacts:
        assert len(artifact.sha256) == 64
        assert (artifact_root / artifact.relative_path).is_file()
    changed = json.loads((artifact_root / "revision-1" / "changed_files.json").read_text())
    assert [item["path"] for item in changed] == ["src/app.py", "src/new.py"]
    assert "src/new.py" in (artifact_root / "revision-1" / "proposal.diff").read_text()
    assert service.get_task("task_1").status == "reviewing"


def test_capture_includes_empty_new_file_without_mutating_worker_index(tmp_path):
    service, workspaces, workspace = executor_done(tmp_path)
    empty = workspace / "src" / "empty.md"
    empty.write_text("")
    before = subprocess.run(
        ["git", "-C", str(workspace), "diff", "--cached", "--binary"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout

    DelegationArtifactService(service, workspaces).capture("task_1")

    patch = (workspace.parent / "artifacts" / "revision-1" / "proposal.diff").read_text()
    after = subprocess.run(
        ["git", "-C", str(workspace), "diff", "--cached", "--binary"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout
    assert "new file mode 100644" in patch
    assert "src/empty.md" in patch
    assert after == before


def test_capture_excludes_stale_intent_to_add_path_absent_from_base_and_workspace(tmp_path):
    service, workspaces, workspace = executor_done(tmp_path)
    ghost = workspace / "src" / "ghost.md"
    ghost.write_text("")
    git(workspace, "add", "-N", "--", "src/ghost.md")
    ghost.unlink()
    (workspace / "src" / "app.py").write_text("value = 2\n")

    DelegationArtifactService(service, workspaces).capture("task_1")

    artifact_root = workspace.parent / "artifacts" / "revision-1"
    changed = json.loads((artifact_root / "changed_files.json").read_text())
    patch = (artifact_root / "proposal.diff").read_text()
    assert [item["path"] for item in changed] == ["src/app.py"]
    assert "ghost.md" not in patch


def test_capture_rejects_denied_path_change(tmp_path):
    service, workspaces, workspace = executor_done(tmp_path)
    (workspace / "private").mkdir()
    (workspace / "private" / "secret.txt").write_text("changed\n")

    with pytest.raises(ArtifactCaptureError, match="Denied path changed"):
        DelegationArtifactService(service, workspaces).capture("task_1")


def test_capture_excludes_untracked_python_and_pytest_caches(tmp_path):
    service, workspaces, workspace = executor_done(tmp_path)
    (workspace / "src" / "app.py").write_text("value = 2\n")
    bytecode = workspace / "src" / "__pycache__" / "app.cpython-312.pyc"
    bytecode.parent.mkdir()
    bytecode.write_bytes(b"generated bytecode")
    pytest_cache = workspace / "src" / ".pytest_cache" / "v" / "cache" / "nodeids"
    pytest_cache.parent.mkdir(parents=True)
    pytest_cache.write_text("[]\n")

    DelegationArtifactService(service, workspaces).capture("task_1")

    artifact_root = workspace.parent / "artifacts" / "revision-1"
    changed = json.loads((artifact_root / "changed_files.json").read_text())
    patch = (artifact_root / "proposal.diff").read_text()
    assert [item["path"] for item in changed] == ["src/app.py"]
    assert "__pycache__" not in patch
    assert ".pytest_cache" not in patch


def test_capture_reports_advisory_launch_before_scanning_empty_workspace(tmp_path):
    service, workspaces, workspace = executor_done(tmp_path)
    stdout = workspace.parent / "artifacts" / "launch.stdout.log"
    stdout.parent.mkdir(exist_ok=True)
    stdout.write_text("printed tool call JSON\n")
    service.store.append_delegation_record(
        "task_1",
        "launches",
        "launch_1",
        {
            "launch_id": "launch_1",
            "task_id": "task_1",
            "session_id": "session_1",
            "executor_id": "worker",
            "argv": ["worker"],
            "cwd": str(workspace),
            "prompt_path": str(workspace.parent / "artifacts" / "prompt.md"),
            "stdout_path": str(stdout),
            "stderr_path": str(workspace.parent / "artifacts" / "stderr.log"),
            "outcome": "advisory",
            "outcome_detail": "Worker produced advisory output but changed no files",
        },
    )

    with pytest.raises(ArtifactCaptureError, match="request a revision") as caught:
        DelegationArtifactService(service, workspaces).capture("task_1")

    assert str(stdout) in str(caught.value)
