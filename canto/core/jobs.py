from __future__ import annotations

import hashlib
import json
import secrets
from pathlib import Path
from typing import Any

from canto.config import Settings
from canto.core.artifacts import ArtifactError, collect_artifacts
from canto.core.dependencies import check_dependencies
from canto.core.credentials import (
    CredentialError,
    CredentialVault,
    resolve_credential_inputs,
)
from canto.core.policy import PolicyDenied, evaluate_policy
from canto.core.registry import Registry
from canto.core.runner import RunnerError, effective_limits, run_provider
from canto.core.security import (
    SensitiveInputError,
    redact_artifacts,
    validate_sensitive_inputs,
)
from canto.core.state import StateStore
from canto.models.schemas import Approval, Job, JobRequest, utc_now


class JobError(ValueError):
    pass


def _id(prefix: str) -> str:
    compact = utc_now()[:10].replace("-", "")
    return f"{prefix}_{compact}_{secrets.token_hex(3)}"


class JobService:
    def __init__(
        self,
        settings: Settings,
        registry: Registry,
        store: StateStore,
        vault: CredentialVault | None = None,
    ):
        self.settings = settings
        self.registry = registry
        self.store = store
        self.vault = vault
        self.settings.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.settings.scaffolds_dir.mkdir(parents=True, exist_ok=True)
        try:
            self.store.set_registry(registry.snapshot())
        except Exception:
            # The API can still expose degraded health when state initialization fails.
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

    @staticmethod
    def _checksum(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _provider_provenance(self, provider: dict[str, Any]) -> dict[str, str]:
        manifest_path = Path(provider["_manifest_path"]).resolve()
        capability_registry = getattr(self.registry, "capability_registry", None)
        if capability_registry is not None:
            for entry in capability_registry.store.load():
                root = Path(entry.path).resolve()
                if manifest_path == root or root in manifest_path.parents:
                    return {
                        "capability": entry.name,
                        "version": entry.version,
                        "checksum": entry.checksum,
                    }
        digest = hashlib.sha256()
        for path in sorted(manifest_path.parent.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            digest.update(path.relative_to(manifest_path.parent).as_posix().encode())
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
        return {
            "capability": "builtin",
            "version": str(provider.get("version", "0.0.0")),
            "checksum": digest.hexdigest(),
        }

    @staticmethod
    def _credential_references(
        provider: dict[str, Any], inputs: dict[str, Any]
    ) -> dict[str, str]:
        names = provider.get("write", {}).get("credential_refs", [])
        return {name: inputs[name] for name in names if name in inputs}

    def _promotion_snapshot(
        self, job: Job, provider: dict[str, Any]
    ) -> dict[str, Any]:
        artifacts = provider["write"]["artifacts"]
        records = {
            item["name"]: item for item in self.store.get_artifacts(job.job_id)
        }
        reviewed_paths = {}
        for kind in ("change_set", "validation"):
            output_name = artifacts[kind]
            record = records.get(output_name)
            if record is None:
                raise JobError(f"Dry-run job is missing {output_name} artifact")
            path = Path(record["path"])
            if not path.is_file():
                raise JobError(f"Dry-run {kind} artifact no longer exists")
            reviewed_paths[f"{kind}_path"] = str(path.resolve())
            reviewed_paths[f"{kind}_checksum"] = self._checksum(path)
        identity_input = provider["write"]["target"]["identity_input"]
        return {
            "dry_run_job_id": job.job_id,
            "skill": job.skill,
            "provider": job.provider,
            "provider_provenance": self._provider_provenance(provider),
            **reviewed_paths,
            "target_identity": job.inputs[identity_input],
            "credential_refs": self._credential_references(provider, job.inputs),
            "inputs_checksum": hashlib.sha256(
                json.dumps(job.inputs, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
        }

    @staticmethod
    def _idempotency_record_key(job: Job, provider: dict[str, Any]) -> str:
        contract = provider["write"]
        key_input = contract["idempotency"]["input"]
        identity_input = contract["target"]["identity_input"]
        return ":".join(
            (
                job.skill,
                job.provider,
                str(job.inputs[identity_input]),
                str(job.inputs[key_input]),
            )
        )

    def _validate_promotion(
        self,
        approval: Approval,
        provider: dict[str, Any],
        inputs: dict[str, Any],
    ) -> None:
        snapshot = approval.promotion
        if not snapshot:
            raise JobError("Live write requires a promotion approval")
        dry_raw = self.store.get_job(snapshot["dry_run_job_id"])
        if not dry_raw:
            raise JobError("Promotion dry-run job no longer exists")
        dry_job = Job.model_validate(dry_raw)
        if dry_job.status != "completed" or dry_job.policy.mode != "dry_run":
            raise JobError("Promotion source must be a completed dry-run job")
        current = self._promotion_snapshot(dry_job, provider)
        for field in (
            "skill",
            "provider",
            "provider_provenance",
            "change_set_path",
            "change_set_checksum",
            "validation_path",
            "validation_checksum",
            "target_identity",
            "credential_refs",
            "inputs_checksum",
        ):
            if current[field] != snapshot[field]:
                raise JobError(f"Promotion is stale: {field} changed after review")
        if inputs != dry_job.inputs:
            raise JobError("Promotion inputs differ from the reviewed dry run")

    @staticmethod
    def _load_artifact_json(path: Path, label: str) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ArtifactError(f"{label} artifact is not valid JSON") from exc
        if not isinstance(value, dict):
            raise ArtifactError(f"{label} artifact must contain a JSON object")
        return value

    def _pre_write_validate(self, job: Job) -> None:
        if job.recovery:
            recovery = self._load_artifact_json(
                Path(job.recovery["recovery_path"]), "Recovery"
            )
            if recovery.get("status") != "available":
                raise ArtifactError("Recovery artifact is not available")
            return
        validation = self._load_artifact_json(
            Path(job.promotion["validation_path"]), "Pre-write validation"
        )
        if validation.get("valid") is not True:
            raise ArtifactError("Pre-write validation did not pass")

    def _validate_write_outputs(
        self, job: Job, provider: dict[str, Any], artifacts: list[dict[str, Any]]
    ) -> None:
        bindings = provider["write"]["artifacts"]
        records = {item["name"]: item for item in artifacts}

        def load(kind: str) -> dict[str, Any]:
            output_name = bindings[kind]
            record = records.get(output_name)
            if not record:
                raise ArtifactError(f"Write provider is missing {kind} artifact")
            return self._load_artifact_json(Path(record["path"]), kind.title())

        validation = load("validation")
        if validation.get("valid") is not True:
            raise ArtifactError("Write-provider validation did not pass")
        if job.policy.mode != "live":
            return
        verification = load("verification")
        if verification.get("status") != "passed":
            raise ArtifactError("Post-write verification did not pass")
        recovery = load("recovery")
        expected = "completed" if job.recovery else "available"
        if recovery.get("status") != expected:
            raise ArtifactError(
                f"Recovery artifact must have status {expected}"
            )

    def _validate_recovery(
        self, approval: Approval, provider: dict[str, Any]
    ) -> Job:
        snapshot = approval.recovery
        if not snapshot:
            raise JobError("Recovery requires a recovery approval")
        raw = self.store.get_job(snapshot["live_job_id"])
        if not raw:
            raise JobError("Recovery source job no longer exists")
        live_job = Job.model_validate(raw)
        if live_job.status != "completed" or live_job.policy.mode != "live":
            raise JobError("Recovery source must be a completed live job")
        if self._provider_provenance(provider) != snapshot["provider_provenance"]:
            raise JobError("Recovery is stale: provider provenance changed")
        path = Path(snapshot["recovery_path"])
        if not path.is_file() or self._checksum(path) != snapshot["recovery_checksum"]:
            raise JobError("Recovery artifact is missing or changed")
        return live_job

    def promote(self, dry_run_job_id: str, requested_by: str = "cantor") -> Approval:
        raw = self.store.get_job(dry_run_job_id)
        if not raw:
            raise JobError(f"Unknown job: {dry_run_job_id}")
        job = Job.model_validate(raw)
        if job.status != "completed" or job.policy.mode != "dry_run":
            raise JobError("Only a completed dry-run job can be promoted")
        provider = self.registry.provider_internal(job.skill, job.provider)
        if not provider or "write" not in provider:
            raise JobError("Only a declared write provider can be promoted")
        snapshot = self._promotion_snapshot(job, provider)
        approval = Approval(
            approval_id=_id("approval"),
            skill=job.skill,
            provider=job.provider,
            reason=(
                f"Promote reviewed change set for {snapshot['target_identity']} "
                f"({snapshot['change_set_checksum']})"
            ),
            risk_level=int(provider.get("risk_level", 1)),
            created_at=utc_now(),
            updated_at=utc_now(),
            promotion=snapshot,
        )
        self.store.set_approval(
            approval.approval_id, approval.model_dump(mode="json")
        )
        self._event(
            job.job_id,
            "promotion_requested",
            "Live promotion approval requested.",
            {"approval_id": approval.approval_id},
        )
        return approval

    def recover(self, live_job_id: str) -> Approval:
        raw = self.store.get_job(live_job_id)
        if not raw:
            raise JobError(f"Unknown job: {live_job_id}")
        job = Job.model_validate(raw)
        if job.status != "completed" or job.policy.mode != "live":
            raise JobError("Only a completed live job can be recovered")
        provider = self.registry.provider_internal(job.skill, job.provider)
        if not provider or provider.get("write", {}).get("recovery", {}).get(
            "mode"
        ) not in {"rollback", "compensate"}:
            raise JobError("Provider does not support automatic recovery")
        recovery_name = provider["write"]["artifacts"]["recovery"]
        artifact = next(
            (
                item
                for item in self.store.get_artifacts(job.job_id)
                if item["name"] == recovery_name
            ),
            None,
        )
        if not artifact or not Path(artifact["path"]).is_file():
            raise JobError("Live job recovery artifact is unavailable")
        snapshot = {
            "live_job_id": job.job_id,
            "skill": job.skill,
            "provider": job.provider,
            "provider_provenance": self._provider_provenance(provider),
            "recovery_path": str(Path(artifact["path"]).resolve()),
            "recovery_checksum": self._checksum(Path(artifact["path"])),
            "target_identity": job.promotion["target_identity"],
        }
        approval = Approval(
            approval_id=_id("approval"),
            skill=job.skill,
            provider=job.provider,
            reason=f"Recover live job {job.job_id} for {snapshot['target_identity']}",
            risk_level=int(provider.get("risk_level", 1)),
            created_at=utc_now(),
            updated_at=utc_now(),
            recovery=snapshot,
        )
        self.store.set_approval(
            approval.approval_id, approval.model_dump(mode="json")
        )
        self._event(
            job.job_id,
            "recovery_requested",
            "Recovery approval requested.",
            {"approval_id": approval.approval_id},
        )
        return approval

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

    def create_job(
        self, request: JobRequest, *, recovery: dict[str, Any] | None = None
    ) -> Job:
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
        if request.policy.mode == "live" and "write" in provider:
            if linked_approval is None:
                raise JobError("Live write requires an approved dry-run promotion")
            if recovery:
                if linked_approval.recovery != recovery:
                    raise JobError("Recovery does not match the approved snapshot")
                self._validate_recovery(linked_approval, provider)
            else:
                self._validate_promotion(linked_approval, provider, inputs)
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
            promotion=linked_approval.promotion if linked_approval else None,
            recovery=recovery,
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
        idempotency_key = None
        if job.policy.mode == "live" and "write" in provider and not job.recovery:
            idempotency_key = self._idempotency_record_key(job, provider)
            claim = {
                "status": "running",
                "job_id": job.job_id,
                "change_set_checksum": job.promotion["change_set_checksum"],
            }
            existing = self.store.claim_idempotency(idempotency_key, claim)
            if existing:
                if (
                    existing.get("change_set_checksum")
                    != claim["change_set_checksum"]
                ):
                    return self._fail(
                        job,
                        "idempotency_conflict",
                        "Idempotency key is bound to a different change set",
                    )
                if existing.get("status") == "completed":
                    original_job_id = existing["job_id"]
                    self.store.set_artifacts(
                        job.job_id, self.store.get_artifacts(original_job_id)
                    )
                    job.status = "completed"
                    job.result = {
                        "status": "completed",
                        "summary": "Idempotent replay returned the prior live result.",
                        "idempotent_replay": True,
                        "original_job_id": original_job_id,
                    }
                    self._save(job)
                    self._event(
                        job.job_id,
                        "idempotent_replay",
                        "No mutation performed; prior live result returned.",
                        {"original_job_id": original_job_id},
                    )
                    return job
                return self._fail(
                    job,
                    "idempotency_in_progress",
                    "Another live job is using this idempotency key",
                )
        self._event(job_id, "provider_started", f"Running {job.skill}.{job.provider}.")
        try:
            limits = effective_limits(provider, self.settings)
        except RunnerError as exc:
            return self._fail(job, "invalid_runtime_limits", str(exc))
        self._event(
            job_id,
            "runtime_limits_applied",
            "Provider runtime limits applied.",
            limits,
        )
        try:
            resolved_inputs, sensitive_values = resolve_credential_inputs(
                job.inputs, self.vault or CredentialVault.local()
            )
        except CredentialError as exc:
            return self._fail(job, "credential_resolution_failed", str(exc))
        payload = {
            "job_id": job.job_id,
            "skill": job.skill,
            "provider": job.provider,
            "inputs": resolved_inputs,
            "policy": job.policy.model_dump(mode="json"),
            "promotion": job.promotion,
            "recovery": job.recovery,
            "artifact_dir": job.artifact_dir,
            "canto_root": str(self.settings.root_dir.resolve()),
            "scaffolds_dir": str(self.settings.scaffolds_dir.resolve()),
        }
        try:
            if job.policy.mode == "live" and "write" in provider:
                self._pre_write_validate(job)
            try:
                result = run_provider(
                    provider,
                    payload,
                    Path(job.artifact_dir),
                    self.settings,
                    sensitive_values=sensitive_values,
                )
            finally:
                redact_artifacts(Path(job.artifact_dir), sensitive_values)
            artifacts = collect_artifacts(Path(job.artifact_dir), provider.get("outputs", {}))
            if "write" in provider:
                self._validate_write_outputs(job, provider, artifacts)
        except (RunnerError, ArtifactError) as exc:
            details = exc.details if isinstance(exc, RunnerError) else {}
            if idempotency_key:
                self.store.set_idempotency(
                    idempotency_key,
                    {
                        "status": "failed",
                        "job_id": job.job_id,
                        "change_set_checksum": job.promotion[
                            "change_set_checksum"
                        ],
                    },
                )
            return self._fail(job, "provider_failed", str(exc), details)
        self.store.set_artifacts(job_id, artifacts)
        job.status = "completed"
        job.result = result
        self._save(job)
        if idempotency_key:
            self.store.set_idempotency(
                idempotency_key,
                {
                    "status": "completed",
                    "job_id": job.job_id,
                    "change_set_checksum": job.promotion["change_set_checksum"],
                },
            )
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
        if approval.promotion:
            dry_job = Job.model_validate(
                self.store.get_job(approval.promotion["dry_run_job_id"])
            )
            provider = self.registry.provider_internal(
                dry_job.skill, dry_job.provider
            )
            if not provider:
                raise JobError("Promotion provider is no longer registered")
            self._validate_promotion(approval, provider, dry_job.inputs)
        if approval.recovery:
            raw_job = self.store.get_job(approval.recovery["live_job_id"])
            if not raw_job:
                raise JobError("Recovery source job no longer exists")
            recovery_job = Job.model_validate(raw_job)
            provider = self.registry.provider_internal(
                recovery_job.skill, recovery_job.provider
            )
            if not provider:
                raise JobError("Recovery provider is no longer registered")
            self._validate_recovery(approval, provider)
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
        if approval.promotion:
            dry_job = Job.model_validate(
                self.store.get_job(approval.promotion["dry_run_job_id"])
            )
            live_request = JobRequest(
                skill=dry_job.skill,
                provider=dry_job.provider,
                goal=dry_job.goal,
                inputs=dry_job.inputs,
                policy=dry_job.policy.model_copy(update={"mode": "live"}),
                requested_by=approved_by,
                approval_id=approval.approval_id,
            )
            live_job = self.create_job(live_request)
            self._event(
                dry_job.job_id,
                "promotion_approved",
                "Live promotion approved.",
                {"live_job_id": live_job.job_id},
            )
            return self.process_job(live_job.job_id)
        if approval.recovery:
            source = Job.model_validate(
                self.store.get_job(approval.recovery["live_job_id"])
            )
            recovery_request = JobRequest(
                skill=source.skill,
                provider=source.provider,
                goal=f"Recover {source.job_id}",
                inputs=source.inputs,
                policy=source.policy,
                requested_by=approved_by,
                approval_id=approval.approval_id,
            )
            recovery_job = self.create_job(
                recovery_request, recovery=approval.recovery
            )
            return self.process_job(recovery_job.job_id)
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
