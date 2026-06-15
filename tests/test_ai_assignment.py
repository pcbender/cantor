from __future__ import annotations

import subprocess

from canto.core.ai_assignment import AIWorkerAssignmentService
from canto.core.ai_discovery import ModelCatalogService
from canto.core.ai_endpoints import AIEndpointService
from canto.core.ai_selection import WorkerSelectionService
from canto.core.ai_worker import APIWorkerHarness, AgentResponse, AgentToolCall
from canto.core.credentials import CredentialVault
from canto.core.delegation import DelegationService
from canto.core.state import MemoryStateStore
from canto.models.ai_workers import AIModelRecord, WorkerSelectionPolicy
from canto.models.delegation import (
    DelegationScope,
    DelegationTask,
    DelegationWorkspace,
    RepositoryIdentity,
)


class Workspaces:
    def __init__(self, workspace):
        self.workspace = workspace

    def get(self, task_id):
        return self.workspace


class Adapter:
    def __init__(self):
        self.turns = {}

    def complete(self, endpoint, credential, model_id, messages, tools):
        turn = self.turns.get(model_id, 0)
        self.turns[model_id] = turn + 1
        if turn == 0:
            return AgentResponse(tool_calls=[AgentToolCall("1", "write_file", {"path": "src/result.txt", "content": model_id})])
        return AgentResponse(text="done", input_tokens=5, output_tokens=2)


def setup(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Test User"], check=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "base.txt").write_text("base\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-q", "-m", "base"], check=True)
    base_commit = subprocess.run(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    store = MemoryStateStore()
    delegation = DelegationService(store)
    repo = RepositoryIdentity(canonical_path=str(tmp_path), initial_head=base_commit)
    task = delegation.create_task(
        DelegationTask(
            task_id="task-1",
            title="Implement fixture",
            repository=repo,
            scope=DelegationScope(allowed_paths=["src"]),
            instructions="Create the requested result.",
        )
    )
    delegation.transition(task.task_id, "assigned")
    workspace = DelegationWorkspace(
        workspace_id="workspace-1",
        task_id=task.task_id,
        path=str(tmp_path),
        branch="test",
        base_commit=base_commit,
        repository=repo,
        allowed_paths=["src"],
    )
    delegation.append_record(task.task_id, "workspaces", workspace)
    delegation.transition(task.task_id, "workspace_ready", updates={"workspace_id": workspace.workspace_id})
    canto_home = tmp_path.parent / f"{tmp_path.name}-canto-home"
    endpoints = AIEndpointService(
        store,
        CredentialVault(canto_home / "vault"),
        canto_home / "config" / "ai.yaml",
    )
    endpoints.add("local", "ollama", "http://localhost:11434")
    model = AIModelRecord(
        model_key="local:coder",
        endpoint_id="local",
        provider="ollama",
        provider_model_id="coder",
        resolved_version="digest",
        classification="implementation",
        probe_version="1",
        probe_stale=False,
        probe_state="current",
        availability="available",
        catalog_checksum="checksum",
    )
    store.set_ai_record("model", model.model_key, model.model_dump(mode="json"))
    catalog = ModelCatalogService(store, endpoints)
    service = AIWorkerAssignmentService(
        delegation,
        Workspaces(workspace),
        endpoints,
        catalog,
        WorkerSelectionService(store),
        APIWorkerHarness(Adapter()),
    )
    return store, delegation, service


def test_assignment_uses_existing_delegation_lifecycle_and_records_usage(tmp_path):
    store, delegation, service = setup(tmp_path)

    launch = service.launch("task-1", WorkerSelectionPolicy())

    task = delegation.get_task("task-1")
    assert task.status == "executor_done"
    assert task.selected_model_key == "local:coder"
    assert launch.argv == ["canto-api-worker", "local:coder"]
    assert launch.outcome == "completed_work"
    assert launch.workspace_changed is True
    assert (tmp_path / "src" / "result.txt").read_text() == "coder"
    assert store.list_ai_records("usage")[0]["resolved_version"] == "digest"
    assert store.list_ai_records("endpoint_health")[0]["available"] is True


def test_local_failure_uses_explicitly_authorized_cloud_fallback(tmp_path):
    store, delegation, service = setup(tmp_path)
    service.endpoints.add(
        "cloud", "openai", "https://api.openai.com", api_key="secret"
    )
    cloud = AIModelRecord(
        model_key="cloud:coder",
        endpoint_id="cloud",
        provider="openai",
        provider_model_id="cloud-coder",
        resolved_version="2026-01-01",
        classification="implementation",
        probe_version="1",
        probe_stale=False,
        probe_state="current",
        availability="available",
        catalog_checksum="cloud-checksum",
    )
    store.set_ai_record("model", cloud.model_key, cloud.model_dump(mode="json"))

    class FailLocal(Adapter):
        def complete(self, endpoint, credential, model_id, messages, tools):
            if endpoint.provider == "ollama":
                raise RuntimeError("local unavailable")
            return super().complete(endpoint, credential, model_id, messages, tools)

    service.harness = APIWorkerHarness(FailLocal())

    launch = service.launch(
        "task-1",
        WorkerSelectionPolicy(cloud_allowed=True, cloud_fallback_allowed=True),
    )

    assert launch.executor_id == "ai:cloud:coder"
    assert delegation.get_task("task-1").selected_model_key == "cloud:coder"
    assert len(store.list_ai_records("selection")) == 2


def test_api_worker_advisory_output_does_not_imply_completed_work(tmp_path):
    _, delegation, service = setup(tmp_path)

    class Advisory:
        def complete(self, endpoint, credential, model_id, messages, tools):
            return AgentResponse(text="I would edit src/result.txt.")

    service.harness = APIWorkerHarness(Advisory())

    launch = service.launch("task-1", WorkerSelectionPolicy())

    assert launch.outcome == "advisory"
    assert launch.workspace_changed is False
    assert delegation.get_task("task-1").status == "executor_done"
