from __future__ import annotations

from datetime import datetime, timedelta, timezone

from canto.core.jobs import JobService
from canto.core.memory import MemoryService


def test_governed_memory_end_to_end(runtime):
    settings, registry, store, _ = runtime
    memory = MemoryService(store)

    project = memory.create_project("Canto dogfood", "developer")
    memory.link_repository(project.project_id, "repo_canto", "developer")
    scope = f"project:{project.project_id}"

    terminology = memory.propose(
        scope=scope,
        type="terminology",
        title="Worker",
        body="The governed agent performing assigned work.",
        source_kind="documentation",
        source_ref="docs/architecture-language-lexicon.md",
        author_kind="developer",
        author_id="developer",
        confidence="verified",
        aliases=["Executor"],
    )
    approval = memory.request_approval(terminology.memory_id, "developer")
    activated = JobService(settings, registry, store).approve(
        approval.approval_id, "developer", "approved"
    )
    assert activated.status == "active"

    scopes = memory.allowed_scopes("repo_canto", [scope, "global:terminology"])
    assert memory.resolve("Executor", scopes).items[0].memory_id == terminology.memory_id
    pack = memory.context_pack("startup", scopes, "Worker")
    assert pack.sections["glossary"][0].memory_id == terminology.memory_id

    store.set_job("job_1", {"job_id": "job_1", "status": "completed"})
    outcome = memory.propose(
        scope=scope,
        type="outcome",
        title="Memory dogfood completed",
        body="The governed memory flow completed in the test runtime.",
        source_kind="job",
        source_ref="job_1",
        author_kind="worker",
        author_id="worker_test",
        confidence="supported",
    )
    assert outcome.status == "active"
    assert store.get_approval(outcome.approval_id)["decided_by"] == "orchestrator:local"

    replacement = memory.propose(
        scope=scope,
        type="terminology",
        title="Worker",
        body="The governed local or cloud agent performing bounded assigned work.",
        source_kind="documentation",
        source_ref="docs/architecture-language-lexicon.md",
        author_kind="developer",
        author_id="developer",
        confidence="verified",
        aliases=["Executor"],
    )
    replacement_approval = memory.request_approval(replacement.memory_id, "developer")
    memory.decide_approval(
        replacement_approval.approval_id,
        approve=True,
        actor="developer",
        note="updated",
    )
    memory.supersede(terminology.memory_id, replacement.memory_id, "developer")

    old_observation = memory.propose(
        scope=scope,
        type="observation",
        title="Temporary observation",
        body="This observation should expire.",
        source_kind="documentation",
        source_ref="docs/memory-service.md",
        author_kind="worker",
        author_id="worker_test",
        confidence="observed",
        observed=True,
        low_value=True,
    )
    raw = store.get_memory_item(old_observation.memory_id)
    raw["created_at"] = (
        datetime.now(timezone.utc) - timedelta(days=8)
    ).isoformat().replace("+00:00", "Z")
    store.set_memory_item(old_observation.memory_id, raw)
    assert memory.run_retention() == [old_observation.memory_id]

    exported = memory.export()
    assert {item["memory_id"] for item in exported} >= {
        terminology.memory_id,
        replacement.memory_id,
        outcome.memory_id,
    }
    assert any(event["event_type"] == "superseded" for event in memory.audit(terminology.memory_id))


def test_cross_worker_shared_memory_with_bounded_orchestrator_approval(runtime):
    _, _, store, _ = runtime
    memory = MemoryService(store)
    project = memory.create_project("Cross worker dogfood", "developer")
    memory.link_repository(project.project_id, "repo_canto", "developer")
    scope = f"project:{project.project_id}"

    store.set_delegation_task("task_worker_a", {"task_id": "task_worker_a", "status": "accepted"})
    store.set_delegation_task("task_worker_b", {"task_id": "task_worker_b", "status": "workspace_ready"})
    store.append_delegation_record(
        "task_worker_a", "sessions", "session_worker_a",
        {"session_id": "session_worker_a", "task_id": "task_worker_a"},
    )
    store.append_delegation_record(
        "task_worker_b", "sessions", "session_worker_b",
        {"session_id": "session_worker_b", "task_id": "task_worker_b"},
    )

    approved = memory.propose(
        scope=scope,
        type="source_pointer",
        title="Migration fixture source",
        body="Worker A found the canonical migration fixture notes.",
        source_kind="delegation_task",
        source_ref="task_worker_a",
        author_kind="worker",
        author_id="session_worker_a",
        confidence="supported",
        tags=["migration", "fixtures"],
    )
    assert approved.status == "active"
    assert store.get_approval(approved.approval_id)["decided_by"] == "orchestrator:local"

    pending = memory.propose(
        scope=scope,
        type="decision",
        title="Make fixture source authoritative",
        body="This decision must remain pending for Developer review.",
        source_kind="delegation_task",
        source_ref="task_worker_a",
        author_kind="worker",
        author_id="session_worker_a",
        confidence="supported",
    )
    assert pending.status == "proposed"

    out_of_scope = memory.propose(
        scope="repo:other_repo",
        type="source_pointer",
        title="Other repo source",
        body="Worker B must not see this.",
        source_kind="delegation_task",
        source_ref="task_worker_a",
        author_kind="worker",
        author_id="session_worker_a",
        confidence="supported",
    )
    assert out_of_scope.status == "active"

    worker_b_scopes = memory.allowed_scopes("repo_canto", [scope, "repo:other_repo"])
    pack = memory.context_pack("startup", worker_b_scopes, "fixture source")
    visible = [item for items in pack.sections.values() for item in items]
    assert [item.memory_id for item in visible] == [approved.memory_id]
    assert pending.memory_id not in {item.memory_id for item in visible}
    assert out_of_scope.memory_id not in {item.memory_id for item in visible}
