import json

import fakeredis

from canto.core.state import RedisStateStore, SqliteStateStore
from canto.core.state_migration import migrate_legacy_state


def test_migrate_legacy_state_is_repeatable_and_preserves_sources(tmp_path):
    source = RedisStateStore("redis://unused")
    source.client = fakeredis.FakeRedis(decode_responses=True)
    target = SqliteStateStore(tmp_path / "state" / "canto.db")
    job = {
        "job_id": "job_20260610_abcdef",
        "status": "completed",
        "created_at": "2026-06-10T00:00:00Z",
    }
    event = {"timestamp": "2026-06-10T00:00:01Z", "type": "job_completed"}
    artifacts = [{"name": "report", "path": "/tmp/report.md"}]
    approval = {
        "approval_id": "approval_20260610_abcdef",
        "status": "approved",
        "updated_at": "2026-06-10T00:00:00Z",
    }
    registry = {"skills": [], "providers": [], "tools": []}
    source.set_job(job["job_id"], job)
    source.append_event(job["job_id"], event)
    source.set_artifacts(job["job_id"], artifacts)
    source.set_approval(approval["approval_id"], approval)
    source.set_registry(registry)
    plans = tmp_path / "plans"
    plans.mkdir()
    plan = {
        "plan_id": "plan_20260610_abcdef",
        "status": "completed",
        "created_at": "2026-06-10T00:00:00Z",
    }
    plan_path = plans / f"{plan['plan_id']}.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    first = migrate_legacy_state(source, target, plans)
    second = migrate_legacy_state(source, target, plans)

    assert first.imported == {
        "jobs": 1,
        "events": 1,
        "artifact_sets": 1,
        "approvals": 1,
        "registry_snapshots": 1,
        "plans": 1,
    }
    assert second.imported == {}
    assert second.skipped == {
        "jobs": 1,
        "events": 1,
        "artifact_sets": 1,
        "approvals": 1,
        "registry_snapshots": 1,
        "plans": 1,
    }
    assert target.get_job(job["job_id"]) == job
    assert target.get_events(job["job_id"]) == [event]
    assert target.get_artifacts(job["job_id"]) == artifacts
    assert target.get_approval(approval["approval_id"]) == approval
    assert target.get_registry() == registry
    assert target.get_plan(plan["plan_id"]) == plan
    assert source.get_job(job["job_id"]) == job
    assert plan_path.is_file()
