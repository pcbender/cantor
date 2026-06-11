from __future__ import annotations

from canto.core.delegation import DelegationService
from canto.core.delegation_timeline import DelegationTimelineService
from canto.core.state import SqliteStateStore
from canto.models.delegation import (
    CommandRecord,
    DelegationMessage,
    DelegationTask,
    RepositoryIdentity,
)


def test_timeline_is_deterministic_and_restart_safe(tmp_path):
    path = tmp_path / "state" / "canto.db"
    service = DelegationService(SqliteStateStore(path))
    service.create_task(
        DelegationTask(
            task_id="task_1",
            title="Timeline",
            repository=RepositoryIdentity(canonical_path="/repository"),
        )
    )
    service.transition("task_1", "assigned", updates={"executor_id": "manual"})
    service.append_record(
        "task_1",
        "messages",
        DelegationMessage(
            message_id="message_1",
            task_id="task_1",
            sender="executor",
            kind="progress",
            body="Working",
            created_at="2099-06-11T12:00:00Z",
        ),
    )
    service.append_record(
        "task_1",
        "commands",
        CommandRecord(
            record_id="command_1",
            task_id="task_1",
            command="pytest",
            source="executor_reported",
            status="reported",
            created_at="2099-06-11T12:00:00Z",
        ),
    )
    before = [
        item.model_dump(mode="json")
        for item in DelegationTimelineService(service).timeline("task_1")
    ]

    reopened = DelegationService(SqliteStateStore(path))
    after = [
        item.model_dump(mode="json")
        for item in DelegationTimelineService(reopened).timeline("task_1")
    ]

    assert after == before
    assert [item["kind"] for item in after][-2:] == ["messages", "commands"]
    assert [item["summary"] for item in after if item["kind"] == "event"] == [
        "task.created",
        "task.assigned",
    ]
