from __future__ import annotations

from fastapi import BackgroundTasks, FastAPI, HTTPException

from canto import __version__
from canto.config import Settings, get_settings
from canto.core.artifacts import ArtifactError, read_artifact
from canto.core.jobs import JobError, JobService
from canto.core.local_registry import Registry as CapabilityRegistry
from canto.core.registry import Registry
from canto.core.state import RedisStateStore, StateStore
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
    store = store or RedisStateStore(settings.redis_url)
    service = JobService(settings, registry, store)

    app = FastAPI(title="Canto", version=__version__)
    app.state.settings = settings
    app.state.registry = registry
    app.state.capability_registry = capability_registry
    app.state.store = store
    app.state.service = service

    @app.get("/health")
    def health() -> dict[str, str]:
        try:
            redis_status = "ok" if store.ping() else "error"
        except Exception:
            redis_status = "error"
        return {"status": "ok" if redis_status == "ok" else "degraded", "redis": redis_status, "version": __version__}

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

    @app.get("/jobs/{job_id}")
    def get_job(job_id: str) -> dict:
        result = store.get_job(job_id)
        if not result:
            raise HTTPException(404, f"Unknown job: {job_id}")
        return result

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
