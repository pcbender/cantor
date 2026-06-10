from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any

from canto.config import Settings
from canto.core.artifacts import ArtifactError, collect_artifacts
from canto.core.dependencies import check_dependencies
from canto.core.policy import PolicyDenied, evaluate_policy
from canto.core.registry import Registry
from canto.core.runner import RunnerError, run_provider
from canto.core.security import SensitiveInputError, validate_sensitive_inputs
from canto.core.state import StateStore
from canto.models.schemas import Approval, Job, JobRequest, utc_now


class JobError(ValueError):
    pass


def _id(prefix: str) -> str:
    compact = utc_now()[:10].replace("-", "")
    return f"{prefix}_{compact}_{secrets.token_hex(3)}"


class JobService:
    def __init__(self, settings: Settings, registry: Registry, store: StateStore):
        self.settings = settings
        self.registry = registry
        self.store = store
        self.settings.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.settings.scaffolds_dir.mkdir(parents=True, exist_ok=True)
        try:
            self.store.set_registry(registry.snapshot())
        except Exception:
            # The API can still expose a degraded health response before Redis starts.
            pass

    def _event(self, job_id: str, event_type: str, message: str, data: dict[str, Any] | None = None) -> None:
        self.store.append_event(
            job_id,
            {"timestamp": utc_now(), "type": event_type, "message": message, "data": data or {}},
        )

    def _refresh_registry(self) -> None:
        if self.registry.refresh_if_changed():
            self.store.set_registry(self.registry.snapshot())

    def _save(self, job: Job) -> None:
        job.updated_at = utc_now()
        self.store.set_job(job.job_id, job.model_dump(mode="json"))

    def _transition(self, job: Job, expected_statuses: set[str], status: str) -> bool:
        job.status = status
        job.updated_at = utc_now()
        return self.store.transition_job(job.job_id, expected_statuses, job.model_dump(mode="json"))

    def _validate_inputs(self, provider: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
        declarations = provider.get("inputs", {})
        unknown = set(values) - set(declarations)
        if unknown:
            raise JobError(f"Unknown provider inputs: {sorted(unknown)}")
        normalized: dict[str, Any] = {}
        for name, declaration in declarations.items():
            if name not in values:
                if "default" in declaration:
                    normalized[name] = declaration["default"]
                    continue
                if declaration.get("required"):
                    raise JobError(f"Missing required input: {name}")
                continue
            value = values[name]
            expected = declaration.get("type")
            valid = {
                "string": isinstance(value, str),
                "integer": isinstance(value, int) and not isinstance(value, bool),
                "boolean": isinstance(value, bool),
                "object": isinstance(value, dict),
                "array": isinstance(value, list),
            }.get(expected, True)
            if not valid:
                raise JobError(f"Input {name} must be {expected}")
            normalized[name] = value
        return normalized

    def missing_capability(self, request: JobRequest) -> dict[str, Any] | None:
        self._refresh_registry()
        if request.skill not in self.registry.skills:
            return {
                "status": "missing_skill",
                "skill": request.skill,
                "message": f"Skill {request.skill} is not installed.",
                "suggested_action": {
                    "skill": "scaffold_skill",
                    "provider": "local_scaffolder",
                    "inputs": {"skill": request.skill},
                    "requires_approval": True,
                },
            }
        if (request.skill, request.provider) not in self.registry.providers:
            return {
                "status": "missing_provider",
                "skill": request.skill,
                "provider": request.provider,
                "message": f"Provider {request.provider} is not installed for skill {request.skill}.",
                "suggested_action": {
                    "skill": "scaffold_provider",
                    "provider": "local_scaffolder",
                    "inputs": {"skill": request.skill, "provider": request.provider},
                    "requires_approval": True,
                },
            }
        return None

    def create_job(self, request: JobRequest) -> Job:
        self._refresh_registry()
        provider = self.registry.provider_internal(request.skill, request.provider)
        if not provider:
            raise JobError("Requested capability is not registered")
        inputs = self._validate_inputs(provider, request.inputs)
        try:
            validate_sensitive_inputs(inputs)
        except SensitiveInputError as exc:
            raise JobError(str(exc)) from exc
        linked_approval = None
        if request.approval_id:
            raw_approval = self.store.get_approval(request.approval_id)
            if not raw_approval:
                raise JobError(f"Unknown approval: {request.approval_id}")
            linked_approval = Approval.model_validate(raw_approval)
            if linked_approval.status != "approved":
                raise JobError(
                    f"Approval {request.approval_id} is {linked_approval.status}"
                )
        job_id = _id("job")
        artifact_dir = (self.settings.jobs_dir / job_id).resolve()
        artifact_dir.mkdir(parents=True, exist_ok=False)
        now = utc_now()
        job = Job(
            job_id=job_id,
            status="queued",
            created_at=now,
            updated_at=now,
            requested_by=request.requested_by,
            skill=request.skill,
            provider=request.provider,
            goal=request.goal,
            inputs=inputs,
            policy=request.policy,
            artifact_dir=str(artifact_dir),
            approval_id=request.approval_id,
            requires_approval=request.approval_id is not None,
        )
        if linked_approval:
            linked_approval.job_id = job_id
            self.store.set_approval(
                request.approval_id, linked_approval.model_dump(mode="json")
            )
        self._save(job)
        self._event(job_id, "job_created", "Job queued.")
        return job

    def process_job(self, job_id: str) -> Job:
        self._refresh_registry()
        raw = self.store.get_job(job_id)
        if not raw:
            raise JobError(f"Unknown job: {job_id}")
        job = Job.model_validate(raw)
        if job.status not in {"queued", "waiting_for_approval"}:
            return job
        provider = self.registry.provider_internal(job.skill, job.provider)
        if not provider:
            return self._fail(job, "provider_missing", "Provider disappeared from the registry")

        if job.status == "waiting_for_approval":
            approval = self.store.get_approval(job.approval_id or "")
            if not approval or approval.get("status") != "approved":
                return job
            if not self._transition(job, {"waiting_for_approval"}, "running"):
                return Job.model_validate(self.store.get_job(job_id))
        else:
            if not self._transition(job, {"queued"}, "checking_dependencies"):
                return Job.model_validate(self.store.get_job(job_id))
            self._event(job_id, "dependency_check_started", "Checking provider and tool dependencies.")
            tool_manifests = []
            for tool_name in provider.get("tools", []):
                tool = self.registry.tools.get(tool_name)
                if not tool:
                    return self._fail(job, "missing_tool", f"Provider requires unregistered tool {tool_name}")
                tool_manifests.append(tool)
            dependency_result = check_dependencies([provider, *tool_manifests])
            self._event(job_id, "dependency_check_completed", "Dependency check completed.", dependency_result)
            if dependency_result["status"] != "ready":
                job.status = "waiting_for_dependency"
                job.error = {"code": "missing_dependencies", **dependency_result}
                self._save(job)
                return job
            try:
                reasons = evaluate_policy(provider, job.inputs, job.policy)
            except PolicyDenied as exc:
                return self._fail(job, "policy_denied", str(exc))
            if reasons:
                if job.approval_id:
                    approval = self.store.get_approval(job.approval_id)
                    status = approval.get("status") if approval else None
                    if status == "approved":
                        if not self._transition(
                            job, {"checking_dependencies"}, "running"
                        ):
                            return Job.model_validate(self.store.get_job(job_id))
                    elif status == "rejected":
                        return self._fail(
                            job,
                            "approval_rejected",
                            "The linked approval was rejected",
                        )
                    else:
                        job.status = "waiting_for_approval"
                        job.requires_approval = True
                        self._save(job)
                        return job
                else:
                    approval_id = _id("approval")
                    approval = Approval(
                        approval_id=approval_id,
                        job_id=job_id,
                        skill=job.skill,
                        provider=job.provider,
                        reason="; ".join(reasons),
                        risk_level=int(provider.get("risk_level", 1)),
                        created_at=utc_now(),
                        updated_at=utc_now(),
                    )
                    self.store.set_approval(approval_id, approval.model_dump(mode="json"))
                    job.status = "waiting_for_approval"
                    job.requires_approval = True
                    job.approval_id = approval_id
                    self._save(job)
                    self._event(job_id, "approval_requested", approval.reason, {"approval_id": approval_id})
                    return job

            if job.status != "running" and not self._transition(
                job, {"checking_dependencies"}, "running"
            ):
                return Job.model_validate(self.store.get_job(job_id))

        job.error = None
        self._event(job_id, "provider_started", f"Running {job.skill}.{job.provider}.")
        payload = {
            "job_id": job.job_id,
            "skill": job.skill,
            "provider": job.provider,
            "inputs": job.inputs,
            "artifact_dir": job.artifact_dir,
            "canto_root": str(self.settings.root_dir.resolve()),
            "scaffolds_dir": str(self.settings.scaffolds_dir.resolve()),
        }
        try:
            result = run_provider(provider, payload, Path(job.artifact_dir), self.settings)
            artifacts = collect_artifacts(Path(job.artifact_dir), provider.get("outputs", {}))
        except (RunnerError, ArtifactError) as exc:
            details = exc.details if isinstance(exc, RunnerError) else {}
            return self._fail(job, "provider_failed", str(exc), details)
        self.store.set_artifacts(job_id, artifacts)
        job.status = "completed"
        job.result = result
        self._save(job)
        self._event(job_id, "artifacts_collected", f"Collected {len(artifacts)} artifacts.")
        self._event(job_id, "job_completed", result.get("summary", "Job completed."))
        return job

    def _fail(self, job: Job, code: str, message: str, details: dict[str, Any] | None = None) -> Job:
        job.status = "failed"
        job.error = {"code": code, "message": message, "details": details or {}}
        self._save(job)
        self._event(job.job_id, "job_failed", message, {"code": code})
        return job

    def approve(self, approval_id: str, approved_by: str, note: str) -> Job | Approval:
        raw = self.store.get_approval(approval_id)
        if not raw:
            raise JobError(f"Unknown approval: {approval_id}")
        approval = Approval.model_validate(raw)
        if approval.status != "pending":
            raise JobError(f"Approval is already {approval.status}")
        approval.status = "approved"
        approval.updated_at = utc_now()
        approval.decided_by = approved_by
        approval.note = note
        if not self.store.transition_approval(
            approval_id, {"pending"}, approval.model_dump(mode="json")
        ):
            current = self.store.get_approval(approval_id)
            status = current.get("status", "unknown") if current else "unknown"
            raise JobError(f"Approval is already {status}")
        if approval.job_id:
            self._event(approval.job_id, "approval_granted", "Cantor approved the job.", {"approved_by": approved_by})
            return self.process_job(approval.job_id)
        return approval

    def reject(self, approval_id: str, rejected_by: str, reason: str) -> Job | Approval:
        raw = self.store.get_approval(approval_id)
        if not raw:
            raise JobError(f"Unknown approval: {approval_id}")
        approval = Approval.model_validate(raw)
        if approval.status != "pending":
            raise JobError(f"Approval is already {approval.status}")
        approval.status = "rejected"
        approval.updated_at = utc_now()
        approval.decided_by = rejected_by
        approval.note = reason
        if not self.store.transition_approval(
            approval_id, {"pending"}, approval.model_dump(mode="json")
        ):
            current = self.store.get_approval(approval_id)
            status = current.get("status", "unknown") if current else "unknown"
            raise JobError(f"Approval is already {status}")
        if not approval.job_id:
            return approval
        job = Job.model_validate(self.store.get_job(approval.job_id))
        job.status = "rejected"
        job.error = {"code": "approval_rejected", "message": reason}
        self._save(job)
        self._event(job.job_id, "approval_rejected", reason, {"rejected_by": rejected_by})
        return job
