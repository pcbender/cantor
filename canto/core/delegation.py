from __future__ import annotations

from uuid import uuid4

from canto.core.state import StateStore
from canto.models.delegation import (
    DelegationEvent,
    DelegationStatus,
    DelegationTask,
    ExecutorProfile,
)
from canto.models.schemas import utc_now


class DelegationError(RuntimeError):
    pass


TRANSITIONS: dict[str, set[str]] = {
    "draft": {"assigned"},
    "assigned": {"workspace_ready"},
    "workspace_ready": {"executor_working"},
    "executor_working": {"executor_blocked", "executor_done", "failed", "cancelled"},
    "executor_blocked": {"executor_working", "failed", "cancelled"},
    "executor_done": {"reviewing", "revision_requested"},
    "reviewing": {"revision_requested", "accepted", "rejected"},
    "revision_requested": {"executor_working"},
    "accepted": {"promoting", "cancelled"},
    "promoting": {"promoted", "promotion_failed"},
    "promotion_failed": {"promoting", "revision_requested", "rejected", "cancelled"},
}

TERMINAL_STATUSES = {"promoted", "rejected", "cancelled", "failed"}


class DelegationService:
    def __init__(self, store: StateStore):
        self.store = store

    def create_task(self, task: DelegationTask) -> DelegationTask:
        if self.store.get_delegation_task(task.task_id):
            raise DelegationError(f"Delegation task already exists: {task.task_id}")
        if task.status != "draft":
            raise DelegationError("New delegation tasks must start in draft status")
        self.store.set_delegation_task(task.task_id, task.model_dump(mode="json"))
        self._event(task, "task.created")
        return task

    def get_task(self, task_id: str) -> DelegationTask:
        value = self.store.get_delegation_task(task_id)
        if not value:
            raise DelegationError(f"Delegation task not found: {task_id}")
        return DelegationTask.model_validate(value)

    def list_tasks(self) -> list[DelegationTask]:
        return [DelegationTask.model_validate(value) for value in self.store.list_delegation_tasks()]

    def transition(
        self,
        task_id: str,
        status: DelegationStatus,
        *,
        details: dict | None = None,
        updates: dict | None = None,
    ) -> DelegationTask:
        current = self.get_task(task_id)
        if status not in TRANSITIONS.get(current.status, set()):
            raise DelegationError(
                f"Invalid delegation transition: {current.status} -> {status}"
            )
        values = current.model_dump(mode="json")
        values.update(updates or {})
        values["status"] = status
        values["updated_at"] = utc_now()
        updated = DelegationTask.model_validate(values)
        if not self.store.transition_delegation_task(
            task_id, {current.status}, updated.model_dump(mode="json")
        ):
            raise DelegationError(f"Delegation task changed concurrently: {task_id}")
        self._event(updated, f"task.{status}", details)
        return updated

    def set_executor_profile(self, profile: ExecutorProfile) -> ExecutorProfile:
        self.store.set_executor_profile(
            profile.executor_id, profile.model_dump(mode="json")
        )
        return profile

    def get_executor_profile(self, executor_id: str) -> ExecutorProfile:
        value = self.store.get_executor_profile(executor_id)
        if not value:
            raise DelegationError(f"Executor profile not found: {executor_id}")
        return ExecutorProfile.model_validate(value)

    def list_executor_profiles(self) -> list[ExecutorProfile]:
        return [
            ExecutorProfile.model_validate(value)
            for value in self.store.list_executor_profiles()
        ]

    def append_record(self, task_id: str, record_type: str, record) -> None:
        self.get_task(task_id)
        data = record.model_dump(mode="json")
        record_id = next(
            (value for key, value in data.items() if key.endswith("_id") and key != "task_id"),
            None,
        )
        if not record_id:
            raise DelegationError("Delegation record requires a record identifier")
        self.store.append_delegation_record(task_id, record_type, record_id, data)

    def get_records(self, task_id: str, record_type: str) -> list[dict]:
        self.get_task(task_id)
        return self.store.get_delegation_records(task_id, record_type)

    def get_events(self, task_id: str) -> list[DelegationEvent]:
        self.get_task(task_id)
        return [
            DelegationEvent.model_validate(value)
            for value in self.store.get_delegation_events(task_id)
        ]

    def _event(
        self, task: DelegationTask, event_type: str, details: dict | None = None
    ) -> None:
        event = DelegationEvent(
            event_id=f"event_{uuid4().hex}",
            task_id=task.task_id,
            event_type=event_type,
            status=task.status,
            details=details or {},
        )
        self.store.append_delegation_event(
            task.task_id, event.model_dump(mode="json")
        )
