from __future__ import annotations

from canto.core.delegation import DelegationService
from canto.models.delegation import DelegationTimelineItem


RECORD_TYPES = (
    "workspaces",
    "workspace_lifecycle",
    "sessions",
    "launches",
    "messages",
    "commands",
    "results",
    "reviews",
    "promotion_decisions",
    "promotion_queue",
    "promotions",
)

TERMINAL_EVENT_TYPES = {
    "task.promoted",
    "task.rejected",
    "task.cancelled",
    "task.failed",
}


def _record_id(value: dict) -> str:
    return next(
        (
            str(item)
            for key, item in value.items()
            if key.endswith("_id") and key != "task_id"
        ),
        "record",
    )


def _summary(record_type: str, value: dict) -> str:
    if record_type == "messages":
        return f"{value.get('sender')}: {value.get('kind')}"
    if record_type == "commands":
        return f"command {value.get('status')}: {value.get('command')}"
    if record_type == "reviews":
        return f"review {value.get('decision')} for revision {value.get('result_revision')}"
    if record_type == "results":
        return f"captured result revision {value.get('revision')}"
    if record_type == "promotions":
        return f"promotion {value.get('status')}"
    if record_type == "promotion_queue":
        return f"promotion queue {value.get('status')}"
    return record_type.replace("_", " ")


class DelegationTimelineService:
    def __init__(self, delegation: DelegationService):
        self.delegation = delegation

    def timeline(self, task_id: str) -> list[DelegationTimelineItem]:
        task = self.delegation.get_task(task_id)
        items = []
        for sequence, event in enumerate(self.delegation.get_events(task_id)):
            data = event.model_dump(mode="json")
            sort_timestamp = (
                "9999-12-31T23:59:59.999999Z"
                if data["event_type"] in TERMINAL_EVENT_TYPES
                else data["created_at"]
            )
            items.append(
                (
                    sort_timestamp,
                    0,
                    sequence,
                    DelegationTimelineItem(
                        timestamp=data["created_at"],
                        kind="event",
                        record_id=data["event_id"],
                        summary=data["event_type"],
                        data=data,
                    ),
                )
            )
        for type_order, record_type in enumerate(RECORD_TYPES, 1):
            for sequence, value in enumerate(
                self.delegation.get_records(task_id, record_type)
            ):
                timestamp = (
                    value.get("created_at")
                    or value.get("started_at")
                    or value.get("removed_at")
                    or task.created_at
                )
                record_id = _record_id(value)
                items.append(
                    (
                        timestamp,
                        type_order,
                        sequence,
                        DelegationTimelineItem(
                            timestamp=timestamp,
                            kind=record_type,
                            record_id=record_id,
                            summary=_summary(record_type, value),
                            data=value,
                        ),
                    )
                )
        return [item[-1] for item in sorted(items, key=lambda item: item[:3])]
