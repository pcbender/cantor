from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from canto.core.state import RedisStateStore, SqliteStateStore


class StateMigrationError(ValueError):
    """Raised when legacy state cannot be migrated safely."""


class StateMigrationResult(BaseModel):
    imported: dict[str, int] = Field(default_factory=dict)
    skipped: dict[str, int] = Field(default_factory=dict)


def _increment(target: dict[str, int], name: str) -> None:
    target[name] = target.get(name, 0) + 1


def migrate_legacy_state(
    source: RedisStateStore,
    target: SqliteStateStore,
    plans_dir: str | Path | None = None,
) -> StateMigrationResult:
    imported: dict[str, int] = {}
    skipped: dict[str, int] = {}

    try:
        job_keys = sorted(source.client.scan_iter(match="canto:job:job_*"))
        approval_keys = sorted(source.client.scan_iter(match="canto:approval:*"))
    except Exception as exc:
        raise StateMigrationError(f"Cannot read Redis state: {exc}") from exc

    job_ids = []
    for raw_key in job_keys:
        key = raw_key.decode() if isinstance(raw_key, bytes) else raw_key
        suffix = key.removeprefix("canto:job:")
        if ":" in suffix:
            continue
        job_ids.append(suffix)

    for job_id in sorted(job_ids):
        job = source.get_job(job_id)
        if job is None:
            continue
        if target.get_job(job_id) is None:
            target.set_job(job_id, job)
            _increment(imported, "jobs")
        else:
            _increment(skipped, "jobs")

        events = source.get_events(job_id)
        if events:
            if target.get_events(job_id):
                skipped["events"] = skipped.get("events", 0) + len(events)
            else:
                for event in events:
                    target.append_event(job_id, event)
                imported["events"] = imported.get("events", 0) + len(events)

        artifacts = source.get_artifacts(job_id)
        if artifacts:
            if target.get_artifacts(job_id):
                skipped["artifact_sets"] = skipped.get("artifact_sets", 0) + 1
            else:
                target.set_artifacts(job_id, artifacts)
                _increment(imported, "artifact_sets")

    for raw_key in approval_keys:
        key = raw_key.decode() if isinstance(raw_key, bytes) else raw_key
        approval_id = key.removeprefix("canto:approval:")
        approval = source.get_approval(approval_id)
        if approval is None:
            continue
        if target.get_approval(approval_id) is None:
            target.set_approval(approval_id, approval)
            _increment(imported, "approvals")
        else:
            _increment(skipped, "approvals")

    registry = source.get_registry()
    if registry is not None:
        if target.get_registry() is None:
            target.set_registry(registry)
            _increment(imported, "registry_snapshots")
        else:
            _increment(skipped, "registry_snapshots")

    if plans_dir is not None:
        for path in sorted(Path(plans_dir).glob("plan_*.json")):
            try:
                plan = json.loads(path.read_text(encoding="utf-8"))
                plan_id = plan["plan_id"]
                status = plan["status"]
            except (OSError, json.JSONDecodeError, KeyError) as exc:
                raise StateMigrationError(
                    f"Cannot read legacy plan {path}: {exc}"
                ) from exc
            if not isinstance(plan_id, str) or not isinstance(status, str):
                raise StateMigrationError(
                    f"Legacy plan {path} has invalid plan_id or status"
                )
            if target.get_plan(plan_id) is None:
                target.set_plan(plan_id, plan)
                _increment(imported, "plans")
            else:
                _increment(skipped, "plans")

    return StateMigrationResult(imported=imported, skipped=skipped)
