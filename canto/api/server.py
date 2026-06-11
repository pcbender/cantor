from __future__ import annotations

from fastapi import BackgroundTasks, FastAPI, HTTPException, status

from canto import __version__
from canto.config import Settings, get_settings
from canto.core.artifacts import ArtifactError, read_artifact
from canto.core.jobs import JobError, JobService
from canto.core.local_registry import Registry as CapabilityRegistry
from canto.core.orchestration import (
    CapabilityMatcher,
    DiscoverRequest,
    DiscoverResponse,
    ExecutionPlan,
    OrchestrationError,
    Orchestrator,
    PlanCreateRequest,
    PlanEventsResponse,
    PlanExecutionAccepted,
    PlanExplanation,
    PlanStore,
)
from canto.core.registry import Registry
from canto.core.state import SqliteStateStore, StateStore
from canto.models.schemas import ApprovalDecision, JobRequest, RejectionDecision


def create_app(
    settings: Settings | None = None,
    store: StateStore | None = None,
    capability_registry: CapabilityRegistry | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    capability_registry = capability_registry or CapabilityRegistry.local()
    registry = Registry(
        settings.skills_dir,
        settings.tools_dir,
        capability_registry=capability_registry,
    )
    store = store or SqliteStateStore(
        capability_registry.store.paths.root / "state" / "canto.db"
    )
    service = JobService(settings, registry, store)
    orchestrator = Orchestrator(
        capability_registry,
        PlanStore(store),
        job_service=service,
    )

    app = FastAPI(title="Canto", version=__version__)
    app.state.settings = settings
    app.state.registry = registry
    app.state.capability_registry = capability_registry
    app.state.store = store
    app.state.service = service
    app.state.orchestrator = orchestrator

    @app.get("/health")
    def health() -> dict[str, str]:
        try:
            state_status = "ok" if store.ping() else "error"
        except Exception:
            state_status = "error"
        return {
            "status": "ok" if state_status == "ok" else "degraded",
            "state": state_status,
            "redis": "not_required",
            "version": __version__,
        }

    @app.get("/registry")
    def registry_snapshot() -> dict:
        return registry.snapshot()

    @app.get("/skills/{skill_name}")
    def get_skill(skill_name: str) -> dict:
        result = registry.get_skill(skill_name)
        if not result:
            raise HTTPException(404, f"Unknown skill: {skill_name}")
        return result

    @app.get("/skills/{skill_name}/providers/{provider_name}")
    def get_provider(skill_name: str, provider_name: str) -> dict:
        result = registry.get_provider(skill_name, provider_name)
        if not result:
            raise HTTPException(404, f"Unknown provider: {skill_name}.{provider_name}")
        return result

    @app.post("/jobs")
    def create_job(request: JobRequest, background_tasks: BackgroundTasks) -> dict:
        missing = service.missing_capability(request)
        if missing:
            return missing
        try:
            job = service.create_job(request)
        except JobError as exc:
            raise HTTPException(422, str(exc)) from exc
        background_tasks.add_task(service.process_job, job.job_id)
        return {"job_id": job.job_id, "status": job.status}

    @app.post("/discover", response_model=DiscoverResponse)
    def discover(request: DiscoverRequest) -> DiscoverResponse:
        matches = CapabilityMatcher(capability_registry).discover(request.goal)
        return DiscoverResponse(
            goal=request.goal,
            matches=matches[: request.limit],
        )

    @app.post("/plans", response_model=ExecutionPlan)
    def create_plan(request: PlanCreateRequest) -> ExecutionPlan:
        try:
            return orchestrator.create_plan(request.goal, inputs=request.inputs)
        except OrchestrationError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/plans/{plan_id}", response_model=ExecutionPlan)
    def get_plan(plan_id: str) -> ExecutionPlan:
        try:
            return orchestrator.get_plan(plan_id)
        except OrchestrationError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get("/plans/{plan_id}/explain", response_model=PlanExplanation)
    def explain_plan(plan_id: str) -> PlanExplanation:
        try:
            return orchestrator.explain(plan_id)
        except OrchestrationError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/plans/{plan_id}/approve", response_model=ExecutionPlan)
    def approve_plan(plan_id: str, decision: ApprovalDecision) -> ExecutionPlan:
        try:
            return orchestrator.approve_plan(
                plan_id, decision.approved_by, decision.note
            )
        except OrchestrationError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post(
        "/plans/{plan_id}/execute",
        response_model=PlanExecutionAccepted,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def execute_plan(
        plan_id: str, background_tasks: BackgroundTasks
    ) -> PlanExecutionAccepted:
        try:
            accepted = orchestrator.prepare_execution(plan_id)
        except OrchestrationError as exc:
            raise HTTPException(409, str(exc)) from exc
        background_tasks.add_task(orchestrator.execute, plan_id)
        return accepted

    @app.get("/plans/{plan_id}/events", response_model=PlanEventsResponse)
    def plan_events(plan_id: str) -> PlanEventsResponse:
        try:
            return orchestrator.events(plan_id)
        except OrchestrationError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get("/jobs/{job_id}")
    def get_job(job_id: str) -> dict:
        result = store.get_job(job_id)
        if not result:
            raise HTTPException(404, f"Unknown job: {job_id}")
        return result

    @app.post("/jobs/{job_id}/promote")
    def promote_job(job_id: str) -> dict:
        try:
            approval = service.promote(job_id)
        except JobError as exc:
            raise HTTPException(409, str(exc)) from exc
        return approval.model_dump(mode="json")

    @app.post("/jobs/{job_id}/recover")
    def recover_job(job_id: str) -> dict:
        try:
            approval = service.recover(job_id)
        except JobError as exc:
            raise HTTPException(409, str(exc)) from exc
        return approval.model_dump(mode="json")

    @app.get("/jobs/{job_id}/events")
    def get_events(job_id: str) -> dict:
        if not store.get_job(job_id):
            raise HTTPException(404, f"Unknown job: {job_id}")
        return {"job_id": job_id, "events": store.get_events(job_id)}

    @app.get("/jobs/{job_id}/artifacts")
    def get_artifacts(job_id: str) -> dict:
        if not store.get_job(job_id):
            raise HTTPException(404, f"Unknown job: {job_id}")
        return {"job_id": job_id, "artifacts": store.get_artifacts(job_id)}

    @app.get("/jobs/{job_id}/artifacts/{artifact_name}")
    def get_artifact(job_id: str, artifact_name: str) -> dict:
        artifact = next((item for item in store.get_artifacts(job_id) if item["name"] == artifact_name), None)
        if not artifact:
            raise HTTPException(404, f"Unknown artifact: {artifact_name}")
        try:
            return read_artifact(artifact)
        except ArtifactError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/approvals/{approval_id}/approve")
    def approve(approval_id: str, decision: ApprovalDecision) -> dict:
        try:
            job = service.approve(approval_id, decision.approved_by, decision.note)
        except JobError as exc:
            raise HTTPException(409, str(exc)) from exc
        return job.model_dump(mode="json")

    @app.post("/approvals/{approval_id}/reject")
    def reject(approval_id: str, decision: RejectionDecision) -> dict:
        try:
            job = service.reject(approval_id, decision.rejected_by, decision.reason)
        except JobError as exc:
            raise HTTPException(409, str(exc)) from exc
        return job.model_dump(mode="json")

    return app


app = create_app()
