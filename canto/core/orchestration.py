from __future__ import annotations

import json
import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable, Any, Literal

from pydantic import BaseModel, Field

from canto.core.capability_manifest import CapabilityManifest
from canto.core.jobs import JobService
from canto.core.local_registry import Registry, RegistryEntry
from canto.core.policy import PolicyDenied, evaluate_policy
from canto.core.state import StateStore
from canto.models.schemas import Approval, JobRequest, Policy


TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
PLAN_ID_PATTERN = re.compile(r"plan_[0-9]{8}_[a-f0-9]{6}")
CONTRACT_VERSION = "1.0"


class CapabilityMatch(BaseModel):
    contract_version: str = CONTRACT_VERSION
    name: str
    version: str
    score: int
    reasons: list[str] = Field(default_factory=list)
    intents: list[str] = Field(default_factory=list)
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    risk: str


class DiscoverRequest(BaseModel):
    goal: str = Field(min_length=1)
    limit: int = Field(default=10, ge=1, le=100)


class DiscoverResponse(BaseModel):
    contract_version: str = CONTRACT_VERSION
    goal: str
    matches: list[CapabilityMatch] = Field(default_factory=list)


class WorkflowStep(BaseModel):
    contract_version: str = CONTRACT_VERSION
    capability: str
    version: str = ""
    skill: str = ""
    provider: str = ""
    consumes: dict[str, str] = Field(default_factory=dict)
    artifact_outputs: dict[str, str] = Field(default_factory=dict)
    reason: str
    requires: list[str] = Field(default_factory=list)
    produces: list[str] = Field(default_factory=list)


class WorkflowCandidate(BaseModel):
    contract_version: str = CONTRACT_VERSION
    goal: str
    steps: list[WorkflowStep] = Field(default_factory=list)


class PlanPreview(BaseModel):
    contract_version: str = CONTRACT_VERSION
    candidate: WorkflowCandidate
    missing_inputs: list[str] = Field(default_factory=list)
    produced_artifacts: list[str] = Field(default_factory=list)


class PlanCreateRequest(BaseModel):
    goal: str = Field(min_length=1)
    inputs: dict[str, Any] = Field(default_factory=dict)


class PlanStepJob(BaseModel):
    step_index: int
    job_id: str
    status: str


class PlanEvent(BaseModel):
    timestamp: str
    type: str
    message: str
    step_index: int | None = None
    job_id: str | None = None


class ExecutionPlan(BaseModel):
    contract_version: str = CONTRACT_VERSION
    plan_id: str
    candidate: WorkflowCandidate
    missing_inputs: list[str] = Field(default_factory=list)
    produced_artifacts: list[str] = Field(default_factory=list)
    status: Literal[
        "draft",
        "waiting_for_approval",
        "approved",
        "running",
        "completed",
        "failed",
        "rejected",
        "cancelled",
    ] = "draft"
    created_at: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    approved_at: str | None = None
    capability_versions: dict[str, str] = Field(default_factory=dict)
    capability_providers: dict[str, str] = Field(default_factory=dict)
    step_approval_ids: dict[str, str] = Field(default_factory=dict)
    step_jobs: list[PlanStepJob] = Field(default_factory=list)
    artifacts: dict[str, str] = Field(default_factory=dict)
    events: list[PlanEvent] = Field(default_factory=list)
    error: str | None = None
    completed_at: str | None = None


class PlanExecutionResult(BaseModel):
    contract_version: str = CONTRACT_VERSION
    plan_id: str
    status: str
    artifacts: dict[str, str] = Field(default_factory=dict)


class PlanExecutionAccepted(BaseModel):
    contract_version: str = CONTRACT_VERSION
    plan_id: str
    status: Literal["running"] = "running"
    step_jobs: list[PlanStepJob] = Field(default_factory=list)


class PlanEventsResponse(BaseModel):
    contract_version: str = CONTRACT_VERSION
    plan_id: str
    events: list[PlanEvent] = Field(default_factory=list)


class PlanStepExplanation(BaseModel):
    contract_version: str = CONTRACT_VERSION
    capability: str
    version: str
    skill: str
    provider: str
    reason: str
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    risk: str
    missing_values: list[str] = Field(default_factory=list)


class PlanExplanation(BaseModel):
    contract_version: str = CONTRACT_VERSION
    plan_id: str
    goal: str
    status: str
    steps: list[PlanStepExplanation] = Field(default_factory=list)


class OrchestrationError(ValueError):
    """Raised when a local orchestration plan cannot be managed."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _next_plan_timestamp(plan: ExecutionPlan) -> str:
    now = datetime.now(timezone.utc)
    if plan.events:
        previous = datetime.fromisoformat(
            plan.events[-1].timestamp.replace("Z", "+00:00")
        )
        if now <= previous:
            now = previous + timedelta(microseconds=1)
    return now.isoformat().replace("+00:00", "Z")


class PlanStore:
    def __init__(self, backend: StateStore | str | Path):
        self.state_store = backend if not isinstance(backend, (str, Path)) else None
        self.plans_dir = Path(backend) if isinstance(backend, (str, Path)) else None
        if self.plans_dir is not None:
            self.plans_dir.mkdir(parents=True, exist_ok=True)

    def save(self, plan: ExecutionPlan) -> None:
        self._validate_plan_id(plan.plan_id)
        if self.state_store is not None:
            self.state_store.set_plan(plan.plan_id, plan.model_dump(mode="json"))
            return
        assert self.plans_dir is not None
        path = self.plans_dir / f"{plan.plan_id}.json"
        temporary = path.with_suffix(".json.tmp")
        try:
            temporary.write_text(
                json.dumps(plan.model_dump(mode="json"), indent=2) + "\n",
                encoding="utf-8",
            )
            temporary.replace(path)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise OrchestrationError(f"Cannot save plan {plan.plan_id}: {exc}") from exc

    def load(self, plan_id: str) -> ExecutionPlan:
        self._validate_plan_id(plan_id)
        if self.state_store is not None:
            value = self.state_store.get_plan(plan_id)
            if value is None:
                raise OrchestrationError(f"Cannot load plan {plan_id}: not found")
            try:
                return ExecutionPlan.model_validate(value)
            except ValueError as exc:
                raise OrchestrationError(
                    f"Cannot load plan {plan_id}: {exc}"
                ) from exc
        assert self.plans_dir is not None
        path = self.plans_dir / f"{plan_id}.json"
        try:
            return ExecutionPlan.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise OrchestrationError(f"Cannot load plan {plan_id}: {exc}") from exc

    @staticmethod
    def _validate_plan_id(plan_id: str) -> None:
        if not PLAN_ID_PATTERN.fullmatch(plan_id):
            raise OrchestrationError(f"Invalid plan ID: {plan_id}")


def tokens(value: str) -> set[str]:
    return set(TOKEN_PATTERN.findall(value.casefold().replace("_", " ").replace("-", " ")))


def _overlap(goal_tokens: set[str], values: Iterable[str]) -> set[str]:
    matched: set[str] = set()
    for value in values:
        matched.update(goal_tokens & tokens(value))
    return matched


def score_manifest(goal: str, manifest: CapabilityManifest) -> tuple[int, list[str]]:
    goal_tokens = tokens(goal)
    score = 0
    reasons = []
    weighted_fields = (
        ("intent", manifest.intents, 40),
        ("name", [manifest.name], 20),
        ("description", [manifest.description], 10),
        ("input", manifest.inputs, 5),
        ("output", manifest.outputs, 3),
    )
    for label, values, weight in weighted_fields:
        matched = sorted(_overlap(goal_tokens, values))
        if matched:
            score += weight * len(matched)
            reasons.append(f"{label} matched: {', '.join(matched)}")
    return score, reasons


def resolve_provider_binding(
    manifest: CapabilityManifest,
) -> tuple[str, str, dict[str, str], dict[str, str]] | None:
    if manifest.execution and manifest.execution.providers:
        bindings = sorted(
            manifest.execution.providers,
            key=lambda item: (item.skill, item.provider),
        )
        binding = bindings[0]
        duplicates = [
            item
            for item in bindings
            if (item.skill, item.provider) == (binding.skill, binding.provider)
        ]
        if len(duplicates) > 1:
            raise OrchestrationError(
                "Ambiguous execution provider bindings for "
                f"({binding.skill}, {binding.provider})"
            )
        return (
            binding.skill,
            binding.provider,
            binding.consumes,
            binding.produces,
        )
    legacy = sorted(manifest.providers)
    if not legacy or "." not in legacy[0]:
        return None
    skill, provider = legacy[0].split(".", 1)
    return (
        skill,
        provider,
        {name: name for name in manifest.inputs},
        {name: name for name in manifest.outputs},
    )


def resolve_artifact_inputs(
    step: WorkflowStep, artifacts: dict[str, Any]
) -> dict[str, Any]:
    resolved = {}
    consumes = step.consumes or {name: name for name in step.requires}
    for provider_input, artifact_name in consumes.items():
        if artifact_name not in artifacts:
            raise OrchestrationError(
                f"Step {step.capability} is missing artifact {artifact_name} "
                f"for provider input {provider_input}"
            )
        resolved[provider_input] = artifacts[artifact_name]
    return resolved


def manifest_execution_metadata(
    manifest: CapabilityManifest,
) -> tuple[
    tuple[str, str, dict[str, str], dict[str, str]] | None,
    list[str],
    list[str],
]:
    binding = resolve_provider_binding(manifest)
    requires = (
        sorted(set(binding[2].values()))
        if binding and binding[2]
        else manifest.inputs
    )
    produces = (
        sorted(set(binding[3].values()))
        if binding and binding[3]
        else manifest.outputs
    )
    return binding, requires, produces


class CapabilityMatcher:
    def __init__(self, registry: Registry):
        self.registry = registry

    def discover(self, goal: str) -> list[CapabilityMatch]:
        matches = []
        for entry in self.registry.list_installed():
            manifest = self.registry.inspect(entry.name, entry.version).manifest
            score, reasons = score_manifest(goal, manifest)
            if score <= 0:
                continue
            matches.append(
                CapabilityMatch(
                    name=entry.name,
                    version=entry.version,
                    score=score,
                    reasons=reasons,
                    intents=manifest.intents,
                    inputs=manifest.inputs,
                    outputs=manifest.outputs,
                    risk=entry.risk,
                )
            )
        return sorted(matches, key=lambda item: (-item.score, item.name, item.version))


class WorkflowPlanner:
    def __init__(self, registry: Registry):
        self.registry = registry
        self.matcher = CapabilityMatcher(registry)

    def plan(self, goal: str) -> PlanPreview:
        matches = self.matcher.discover(goal)
        if not matches:
            return PlanPreview(candidate=WorkflowCandidate(goal=goal))

        installed = {}
        scores = {}
        reasons = {}
        for entry in self.registry.list_installed():
            manifest = self.registry.inspect(entry.name, entry.version).manifest
            installed[entry.name] = manifest
            score, match_reasons = score_manifest(goal, manifest)
            scores[entry.name] = score
            reasons[entry.name] = match_reasons

        target = matches[0].name
        steps: list[WorkflowStep] = []
        added: set[str] = set()
        visiting: set[str] = set()
        missing_inputs: set[str] = set()

        def add_step(name: str, dependency_reason: str | None = None) -> None:
            if name in added:
                return
            if name in visiting:
                raise OrchestrationError(f"Artifact dependency cycle includes {name}")
            visiting.add(name)
            manifest = installed[name]
            binding, requires, produces = manifest_execution_metadata(manifest)
            for requirement in requires:
                producers = [
                    producer_name
                    for producer_name, producer_manifest in installed.items()
                    if producer_name != name
                    and requirement in manifest_execution_metadata(producer_manifest)[2]
                ]
                if not producers:
                    missing_inputs.add(requirement)
                    continue
                producer = sorted(
                    producers,
                    key=lambda candidate: (
                        -scores[candidate],
                        candidate,
                        installed[candidate].version,
                    ),
                )[0]
                add_step(
                    producer,
                    f"produces {requirement} required by {name}",
                )
            visiting.remove(name)
            reason = dependency_reason or "; ".join(reasons[name])
            steps.append(
                WorkflowStep(
                    capability=name,
                    version=manifest.version,
                    skill=binding[0] if binding else "",
                    provider=binding[1] if binding else "",
                    consumes=binding[2] if binding else {},
                    artifact_outputs=binding[3] if binding else {},
                    reason=reason or "highest deterministic metadata score",
                    requires=requires,
                    produces=produces,
                )
            )
            added.add(name)

        add_step(target)
        produced_artifacts = sorted(
            {output for step in steps for output in step.produces}
        )
        return PlanPreview(
            candidate=WorkflowCandidate(goal=goal, steps=steps),
            missing_inputs=sorted(missing_inputs),
            produced_artifacts=produced_artifacts,
        )


class Orchestrator:
    def __init__(
        self,
        registry: Registry,
        store: PlanStore,
        job_service: JobService | None = None,
    ):
        self.registry = registry
        self.planner = WorkflowPlanner(registry)
        self.store = store
        self.job_service = job_service

    def create_plan(
        self,
        goal: str,
        approve: bool = False,
        inputs: dict[str, Any] | None = None,
    ) -> ExecutionPlan:
        preview = self.planner.plan(goal)
        if approve and not preview.candidate.steps:
            raise OrchestrationError("Cannot approve a plan with no capability steps")
        now = _now()
        versions = {}
        providers = {}
        for step in preview.candidate.steps:
            matches = [
                match
                for match in self.registry.list_installed()
                if match.name == step.capability
            ]
            if len(matches) != 1:
                raise OrchestrationError(
                    f"Plan requires exactly one installed version of {step.capability}"
                )
            entry = matches[0]
            if not step.skill or not step.provider:
                raise OrchestrationError(
                    f"Capability {entry.name} does not declare an executable provider"
                )
            versions[entry.name] = entry.version
            providers[entry.name] = f"{step.skill}.{step.provider}"
        plan = ExecutionPlan(
            plan_id=f"plan_{now[:10].replace('-', '')}_{secrets.token_hex(3)}",
            candidate=preview.candidate,
            missing_inputs=[
                name for name in preview.missing_inputs if name not in (inputs or {})
            ],
            produced_artifacts=preview.produced_artifacts,
            status="draft",
            created_at=now,
            inputs=inputs or {},
            capability_versions=versions,
            capability_providers=providers,
            events=[
                PlanEvent(
                    timestamp=now,
                    type="plan_created",
                    message="Plan created.",
                )
            ],
        )
        if approve:
            self._request_plan_approvals(plan)
        self.store.save(plan)
        return plan

    def get_plan(self, plan_id: str) -> ExecutionPlan:
        plan = self.store.load(plan_id)
        self._refresh_approval_status(plan)
        return plan

    def approve_plan(
        self, plan_id: str, approved_by: str, note: str = ""
    ) -> ExecutionPlan:
        plan = self.store.load(plan_id)
        if plan.status != "draft":
            raise OrchestrationError(
                f"Plan {plan_id} cannot be approved from status {plan.status}"
            )
        if not plan.candidate.steps:
            raise OrchestrationError("Cannot approve a plan with no capability steps")
        self._request_plan_approvals(plan)
        if self.job_service is None:
            raise OrchestrationError("JobService is required to approve a plan")
        for approval_id in plan.step_approval_ids.values():
            self.job_service.approve(approval_id, approved_by, note)
        self._refresh_approval_status(plan)
        plan.approved_at = _next_plan_timestamp(plan)
        plan.events.append(
            PlanEvent(
                timestamp=plan.approved_at,
                type="plan_approved",
                message=f"Plan approved by {approved_by}.",
            )
        )
        self.store.save(plan)
        return plan

    def _request_plan_approvals(self, plan: ExecutionPlan) -> None:
        for index, step in enumerate(plan.candidate.steps):
            installed = self.registry.inspect(step.capability, step.version)
            reasons = []
            if installed.manifest.risk.requires_approval:
                reasons.append("Capability manifest requires approval")
            provider_risk = {
                "low": 1,
                "medium": 2,
                "high": 3,
            }[installed.entry.risk]
            if self.job_service is not None:
                provider = self.job_service.registry.provider_internal(
                    step.skill, step.provider
                )
                if not provider and reasons:
                    raise OrchestrationError(
                        f"Provider {step.skill}.{step.provider} is not executable"
                    )
                if provider:
                    try:
                        policy_inputs = {
                            provider_input: plan.inputs[logical_name]
                            for provider_input, logical_name in step.consumes.items()
                            if logical_name in plan.inputs
                        }
                        reasons.extend(
                            evaluate_policy(provider, policy_inputs, Policy())
                        )
                    except PolicyDenied as exc:
                        raise OrchestrationError(str(exc)) from exc
                    provider_risk = int(provider.get("risk_level", provider_risk))
            if not reasons:
                continue
            if self.job_service is None:
                raise OrchestrationError(
                    "JobService is required to persist plan approvals"
                )
            approval_id = (
                f"approval_{_now()[:10].replace('-', '')}_{secrets.token_hex(3)}"
            )
            approval = Approval(
                approval_id=approval_id,
                plan_id=plan.plan_id,
                step_capability=step.capability,
                skill=step.skill,
                provider=step.provider,
                reason="; ".join(sorted(set(reasons))),
                risk_level=provider_risk,
                created_at=_now(),
                updated_at=_now(),
            )
            self.job_service.store.set_approval(
                approval_id, approval.model_dump(mode="json")
            )
            plan.step_approval_ids[str(index)] = approval_id
        plan.approved_at = _now()
        plan.status = "waiting_for_approval" if plan.step_approval_ids else "approved"

    def _refresh_approval_status(self, plan: ExecutionPlan) -> None:
        if not plan.step_approval_ids or plan.status in {
            "running",
            "completed",
            "failed",
            "rejected",
            "cancelled",
        }:
            return
        if self.job_service is None:
            raise OrchestrationError("JobService is required to read plan approvals")
        statuses = []
        for approval_id in plan.step_approval_ids.values():
            approval = self.job_service.store.get_approval(approval_id)
            if not approval:
                raise OrchestrationError(f"Plan approval not found: {approval_id}")
            statuses.append(approval["status"])
        if "rejected" in statuses:
            plan.status = "rejected"
        elif all(status == "approved" for status in statuses):
            plan.status = "approved"
        else:
            plan.status = "waiting_for_approval"
        self.store.save(plan)

    def execute(self, plan_id: str) -> PlanExecutionResult:
        if self.job_service is None:
            raise OrchestrationError("JobService is required to execute a plan")
        plan = self.store.load(plan_id)
        if plan.status == "approved":
            self.prepare_execution(plan_id)
        return self._execute(plan_id, self._execute_job_step)

    def prepare_execution(self, plan_id: str) -> PlanExecutionAccepted:
        plan = self.store.load(plan_id)
        self._refresh_approval_status(plan)
        if plan.status != "approved":
            raise OrchestrationError(
                f"Plan {plan_id} is not approved and cannot be executed"
            )
        if not plan.candidate.steps:
            raise OrchestrationError(f"Plan {plan_id} has no executable steps")
        if plan.missing_inputs:
            raise OrchestrationError(
                f"Plan {plan_id} is missing inputs: {plan.missing_inputs}"
            )
        plan.status = "running"
        plan.events.append(
            PlanEvent(
                timestamp=_now(),
                type="plan_started",
                message="Plan execution started.",
            )
        )
        self.store.save(plan)
        return PlanExecutionAccepted(
            plan_id=plan.plan_id,
            step_jobs=plan.step_jobs,
        )

    def _execute_job_step(
        self,
        plan: ExecutionPlan,
        step_index: int,
        step: WorkflowStep,
        inputs: dict[str, Any],
        approval_id: str | None,
    ) -> dict[str, str]:
        if self.job_service is None:
            raise OrchestrationError("JobService is required to execute a plan")
        job = self.job_service.create_job(
            JobRequest(
                skill=step.skill,
                provider=step.provider,
                inputs=inputs,
                requested_by=f"plan:{step.capability}@{step.version}",
                approval_id=approval_id,
            )
        )
        plan.step_jobs.append(
            PlanStepJob(step_index=step_index, job_id=job.job_id, status=job.status)
        )
        plan.events.append(
            PlanEvent(
                timestamp=_now(),
                type="step_job_created",
                message=f"Created job for step {step_index}.",
                step_index=step_index,
                job_id=job.job_id,
            )
        )
        self.store.save(plan)
        completed = self.job_service.process_job(job.job_id)
        plan.step_jobs[-1].status = completed.status
        plan.events.append(
            PlanEvent(
                timestamp=_now(),
                type="step_job_completed" if completed.status == "completed" else "step_job_stopped",
                message=f"Step {step_index} job stopped with status {completed.status}.",
                step_index=step_index,
                job_id=job.job_id,
            )
        )
        self.store.save(plan)
        if completed.status != "completed":
            raise OrchestrationError(
                f"Step {step.capability} stopped with status {completed.status}"
            )
        records = {
            item["name"]: item["path"]
            for item in self.job_service.store.get_artifacts(job.job_id)
        }
        output_bindings = step.artifact_outputs or {
            name: name for name in step.produces
        }
        return {
            logical_name: records[provider_output]
            for provider_output, logical_name in output_bindings.items()
            if provider_output in records
        }

    def _execute(
        self,
        plan_id: str,
        executor: Callable[
            [ExecutionPlan, int, WorkflowStep, dict[str, Any], str | None],
            dict[str, str],
        ],
    ) -> PlanExecutionResult:
        plan = self.store.load(plan_id)
        self._refresh_approval_status(plan)
        if plan.status not in {"approved", "running"}:
            raise OrchestrationError(
                f"Plan {plan_id} is not approved and cannot be executed"
            )
        if not plan.candidate.steps:
            raise OrchestrationError(f"Plan {plan_id} has no executable steps")
        if plan.missing_inputs:
            raise OrchestrationError(
                f"Plan {plan_id} is missing inputs: {plan.missing_inputs}"
            )

        artifacts: dict[str, str] = {}
        available: dict[str, Any] = dict(plan.inputs)
        try:
            for index, step in enumerate(plan.candidate.steps):
                resolved = resolve_artifact_inputs(step, available)
                produced = executor(
                    plan,
                    index,
                    step,
                    resolved,
                    plan.step_approval_ids.get(str(index)),
                )
                for output in step.produces:
                    if output not in produced:
                        raise OrchestrationError(
                            f"Step {step.capability} did not produce {output}"
                        )
                artifacts.update(produced)
                available.update(produced)
        except Exception as exc:
            plan.status = "failed"
            plan.error = str(exc)
            plan.events.append(
                PlanEvent(
                    timestamp=_now(),
                    type="plan_failed",
                    message=str(exc),
                )
            )
            self.store.save(plan)
            if isinstance(exc, OrchestrationError):
                raise
            raise OrchestrationError(f"Plan {plan_id} execution failed: {exc}") from exc

        plan.status = "completed"
        plan.completed_at = _now()
        plan.artifacts = artifacts
        plan.events.append(
            PlanEvent(
                timestamp=plan.completed_at,
                type="plan_completed",
                message="Plan completed.",
            )
        )
        self.store.save(plan)
        return PlanExecutionResult(
            plan_id=plan.plan_id,
            status=plan.status,
            artifacts=artifacts,
        )

    def events(self, plan_id: str) -> PlanEventsResponse:
        plan = self.store.load(plan_id)
        events = list(plan.events)
        if self.job_service is not None:
            for step_job in plan.step_jobs:
                for event in self.job_service.store.get_events(step_job.job_id):
                    events.append(
                        PlanEvent(
                            timestamp=event["timestamp"],
                            type=event["type"],
                            message=event["message"],
                            step_index=step_job.step_index,
                            job_id=step_job.job_id,
                        )
                    )
        return PlanEventsResponse(
            plan_id=plan_id,
            events=sorted(events, key=lambda event: event.timestamp),
        )

    def explain(self, plan_id: str) -> PlanExplanation:
        plan = self.store.load(plan_id)
        self._refresh_approval_status(plan)
        steps = []
        for step in plan.candidate.steps:
            version = plan.capability_versions[step.capability]
            installed = self.registry.inspect(step.capability, version)
            steps.append(
                PlanStepExplanation(
                    capability=step.capability,
                    version=version,
                    skill=step.skill,
                    provider=step.provider,
                    reason=step.reason,
                    inputs=step.requires,
                    outputs=step.produces,
                    risk=installed.entry.risk,
                    missing_values=[
                        value for value in step.requires if value in plan.missing_inputs
                    ],
                )
            )
        return PlanExplanation(
            plan_id=plan.plan_id,
            goal=plan.candidate.goal,
            status=plan.status,
            steps=steps,
        )
