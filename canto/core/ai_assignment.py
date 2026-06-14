from __future__ import annotations

import subprocess
from pathlib import Path
from uuid import uuid4

from canto.core.ai_discovery import ModelCatalogService
from canto.core.ai_endpoints import AIEndpointService, endpoint_is_local
from canto.core.ai_selection import WorkerSelectionService, compose_worker_policy
from canto.core.ai_worker import APIWorkerError, APIWorkerHarness
from canto.core.delegation import DelegationError, DelegationService
from canto.core.delegation_workspace import DelegationWorkspaceService
from canto.models.ai_workers import (
    EndpointHealthRecord,
    WorkerSelectionPolicy,
    WorkerUsageRecord,
)
from canto.models.delegation import ExecutorLaunch, ExecutorSession
from canto.models.schemas import utc_now


class WorkerAssignmentError(DelegationError):
    pass


class AIWorkerAssignmentService:
    def __init__(
        self,
        delegation: DelegationService,
        workspaces: DelegationWorkspaceService,
        endpoints: AIEndpointService,
        catalog: ModelCatalogService,
        selection: WorkerSelectionService,
        harness: APIWorkerHarness,
    ):
        self.delegation = delegation
        self.workspaces = workspaces
        self.endpoints = endpoints
        self.catalog = catalog
        self.selection = selection
        self.harness = harness

    def launch(
        self,
        task_id: str,
        policy: WorkerSelectionPolicy | None = None,
    ) -> ExecutorLaunch:
        task = self.delegation.get_task(task_id)
        if task.status not in {"workspace_ready", "revision_requested"}:
            raise WorkerAssignmentError(
                "AI Worker launch requires a workspace_ready or revision_requested task"
            )
        base_policy = policy or WorkerSelectionPolicy(priority=task.worker_priority)
        effective = compose_worker_policy(base_policy, task.worker_policy)
        endpoint_map = {item.endpoint_id: item for item in self.endpoints.list()}
        models = self.catalog.list()
        remaining = [
            model
            for model in models
            if not effective.allowed_models or model.model_key in effective.allowed_models
        ]
        first = True
        last_error = "No eligible AI Worker"
        while remaining:
            attempt_policy = effective.model_copy(
                update={"allowed_models": [item.model_key for item in remaining]}
            )
            decision = self.selection.select(
                task_id, remaining, endpoint_map, attempt_policy
            )
            if not decision.selected_model_key:
                break
            model = self.catalog.get(decision.selected_model_key)
            endpoint = endpoint_map[model.endpoint_id]
            if not first and not endpoint_is_local(endpoint) and not effective.cloud_fallback_allowed:
                break
            task = self._record_selection(task_id, decision.decision_id, model.model_key)
            workspace_state = self._workspace_state(task_id)
            try:
                return self._run_attempt(task, model, endpoint, effective)
            except Exception as exc:
                last_error = str(exc)
                if self._workspace_state(task_id) != workspace_state:
                    last_error += "; fallback stopped because the failed Worker changed the Workspace"
                    break
                remaining = [item for item in remaining if item.model_key != model.model_key]
                first = False
        current = self.delegation.get_task(task_id)
        if current.status == "executor_working":
            self.delegation.transition(
                task_id, "failed", details={"error": last_error, "harness": "api_worker"}
            )
        raise WorkerAssignmentError(last_error)

    def _record_selection(self, task_id: str, decision_id: str, model_key: str):
        current = self.delegation.get_task(task_id)
        updates = {
            "selection_decision_id": decision_id,
            "selected_model_key": model_key,
            "executor_id": f"ai:{model_key}",
        }
        if current.status in {"workspace_ready", "revision_requested"}:
            return self.delegation.transition(
                task_id,
                "executor_working",
                updates=updates,
                details={"harness": "api_worker", **updates},
            )
        value = current.model_copy(update={**updates, "updated_at": utc_now()})
        self.delegation.store.set_delegation_task(
            task_id, value.model_dump(mode="json")
        )
        return value

    def _run_attempt(self, task, model, endpoint, policy):
        workspace = self.workspaces.get(task.task_id)
        path = Path(workspace.path)
        artifact_dir = path.parent / "artifacts"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        session_id = f"session_{uuid4().hex}"
        launch_id = f"launch_{uuid4().hex}"
        prompt = self._prompt(task)
        prompt_path = artifact_dir / f"{launch_id}.prompt.md"
        stdout_path = artifact_dir / f"{launch_id}.stdout.log"
        stderr_path = artifact_dir / f"{launch_id}.stderr.log"
        prompt_path.write_text(prompt, encoding="utf-8")
        session = ExecutorSession(
            session_id=session_id,
            task_id=task.task_id,
            executor_id=f"ai:{model.model_key}",
            status="running",
            enforcement="canto_observed",
            started_at=utc_now(),
        )
        self.delegation.append_record(task.task_id, "sessions", session)
        launch = ExecutorLaunch(
            launch_id=launch_id,
            task_id=task.task_id,
            session_id=session_id,
            executor_id=session.executor_id,
            argv=["canto-api-worker", model.model_key],
            cwd=str(path),
            prompt_path=str(prompt_path),
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
        )
        started = __import__("time").monotonic()
        try:
            usage, summary = self.harness.run(
                task_id=task.task_id,
                session_id=session_id,
                model=model,
                endpoint=endpoint,
                credential=self.endpoints.credential(endpoint),
                prompt=prompt,
                workspace=path,
                scope=task.scope,
                budget=policy.budget,
            )
            usage.decision_id = task.selection_decision_id
            self._price(usage, model)
            self._record_usage(task.task_id, usage)
            stdout_path.write_text(summary, encoding="utf-8")
            stderr_path.write_text("", encoding="utf-8")
            launch = launch.model_copy(
                update={
                    "token_usage": {
                        "input": usage.input_tokens,
                        "output": usage.output_tokens,
                    },
                    "exit_code": 0,
                    "ended_at": utc_now(),
                }
            )
            self.delegation.append_record(task.task_id, "launches", launch)
            self._health(endpoint.endpoint_id, True, "Worker completed", started)
            self.delegation.transition(
                task.task_id,
                "executor_done",
                details={"launch_id": launch_id, "model_key": model.model_key},
            )
            return launch
        except Exception as exc:
            partial_usage = getattr(exc, "usage", None)
            if partial_usage is not None:
                partial_usage.decision_id = task.selection_decision_id
                partial_usage.terminal_reason = "worker_failed"
                partial_usage.ended_at = utc_now()
                self._price(partial_usage, model)
                self._record_usage(task.task_id, partial_usage)
            stderr_path.write_text(str(exc), encoding="utf-8")
            launch = launch.model_copy(update={"exit_code": 1, "ended_at": utc_now()})
            self.delegation.append_record(task.task_id, "launches", launch)
            self._health(endpoint.endpoint_id, False, str(exc), started)
            raise

    def _record_usage(self, task_id: str, usage: WorkerUsageRecord) -> None:
        self.delegation.store.set_ai_record(
            "usage", usage.usage_id, usage.model_dump(mode="json")
        )
        self.delegation.append_record(task_id, "worker_usage", usage)

    def _health(self, endpoint_id: str, available: bool, detail: str, started: float):
        import time

        record = EndpointHealthRecord(
            health_id=f"health_{uuid4().hex}",
            endpoint_id=endpoint_id,
            available=available,
            detail=detail,
            latency_ms=(time.monotonic() - started) * 1000,
        )
        self.delegation.store.set_ai_record(
            "endpoint_health", record.health_id, record.model_dump(mode="json")
        )

    @staticmethod
    def _price(usage: WorkerUsageRecord, model) -> None:
        pricing = model.pricing
        if model.provider == "ollama":
            usage.estimated_cost_usd = usage.actual_cost_usd = 0.0
        elif pricing.input_per_million is not None and pricing.output_per_million is not None:
            cost = (
                (usage.input_tokens - usage.cached_input_tokens) * pricing.input_per_million
                + usage.cached_input_tokens * (pricing.cached_input_per_million or pricing.input_per_million)
                + usage.output_tokens * pricing.output_per_million
            ) / 1_000_000
            usage.actual_cost_usd = usage.estimated_cost_usd = cost

    def _workspace_state(self, task_id: str) -> str:
        path = self.workspaces.get(task_id).path
        completed = subprocess.run(
            ["git", "-C", path, "status", "--porcelain"],
            text=True,
            capture_output=True,
            check=False,
        )
        return completed.stdout

    @staticmethod
    def _prompt(task) -> str:
        return (
            "You are a Canto delegated Worker. Work only in the bounded Workspace. "
            "Do not commit, push, self-accept, or Apply.\n\n"
            f"Assignment: {task.title}\n\n{task.instructions}\n"
        )
