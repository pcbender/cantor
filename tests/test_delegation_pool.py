from __future__ import annotations

from canto.core.delegation import DelegationService
from canto.core.delegation_pool import DelegationPoolService
from canto.core.state import MemoryStateStore
from canto.models.delegation import DelegationTask, ExecutorProfile, RepositoryIdentity


def test_pool_reports_availability_and_parallel_assignments(tmp_path):
    service = DelegationService(MemoryStateStore())
    service.set_executor_profile(
        ExecutorProfile(executor_id="manual", name="Manual", harness="manual")
    )
    service.set_executor_profile(
        ExecutorProfile(
            executor_id="missing_codex",
            name="Missing Codex",
            harness="codex_cli",
            executable=str(tmp_path / "missing"),
            launch_mode="canto",
        )
    )
    for task_id in ("task_a", "task_b"):
        service.create_task(
            DelegationTask(
                task_id=task_id,
                title=task_id,
                repository=RepositoryIdentity(canonical_path="/repository"),
            )
        )
        service.transition(task_id, "assigned", updates={"executor_id": "manual"})

    pool = DelegationPoolService(service)
    executors = {entry.executor_id: entry for entry in pool.executors()}

    assert executors["manual"].available is True
    assert executors["manual"].active_tasks == 2
    assert executors["manual"].task_ids == ["task_a", "task_b"]
    assert executors["missing_codex"].available is False
    assert [task.task_id for task in pool.tasks(active_only=True)] == [
        "task_a",
        "task_b",
    ]


def test_pool_does_not_assign_unassigned_tasks():
    service = DelegationService(MemoryStateStore())
    service.set_executor_profile(
        ExecutorProfile(executor_id="manual", name="Manual", harness="manual")
    )
    service.create_task(
        DelegationTask(
            task_id="task_a",
            title="Unassigned",
            repository=RepositoryIdentity(canonical_path="/repository"),
        )
    )

    DelegationPoolService(service).executors()

    assert service.get_task("task_a").executor_id is None
    assert service.get_task("task_a").status == "draft"
