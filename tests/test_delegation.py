from __future__ import annotations

import fakeredis
import pytest
from pydantic import ValidationError

from canto.core.delegation import DelegationError, DelegationService
from canto.core.state import MemoryStateStore, RedisStateStore, SqliteStateStore
from canto.models.delegation import (
    CommandRecord,
    DelegationMessage,
    DelegationScope,
    DelegationTask,
    ExecutorProfile,
    RepositoryIdentity,
)


@pytest.fixture(params=["memory", "redis", "sqlite"])
def store(request, tmp_path):
    if request.param == "memory":
        return MemoryStateStore()
    if request.param == "sqlite":
        return SqliteStateStore(tmp_path / "state" / "canto.db")
    state = RedisStateStore("redis://unused")
    state.client = fakeredis.FakeRedis(decode_responses=True)
    return state


def task(task_id: str = "task_1") -> DelegationTask:
    return DelegationTask(
        task_id=task_id,
        title="Implement a bounded change",
        repository=RepositoryIdentity(
            canonical_path="/workspace/project", initial_head="a" * 40
        ),
        scope=DelegationScope(
            allowed_paths=["canto/", "tests/"], denied_paths=[".env"]
        ),
    )


def test_delegation_models_reject_unknown_status():
    with pytest.raises(ValidationError):
        DelegationTask(
            task_id="task_1",
            title="Invalid",
            status="invented",
            repository=RepositoryIdentity(canonical_path="/workspace/project"),
        )


def test_service_persists_tasks_profiles_records_and_ordered_events(store):
    service = DelegationService(store)
    created = service.create_task(task())
    profile = ExecutorProfile(
        executor_id="manual_1", name="Manual reviewer", harness="manual"
    )
    service.set_executor_profile(profile)

    assigned = service.transition(
        created.task_id, "assigned", updates={"executor_id": profile.executor_id}
    )
    service.append_record(
        created.task_id,
        "messages",
        DelegationMessage(
            message_id="message_1",
            task_id=created.task_id,
            sender="orchestrator",
            kind="assignment",
            body="Work only in the declared scope.",
        ),
    )
    service.append_record(
        created.task_id,
        "commands",
        CommandRecord(
            record_id="command_1",
            task_id=created.task_id,
            command="pytest tests/test_delegation.py",
            source="executor_reported",
            status="reported",
        ),
    )

    assert assigned.executor_id == "manual_1"
    assert service.get_task(created.task_id).status == "assigned"
    assert [item.task_id for item in service.list_tasks()] == [created.task_id]
    assert service.get_executor_profile("manual_1") == profile
    assert service.get_records(created.task_id, "messages")[0]["message_id"] == "message_1"
    assert service.get_records(created.task_id, "commands")[0]["record_id"] == "command_1"
    assert [event.event_type for event in service.get_events(created.task_id)] == [
        "task.created",
        "task.assigned",
    ]


def test_service_rejects_invalid_transition(store):
    service = DelegationService(store)
    service.create_task(task())

    with pytest.raises(
        DelegationError, match="Invalid delegation transition: draft -> promoted"
    ):
        service.transition("task_1", "promoted")


def test_delegation_store_compare_and_set(store):
    value = task().model_dump(mode="json")
    store.set_delegation_task("task_1", value)
    assigned = {**value, "status": "assigned"}

    assert store.transition_delegation_task("task_1", {"draft"}, assigned) is True
    assert store.transition_delegation_task("task_1", {"draft"}, value) is False


def test_sqlite_delegation_state_survives_reopen(tmp_path):
    path = tmp_path / "state" / "canto.db"
    first = DelegationService(SqliteStateStore(path))
    first.create_task(task())
    first.transition("task_1", "assigned")

    reopened = DelegationService(SqliteStateStore(path))

    assert reopened.get_task("task_1").status == "assigned"
    assert len(reopened.get_events("task_1")) == 2
