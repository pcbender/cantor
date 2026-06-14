from __future__ import annotations

import fakeredis
import pytest
import sqlite3
import threading

from canto.core.state import MemoryStateStore, RedisStateStore, SqliteStateStore


@pytest.fixture(params=["memory", "redis", "sqlite"])
def store(request, tmp_path):
    if request.param == "memory":
        return MemoryStateStore()
    if request.param == "sqlite":
        return SqliteStateStore(tmp_path / "state" / "canto.db")
    state = RedisStateStore("redis://unused")
    state.client = fakeredis.FakeRedis(decode_responses=True)
    return state


def test_transition_job_requires_expected_status(store):
    queued = {"job_id": "job_1", "status": "queued"}
    running = {"job_id": "job_1", "status": "running"}
    store.set_job("job_1", queued)

    assert store.transition_job("job_1", {"queued"}, running) is True
    assert store.transition_job("job_1", {"queued"}, queued) is False
    assert store.get_job("job_1") == running


def test_transition_approval_requires_expected_status(store):
    pending = {"approval_id": "approval_1", "status": "pending"}
    approved = {"approval_id": "approval_1", "status": "approved"}
    store.set_approval("approval_1", pending)

    assert store.transition_approval("approval_1", {"pending"}, approved) is True
    assert store.transition_approval("approval_1", {"pending"}, pending) is False
    assert store.get_approval("approval_1") == approved


def test_state_store_round_trip_contract(store):
    job = {"job_id": "job_1", "status": "queued", "value": 1}
    event = {"timestamp": "2026-06-10T00:00:00Z", "type": "created"}
    artifacts = [{"name": "report", "path": "/tmp/report.md"}]
    approval = {"approval_id": "approval_1", "status": "pending"}
    registry = {"skills": [{"name": "demo"}], "providers": [], "tools": []}
    plan = {"plan_id": "plan_20260610_abcdef", "status": "draft"}

    store.set_job("job_1", job)
    store.append_event("job_1", event)
    store.set_artifacts("job_1", artifacts)
    store.set_approval("approval_1", approval)
    store.set_registry(registry)
    store.set_plan(plan["plan_id"], plan)

    assert store.ping() is True
    assert store.get_job("job_1") == job
    assert store.get_events("job_1") == [event]
    assert store.get_artifacts("job_1") == artifacts
    assert store.get_approval("approval_1") == approval
    assert store.get_registry() == registry
    assert store.get_plan(plan["plan_id"]) == plan

    claim = {"status": "running", "job_id": "job_1"}
    assert store.claim_idempotency("demo", claim) is None
    assert store.claim_idempotency("demo", claim) == claim
    failed = {"status": "failed", "job_id": "job_1"}
    store.set_idempotency("demo", failed)
    assert store.claim_idempotency("demo", claim) is None


def test_sqlite_state_survives_reopen(tmp_path):
    path = tmp_path / "state" / "canto.db"
    first = SqliteStateStore(path)
    first.set_job("job_1", {"job_id": "job_1", "status": "queued"})
    first.append_event("job_1", {"type": "created"})
    first.set_plan(
        "plan_20260610_abcdef",
        {"plan_id": "plan_20260610_abcdef", "status": "draft"},
    )

    reopened = SqliteStateStore(path)

    assert reopened.get_job("job_1")["status"] == "queued"
    assert reopened.get_events("job_1") == [{"type": "created"}]
    assert reopened.get_plan("plan_20260610_abcdef")["status"] == "draft"


def test_sqlite_read_only_store_reads_without_writable_directory(tmp_path):
    path = tmp_path / "state" / "canto.db"
    writable = SqliteStateStore(path)
    writable.set_executor_profile(
        "local-worker",
        {"executor_id": "local-worker", "name": "Local Worker", "harness": "manual"},
    )
    path.parent.chmod(0o500)

    try:
        read_only = SqliteStateStore(path, read_only=True)

        assert read_only.list_executor_profiles()[0]["executor_id"] == "local-worker"
    finally:
        path.parent.chmod(0o700)


def test_sqlite_read_only_store_does_not_create_missing_state(tmp_path):
    path = tmp_path / "missing" / "state.sqlite"
    store = SqliteStateStore(path, read_only=True)

    with pytest.raises(sqlite3.OperationalError, match="does not exist"):
        store.list_executor_profiles()

    assert not path.parent.exists()


def test_sqlite_transition_is_atomic_under_concurrency(tmp_path):
    store = SqliteStateStore(tmp_path / "state" / "canto.db")
    store.set_approval(
        "approval_1", {"approval_id": "approval_1", "status": "pending"}
    )
    barrier = threading.Barrier(3)
    results = []

    def decide(status):
        barrier.wait()
        results.append(
            store.transition_approval(
                "approval_1",
                {"pending"},
                {"approval_id": "approval_1", "status": status},
            )
        )

    workers = [
        threading.Thread(target=decide, args=("approved",)),
        threading.Thread(target=decide, args=("rejected",)),
    ]
    for worker in workers:
        worker.start()
    barrier.wait()
    for worker in workers:
        worker.join()

    assert sorted(results) == [False, True]
    assert store.get_approval("approval_1")["status"] in {"approved", "rejected"}
