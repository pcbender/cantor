from __future__ import annotations

from pathlib import Path

from canto.core.cli_executor import CLI_HARNESSES
from canto.core.delegation import DelegationService, TERMINAL_STATUSES
from canto.core.delegation_executor import DelegationCliExecutor, ExecutorError
from canto.core.delegation_workspace import DelegationWorkspaceService
from canto.models.delegation import (
    DelegationDashboardDetail,
    DelegationDashboardTask,
)


ATTENTION_ORDER = {"blocked": 0, "review": 1, "ready": 2, "working": 3, "terminal": 4}


def _attention(status: str, worker_outcome: str | None = None) -> str:
    if status == "executor_done" and worker_outcome in {"advisory", "no_work"}:
        return "blocked"
    if status in {"executor_blocked", "promotion_failed", "failed"}:
        return "blocked"
    if status in {"executor_done", "reviewing", "revision_requested"}:
        return "review"
    if status in {"draft", "assigned", "workspace_ready", "accepted"}:
        return "ready"
    if status in TERMINAL_STATUSES:
        return "terminal"
    return "working"


def _actions(status: str, worker_outcome: str | None = None) -> list[str]:
    if status == "executor_done" and worker_outcome in {"advisory", "no_work"}:
        return ["revise"]
    return {
        "draft": ["assign"],
        "assigned": ["prepare"],
        "workspace_ready": ["launch", "start"],
        "executor_working": ["message", "block", "done"],
        "executor_blocked": ["resume", "reject"],
        "executor_done": ["capture", "revise"],
        "reviewing": ["accept", "revise", "reject"],
        "revision_requested": ["launch", "resume"],
        "accepted": ["review-summary", "queue-add", "promote"],
        "promoting": [],
        "promotion_failed": ["conflict", "revise", "promote", "reject"],
        "promoted": [],
        "rejected": [],
        "cancelled": [],
        "failed": [],
    }.get(status, [])


class DelegationDashboardService:
    def __init__(
        self,
        delegation: DelegationService,
        workspaces: DelegationWorkspaceService,
    ):
        self.delegation = delegation
        self.workspaces = workspaces

    def list(self, *, active_only: bool = False) -> list[DelegationDashboardTask]:
        rows = []
        for task in self.delegation.list_tasks():
            if active_only and task.status in TERMINAL_STATUSES:
                continue
            profile = None
            if task.executor_id:
                try:
                    profile = self.delegation.get_executor_profile(task.executor_id)
                except Exception:
                    pass
            launches = self.delegation.get_records(task.task_id, "launches")
            latest_launch = launches[-1] if launches else None
            worker_outcome = latest_launch.get("outcome") if latest_launch else None
            actions = _actions(task.status, worker_outcome)
            attention = _attention(task.status, worker_outcome)
            rows.append(
                DelegationDashboardTask(
                    task_id=task.task_id,
                    title=task.title,
                    status=task.status,
                    attention=attention,
                    executor_id=task.executor_id,
                    harness=profile.harness if profile else None,
                    repository=Path(task.repository.canonical_path).name,
                    latest_result_revision=task.latest_result_revision,
                    accepted_result_revision=task.accepted_result_revision,
                    worker_outcome=worker_outcome,
                    next_action=actions[0] if actions else "none",
                    updated_at=task.updated_at,
                )
            )
        rows.sort(key=lambda row: row.task_id)
        rows.sort(key=lambda row: row.updated_at, reverse=True)
        rows.sort(key=lambda row: ATTENTION_ORDER[row.attention])
        return rows

    def detail(self, task_id: str) -> DelegationDashboardDetail:
        task = self.delegation.get_task(task_id)
        row = next(item for item in self.list() if item.task_id == task_id)
        workspace_records = self.delegation.get_records(task_id, "workspaces")
        workspace = workspace_records[-1] if workspace_records else None
        executor = None
        if task.executor_id:
            try:
                profile = self.delegation.get_executor_profile(task.executor_id)
                executor = profile.model_dump(mode="json")
                if profile.harness in CLI_HARNESSES:
                    try:
                        executor["available"] = True
                        executor["availability_detail"] = DelegationCliExecutor.available(profile)
                    except ExecutorError as exc:
                        executor["available"] = False
                        executor["availability_detail"] = str(exc)
                else:
                    executor["available"] = True
                    executor["availability_detail"] = "manual_unverified"
            except Exception:
                executor = {"executor_id": task.executor_id, "available": False}
        results = self.delegation.get_records(task_id, "results")
        commands = self.delegation.get_records(task_id, "commands")
        grouped = {status: [] for status in ("passed", "failed", "reported", "waived")}
        for command in commands:
            grouped.setdefault(command.get("status", "reported"), []).append(command)
        queue_records = self.delegation.get_records(task_id, "promotion_queue")
        artifact_root = None
        if workspace:
            artifact_root = str(Path(workspace["path"]).parent / "artifacts")
        launches = self.delegation.get_records(task_id, "launches")
        latest_launch = launches[-1] if launches else None
        return DelegationDashboardDetail(
            task=row,
            repository=task.repository,
            scope=task.scope,
            workspace=workspace,
            executor=executor,
            sessions=DelegationCliExecutor(
                self.delegation, self.workspaces
            ).projected_sessions(task_id),
            launches=launches,
            latest_result=results[-1] if results else None,
            reviews=self.delegation.get_records(task_id, "reviews"),
            commands=grouped,
            queue=queue_records[-1] if queue_records else None,
            outcome_detail=(latest_launch.get("outcome_detail") if latest_launch else None),
            next_actions=_actions(task.status, row.worker_outcome),
            artifact_root=artifact_root,
        )
