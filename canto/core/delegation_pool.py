from __future__ import annotations

from canto.core.delegation import DelegationService, TERMINAL_STATUSES
from canto.core.delegation_executor import CodexCliExecutor, ExecutorError
from canto.models.delegation import DelegationTaskStatus, ExecutorPoolEntry


class DelegationPoolService:
    def __init__(self, delegation: DelegationService):
        self.delegation = delegation

    def executors(self) -> list[ExecutorPoolEntry]:
        tasks = self.delegation.list_tasks()
        entries = []
        for profile in self.delegation.list_executor_profiles():
            assigned = sorted(
                task.task_id
                for task in tasks
                if task.executor_id == profile.executor_id
                and task.status not in TERMINAL_STATUSES
            )
            if profile.harness == "manual":
                available = True
                detail = "manual_unverified"
            else:
                try:
                    executable = CodexCliExecutor.available(profile)
                    available = True
                    detail = executable
                except ExecutorError as exc:
                    available = False
                    detail = str(exc)
            entries.append(
                ExecutorPoolEntry(
                    executor_id=profile.executor_id,
                    harness=profile.harness,
                    available=available,
                    availability_detail=detail,
                    active_tasks=len(assigned),
                    task_ids=assigned,
                )
            )
        return entries

    def tasks(self, *, active_only: bool = False) -> list[DelegationTaskStatus]:
        tasks = self.delegation.list_tasks()
        if active_only:
            tasks = [task for task in tasks if task.status not in TERMINAL_STATUSES]
        return [
            DelegationTaskStatus(
                task_id=task.task_id,
                title=task.title,
                status=task.status,
                executor_id=task.executor_id,
                workspace_id=task.workspace_id,
                latest_result_revision=task.latest_result_revision,
                updated_at=task.updated_at,
            )
            for task in tasks
        ]
