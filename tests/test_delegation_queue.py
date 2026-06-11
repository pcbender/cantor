from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from canto.core.delegation import DelegationService
from canto.core.delegation_artifacts import DelegationArtifactService
from canto.core.delegation_queue import DelegationPromotionQueue, QueueError
from canto.core.delegation_review import DelegationReviewService
from canto.core.delegation_workspace import DelegationWorkspaceService, inspect_repository
from canto.core.state import MemoryStateStore
from canto.models.delegation import DelegationScope, DelegationTask


def git(repository: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repository), *args], check=True, capture_output=True)


def accepted_tasks(tmp_path, paths):
    repository = tmp_path / "repository"
    repository.mkdir()
    git(repository, "init")
    git(repository, "config", "user.email", "test@example.com")
    git(repository, "config", "user.name", "Test User")
    (repository / "src").mkdir()
    for path in set(paths):
        (repository / path).write_text("value = 1\n")
    git(repository, "add", ".")
    git(repository, "commit", "-m", "initial")
    service = DelegationService(MemoryStateStore())
    workspaces = DelegationWorkspaceService(service, tmp_path / "delegations")
    for index, path in enumerate(paths, 1):
        task_id = f"task_{index}"
        service.create_task(
            DelegationTask(
                task_id=task_id,
                title=task_id,
                repository=inspect_repository(repository),
                scope=DelegationScope(allowed_paths=["src"]),
            )
        )
        service.transition(task_id, "assigned", updates={"executor_id": "manual"})
        workspace = workspaces.prepare(task_id)
        service.transition(task_id, "executor_working")
        (Path(workspace.path) / path).write_text(f"value = {index + 1}\n")
        service.transition(task_id, "executor_done")
        DelegationArtifactService(service, workspaces).capture(task_id)
        DelegationReviewService(service, workspaces).accept(task_id, "reviewer")
    return service, workspaces, repository


def test_queue_detects_overlapping_accepted_results(tmp_path):
    service, workspaces, _ = accepted_tasks(
        tmp_path, ["src/app.py", "src/app.py"]
    )
    queue = DelegationPromotionQueue(service, workspaces)

    first = queue.enqueue("task_1", "orchestrator")
    second = queue.enqueue("task_2", "orchestrator")

    assert first.status == "pending"
    assert second.status == "blocked"
    assert "overlaps queued task task_1" in second.blockers[0]


def test_queue_requires_explicit_promotion_and_detects_divergence(tmp_path):
    service, workspaces, repository = accepted_tasks(tmp_path, ["src/app.py"])
    queue = DelegationPromotionQueue(service, workspaces)
    queue.enqueue("task_1", "orchestrator")
    assert (repository / "src" / "app.py").read_text() == "value = 1\n"

    (repository / "README.md").write_text("advance\n")
    git(repository, "add", "README.md")
    git(repository, "commit", "-m", "advance")

    with pytest.raises(QueueError, match="HEAD diverged"):
        queue.promote("task_1", "orchestrator")


def test_queue_does_not_report_path_overlap_across_repositories(tmp_path):
    (tmp_path / "first").mkdir()
    (tmp_path / "second").mkdir()
    first_service, first_workspaces, _ = accepted_tasks(
        tmp_path / "first", ["src/app.py"]
    )
    second_service, second_workspaces, _ = accepted_tasks(
        tmp_path / "second", ["src/app.py"]
    )
    # Recreate both tasks in one durable view while retaining separate repositories.
    first_task = first_service.get_task("task_1")
    second_task = second_service.get_task("task_1").model_copy(
        update={"task_id": "task_2"}
    )
    first_service.store.set_delegation_task(
        "task_2", second_task.model_dump(mode="json")
    )
    for record_type in ("workspaces", "results"):
        for value in second_service.get_records("task_1", record_type):
            value["task_id"] = "task_2"
            record_id = next(
                item
                for key, item in value.items()
                if key.endswith("_id") and key != "task_id"
            )
            first_service.store.append_delegation_record(
                "task_2", record_type, record_id, value
            )
    queue = DelegationPromotionQueue(first_service, first_workspaces)

    assert queue.enqueue("task_1", "orchestrator").status == "pending"
    assert queue.enqueue("task_2", "orchestrator").status == "pending"
