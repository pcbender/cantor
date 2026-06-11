from __future__ import annotations

import subprocess
from pathlib import Path

from canto.core.delegation import DelegationService
from canto.core.delegation_artifacts import DelegationArtifactService
from canto.core.delegation_commands import DelegationCommandService
from canto.core.delegation_queue import DelegationPromotionQueue
from canto.core.delegation_review import DelegationReviewService
from canto.core.delegation_timeline import DelegationTimelineService
from canto.core.delegation_workspace import DelegationWorkspaceService, inspect_repository
from canto.core.state import SqliteStateStore
from canto.models.delegation import DelegationScope, DelegationTask, ExecutorProfile


def git(repository: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repository), *args],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()


def test_local_delegated_executor_revision_promotion_survives_restart(tmp_path):
    repository = tmp_path / "repository"
    repository.mkdir()
    git(repository, "init")
    git(repository, "config", "user.email", "test@example.com")
    git(repository, "config", "user.name", "Test User")
    (repository / "src").mkdir()
    (repository / "src" / "app.py").write_text("value = 1\n")
    (repository / "private").mkdir()
    (repository / "private" / "token.txt").write_text("fixture\n")
    git(repository, "add", ".")
    git(repository, "commit", "-m", "initial")
    initial_head = git(repository, "rev-parse", "HEAD")

    state_path = tmp_path / "state" / "canto.db"
    service = DelegationService(SqliteStateStore(state_path))
    workspaces = DelegationWorkspaceService(service, tmp_path / "delegations")
    service.set_executor_profile(
        ExecutorProfile(executor_id="manual", name="Manual", harness="manual")
    )
    service.create_task(
        DelegationTask(
            task_id="task_e2e",
            title="Update fixture value",
            instructions="Change the public fixture without touching private data.",
            repository=inspect_repository(repository),
            scope=DelegationScope(
                allowed_paths=["src"],
                denied_paths=["private"],
                allowed_commands=["git diff --check"],
                required_commands=["git diff --check"],
            ),
        )
    )
    service.transition("task_e2e", "assigned", updates={"executor_id": "manual"})
    workspace = workspaces.prepare("task_e2e")
    workspace_path = Path(workspace.path)
    assert not (workspace_path / "private").exists()

    service.transition("task_e2e", "executor_working")
    (workspace_path / "src" / "app.py").write_text("value = 2\n")
    DelegationCommandService(service, workspaces).run(
        "task_e2e", "git diff --check"
    )
    service.transition("task_e2e", "executor_done")
    first = DelegationArtifactService(service, workspaces).capture("task_e2e")
    DelegationReviewService(service, workspaces).request_revision(
        "task_e2e", "maintainer", "Use value 3"
    )

    service.transition("task_e2e", "executor_working")
    (workspace_path / "src" / "app.py").write_text("value = 3\n")
    DelegationCommandService(service, workspaces).run(
        "task_e2e", "git diff --check"
    )
    service.transition("task_e2e", "executor_done")
    second = DelegationArtifactService(service, workspaces).capture("task_e2e")
    DelegationReviewService(service, workspaces).accept(
        "task_e2e", "maintainer", "Revision verified"
    )
    DelegationPromotionQueue(service, workspaces).enqueue(
        "task_e2e", "maintainer"
    )

    reopened_service = DelegationService(SqliteStateStore(state_path))
    reopened_workspaces = DelegationWorkspaceService(
        reopened_service, tmp_path / "delegations"
    )
    timeline_before = DelegationTimelineService(reopened_service).timeline("task_e2e")
    promotion = DelegationPromotionQueue(
        reopened_service, reopened_workspaces
    ).promote("task_e2e", "maintainer")

    assert first.revision == 1
    assert second.revision == 2
    assert reopened_service.get_task("task_e2e").status == "promoted"
    assert promotion.result_revision == 2
    assert (repository / "src" / "app.py").read_text() == "value = 3\n"
    assert (repository / "private" / "token.txt").read_text() == "fixture\n"
    assert git(repository, "rev-parse", "HEAD") == initial_head
    assert any(item.kind == "reviews" for item in timeline_before)
    assert any(item.kind == "promotion_queue" for item in timeline_before)
    assert DelegationTimelineService(reopened_service).timeline("task_e2e")[-1].summary == "task.promoted"
