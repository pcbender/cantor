from __future__ import annotations

import sqlite3
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from canto.core.jobs import JobService
from canto.core.memory import MemoryService, MemoryServiceError
from canto.core.state import MemoryStateStore, SqliteStateStore
from canto.models.memory import MemoryItem


def service(kind: str, tmp_path: Path) -> MemoryService:
    store = MemoryStateStore() if kind == "memory" else SqliteStateStore(tmp_path / f"{kind}.db")
    return MemoryService(store)


@pytest.mark.parametrize("kind", ["memory", "sqlite"])
def test_memory_lifecycle_and_existing_approval(kind: str, tmp_path: Path):
    memory = service(kind, tmp_path)
    item = memory.propose(
        scope="repo:repo_1",
        type="decision",
        title="Use one approval model",
        body="Memory activation uses the existing Approval object.",
        source_kind="documentation",
        source_ref="docs/design.md",
        author_kind="developer",
        author_id="developer",
        confidence="verified",
    )
    approval = memory.request_approval(item.memory_id, "developer")
    assert approval.subject_kind == "memory"
    assert memory.decide_approval(
        approval.approval_id, approve=True, actor="developer", note="approved"
    ).status == "active"
    assert memory.get(item.memory_id).status == "active"
    with pytest.raises(MemoryServiceError, match="already approved"):
        memory.decide_approval(
            approval.approval_id, approve=True, actor="developer", note="again"
        )


def test_job_service_dispatches_memory_approval(runtime):
    settings, registry, _, _ = runtime
    store = MemoryStateStore()
    memory = MemoryService(store)
    item = memory.propose(
        scope="repo:repo_1", type="decision", title="Decision", body="Body",
        source_kind="documentation", source_ref="docs/x", author_kind="developer",
        author_id="developer",
    )
    approval = memory.request_approval(item.memory_id, "developer")
    result = JobService(settings, registry, store).approve(
        approval.approval_id, "developer", "approved"
    )
    assert isinstance(result, MemoryItem)
    assert result.status == "active"


@pytest.mark.parametrize("kind", ["memory", "sqlite"])
def test_projects_scope_eligibility_and_recall(kind: str, tmp_path: Path):
    memory = service(kind, tmp_path)
    project = memory.create_project("Shared migration", "developer")
    memory.link_repository(project.project_id, "repo_1", "developer")
    item = memory.propose(
        scope=f"project:{project.project_id}", type="terminology", title="Crosswalk",
        body="A reviewed mapping between source and target concepts.",
        source_kind="documentation", source_ref="docs/glossary.md",
        author_kind="developer", author_id="developer", aliases=["mapping table"],
    )
    approval = memory.request_approval(item.memory_id, "developer")
    memory.decide_approval(approval.approval_id, approve=True, actor="developer", note="ok")
    scopes = memory.allowed_scopes("repo_1", [f"project:{project.project_id}"])
    assert scopes == [f"project:{project.project_id}"]
    assert memory.recall("mapping", scopes).items[0].memory_id == item.memory_id
    assert memory.resolve("mapping table", scopes).items[0].memory_id == item.memory_id
    memory.unlink_repository(project.project_id, "repo_1", "developer")
    assert memory.allowed_scopes("repo_1", [f"project:{project.project_id}"]) == []


def test_global_scope_is_terminology_only():
    memory = MemoryService(MemoryStateStore())
    with pytest.raises(ValueError, match="limited to terminology"):
        memory.propose(
            scope="global:terminology", type="decision", title="No", body="No",
            source_kind="documentation", source_ref="docs/x",
            author_kind="developer", author_id="developer",
        )


@pytest.mark.parametrize(
    "body",
    [
        "token=github_pat_abcdefghijklmnop",
        "api_key=abcdefghijklmnop",
        "-----BEGIN PRIVATE KEY-----",
    ],
)
def test_secret_like_memory_is_rejected_without_persistence(body: str):
    store = MemoryStateStore()
    with pytest.raises(MemoryServiceError, match="secret-like"):
        MemoryService(store).propose(
            scope="repo:repo_1", type="observation", title="Unsafe", body=body,
            source_kind="documentation", source_ref="docs/x", author_kind="worker",
            author_id="worker", observed=True,
        )
    assert store.list_memory_items() == []


def test_context_pack_profiles_and_conflict_audit():
    memory = MemoryService(MemoryStateStore())
    first = memory.propose(
        scope="repo:repo_1", type="terminology", title="Developer", body="Authorized person",
        source_kind="documentation", source_ref="docs/a", author_kind="developer",
        author_id="developer", aliases=["Cantor"],
    )
    approval = memory.request_approval(first.memory_id, "developer")
    memory.decide_approval(approval.approval_id, approve=True, actor="developer", note="ok")
    second = memory.propose(
        scope="repo:repo_1", type="terminology", title="Developer", body="A software author",
        source_kind="documentation", source_ref="docs/b", author_kind="worker",
        author_id="worker",
    )
    assert any(event["event_type"] == "conflict_detected" for event in memory.audit(second.memory_id))
    pack = memory.context_pack("resolve-reference", ["repo:repo_1"], "Developer")
    assert pack.profile == "resolve-reference"
    assert pack.estimated_tokens <= 750
    assert len([item for values in pack.sections.values() for item in values]) <= 5


@pytest.mark.parametrize("kind", ["memory", "sqlite"])
def test_concurrent_memory_approval_has_one_terminal_decision(kind: str, tmp_path: Path):
    memory = service(kind, tmp_path)
    item = memory.propose(
        scope="repo:repo_1", type="decision", title="Concurrent", body="One decision",
        source_kind="documentation", source_ref="docs/x", author_kind="developer",
        author_id="developer",
    )
    approval = memory.request_approval(item.memory_id, "developer")

    def decide(approve: bool):
        try:
            return memory.decide_approval(
                approval.approval_id, approve=approve, actor="developer", note="decision"
            ).status
        except MemoryServiceError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(decide, [True, False]))
    assert results.count("conflict") == 1
    assert memory.get(item.memory_id).status in {"active", "rejected"}


def test_retention_expires_observation_and_rejects_pending_proposal():
    store = MemoryStateStore()
    memory = MemoryService(store)
    observation = memory.propose(
        scope="repo:repo_1", type="observation", title="Old", body="Old observation",
        source_kind="documentation", source_ref="docs/x", author_kind="worker",
        author_id="worker", observed=True, low_value=True,
    )
    proposal = memory.propose(
        scope="repo:repo_1", type="decision", title="Pending", body="Old proposal",
        source_kind="documentation", source_ref="docs/x", author_kind="developer",
        author_id="developer",
    )
    approval = memory.request_approval(proposal.memory_id, "developer")
    old = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat().replace("+00:00", "Z")
    for item in (observation, proposal):
        raw = store.get_memory_item(item.memory_id)
        raw["created_at"] = old
        store.set_memory_item(item.memory_id, raw)
    expired = memory.run_retention()
    assert set(expired) == {observation.memory_id, proposal.memory_id}
    assert store.get_approval(approval.approval_id)["status"] == "rejected"


def test_orchestrator_auto_activates_governed_outcome_by_default():
    store = MemoryStateStore()
    store.set_job("job_1", {"job_id": "job_1", "status": "completed"})
    memory = MemoryService(store)
    item = memory.propose(
        scope="repo:repo_1",
        type="outcome",
        title="Worker A found fixture coverage",
        body="The migration fixture tests cover version one databases.",
        source_kind="job",
        source_ref="job_1",
        author_kind="worker",
        author_id="worker_a",
        confidence="supported",
    )
    assert item.status == "active"
    approval = store.get_approval(item.approval_id)
    assert approval["status"] == "approved"
    assert approval["decided_by"] == "orchestrator:local"
    events = memory.audit(item.memory_id)
    assert [event["event_type"] for event in events] == [
        "proposed", "approval_requested", "activated"
    ]
    assert json.loads(events[-1]["payload"]["note"])["policy"] == "bounded_orchestrator"


def test_orchestrator_does_not_auto_approve_high_authority_memory():
    memory = MemoryService(MemoryStateStore())
    item = memory.propose(
        scope="repo:repo_1",
        type="decision",
        title="Use Memory as source of truth",
        body="This would redefine architectural truth.",
        source_kind="documentation",
        source_ref="docs/x",
        author_kind="worker",
        author_id="worker_a",
    )
    assert item.status == "proposed"
    assert item.approval_id is None
    assert any(
        event["event_type"] == "orchestrator_activation_skipped"
        and "requires Developer approval" in event["payload"]["reason"]
        for event in memory.audit(item.memory_id)
    )


def test_orchestrator_does_not_auto_approve_conflicting_alias():
    store = MemoryStateStore()
    store.set_delegation_task("task_1", {"task_id": "task_1", "status": "accepted"})
    memory = MemoryService(store)
    existing = memory.propose(
        scope="repo:repo_1", type="terminology", title="Developer",
        body="The person governing work.", source_kind="delegation_task",
        source_ref="task_1", author_kind="developer", author_id="developer",
        confidence="verified", aliases=["Cantor"], auto_activate=False,
    )
    approval = memory.request_approval(existing.memory_id, "developer")
    memory.decide_approval(approval.approval_id, approve=True, actor="developer", note="ok")
    proposed = memory.propose(
        scope="repo:repo_1", type="terminology", title="Developer",
        body="A generic software author.", source_kind="delegation_task",
        source_ref="task_1", author_kind="worker", author_id="worker_a",
        confidence="verified", aliases=["Cantor"],
    )
    assert proposed.status == "proposed"
    event_types = [event["event_type"] for event in memory.audit(proposed.memory_id)]
    assert "conflict_detected" in event_types
    assert "orchestrator_activation_skipped" in event_types


def test_sqlite_v1_migrates_in_place_and_future_version_fails(tmp_path: Path):
    path = tmp_path / "state.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE schema_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO schema_meta VALUES ('schema_version', '1')")
        connection.execute("CREATE TABLE jobs(job_id TEXT PRIMARY KEY, status TEXT NOT NULL, value_json TEXT NOT NULL)")
        connection.execute("INSERT INTO jobs VALUES ('job_1', 'queued', '{}')")
    store = SqliteStateStore(path)
    assert store.ping()
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone() == ("2",)
        assert connection.execute("SELECT job_id FROM jobs").fetchone() == ("job_1",)
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='memory_items'").fetchone() == ("memory_items",)

    future = tmp_path / "future.db"
    with sqlite3.connect(future) as connection:
        connection.execute("CREATE TABLE schema_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO schema_meta VALUES ('schema_version', '99')")
    with pytest.raises(RuntimeError, match="Unsupported SQLite state schema version: 99"):
        SqliteStateStore(future).ping()


def test_failed_sqlite_migration_preserves_prior_version_and_data(tmp_path: Path):
    path = tmp_path / "broken-migration.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE schema_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO schema_meta VALUES ('schema_version', '1')")
        connection.execute("CREATE TABLE jobs(job_id TEXT PRIMARY KEY, status TEXT NOT NULL, value_json TEXT NOT NULL)")
        connection.execute("INSERT INTO jobs VALUES ('job_1', 'queued', '{\"job_id\":\"job_1\"}')")
        connection.execute("CREATE TABLE memory_items(memory_id TEXT PRIMARY KEY)")
    with pytest.raises(sqlite3.OperationalError, match="already exists"):
        SqliteStateStore(path).ping()
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone() == ("1",)
        assert connection.execute("SELECT job_id FROM jobs").fetchone() == ("job_1",)
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='memory_events'").fetchone() is None


def test_read_only_memory_inspection_does_not_create_wal(tmp_path: Path):
    path = tmp_path / "state.db"
    writable = SqliteStateStore(path)
    writable.ping()
    before = {
        suffix: (Path(f"{path}{suffix}").stat().st_size if Path(f"{path}{suffix}").exists() else None)
        for suffix in ("-wal", "-shm")
    }
    assert MemoryService(SqliteStateStore(path, read_only=True)).status()["items"] == 0
    after = {
        suffix: (Path(f"{path}{suffix}").stat().st_size if Path(f"{path}{suffix}").exists() else None)
        for suffix in ("-wal", "-shm")
    }
    assert after == before


def test_read_only_v1_state_reports_empty_memory_without_migrating(tmp_path: Path):
    path = tmp_path / "v1.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE schema_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO schema_meta VALUES ('schema_version', '1')")
    before = path.read_bytes()
    status = MemoryService(SqliteStateStore(path, read_only=True)).status()
    assert status == {"available": True, "items": 0, "active": 0, "proposed": 0, "projects": 0}
    assert path.read_bytes() == before
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT value FROM schema_meta").fetchone() == ("1",)
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='memory_items'").fetchone() is None
