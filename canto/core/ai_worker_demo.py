from __future__ import annotations

import tempfile
from pathlib import Path

from pydantic import BaseModel

from canto.core.ai_assignment import AIWorkerAssignmentService
from canto.core.ai_discovery import ModelCatalogService
from canto.core.ai_endpoints import AIEndpointService
from canto.core.ai_selection import WorkerSelectionService
from canto.core.ai_worker import APIWorkerHarness, AgentResponse, AgentToolCall
from canto.core.credentials import CredentialVault
from canto.core.delegation import DelegationService
from canto.core.delegation_artifacts import DelegationArtifactService
from canto.core.delegation_commands import DelegationCommandService
from canto.core.delegation_demo import cleanup_delegation_demo
from canto.core.delegation_promotion import DelegationPromotionService
from canto.core.delegation_review import DelegationReviewService
from canto.core.delegation_workspace import DelegationWorkspaceService, inspect_repository
from canto.core.repository import initialize_repository
from canto.core.state import SqliteStateStore
from canto.models.ai_workers import AIModelRecord, WorkerSelectionPolicy
from canto.models.delegation import DelegationScope, DelegationTask


class AIWorkerPoolDemoResult(BaseModel):
    root: str
    task_id: str
    model_key: str
    selection_decision_id: str
    status: str
    result_revision: int
    actual_cost_usd: float
    cleaned_up: bool = False


class ScriptedAgentAdapter:
    def __init__(self):
        self.turn = 0

    def complete(self, endpoint, credential, model_id, messages, tools):
        self.turn += 1
        if self.turn == 1:
            return AgentResponse(
                tool_calls=[
                    AgentToolCall(
                        "edit-1",
                        "write_file",
                        {"path": "src/app.py", "content": "value = 2\n"},
                    )
                ],
                input_tokens=20,
                output_tokens=10,
            )
        return AgentResponse(text="Changed value to 2.", input_tokens=5, output_tokens=5)


def _git(repository: Path, *args: str) -> None:
    import subprocess

    subprocess.run(
        ["git", "-C", str(repository), *args], capture_output=True, check=True
    )


def run_ai_worker_pool_demo(*, apply: bool = False, keep: bool = False):
    root = Path(tempfile.mkdtemp(prefix="canto-ai-worker-demo-")).resolve()
    repository = root / "repository"
    repository.mkdir()
    _git(repository, "init", "-q")
    _git(repository, "config", "user.email", "demo@example.com")
    _git(repository, "config", "user.name", "Canto Demo")
    (repository / "src").mkdir()
    (repository / "src" / "app.py").write_text("value = 1\n", encoding="utf-8")
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", "initial")
    initialize_repository(repository)
    _git(repository, "add", "AGENTS.md", ".canto")
    _git(repository, "commit", "-m", "bootstrap canto")

    home = root / "canto-home"
    store = SqliteStateStore(home / "state.sqlite")
    delegation = DelegationService(store)
    workspaces = DelegationWorkspaceService(
        delegation, home / "work" / "delegations"
    )
    endpoints = AIEndpointService(
        store, CredentialVault(home / "vault"), home / "config" / "ai-endpoints.yaml"
    )
    endpoints.add("demo-local", "ollama", "http://localhost:11434")
    model = AIModelRecord(
        model_key="demo-local:canto-scripted-coder",
        endpoint_id="demo-local",
        provider="ollama",
        provider_model_id="canto-scripted-coder",
        resolved_version="demo-v1",
        classification="implementation",
        probe_version="1",
        probe_stale=False,
        catalog_checksum="demo",
    )
    store.set_ai_record("model", model.model_key, model.model_dump(mode="json"))
    task_id = "task_ai_worker_demo"
    delegation.create_task(
        DelegationTask(
            task_id=task_id,
            title="Governed AI Worker pool demo",
            instructions="Change src/app.py value from 1 to 2.",
            repository=inspect_repository(repository),
            scope=DelegationScope(
                allowed_paths=["src"],
                denied_paths=[".env"],
                allowed_commands=["git diff --check"],
                required_commands=["git diff --check"],
            ),
        )
    )
    delegation.transition(task_id, "assigned")
    workspaces.prepare(task_id)
    assignment = AIWorkerAssignmentService(
        delegation,
        workspaces,
        endpoints,
        ModelCatalogService(store, endpoints),
        WorkerSelectionService(store),
        APIWorkerHarness(ScriptedAgentAdapter()),
    )
    assignment.launch(task_id, WorkerSelectionPolicy())
    DelegationCommandService(delegation, workspaces).run(
        task_id, "git diff --check"
    )
    result = DelegationArtifactService(delegation, workspaces).capture(task_id)
    DelegationReviewService(delegation, workspaces).accept(
        task_id, "demo-developer"
    )
    if apply:
        DelegationPromotionService(delegation, workspaces).promote(
            task_id, "demo-developer"
        )
    task = delegation.get_task(task_id)
    usage = store.list_ai_records("usage")[-1]
    value = AIWorkerPoolDemoResult(
        root=str(root),
        task_id=task_id,
        model_key=task.selected_model_key or "",
        selection_decision_id=task.selection_decision_id or "",
        status=task.status,
        result_revision=result.revision,
        actual_cost_usd=usage["actual_cost_usd"],
    )
    if not keep:
        cleanup_delegation_demo(root)
        value = value.model_copy(update={"cleaned_up": True})
    return value

