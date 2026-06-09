from __future__ import annotations

import json
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Any

from pydantic import BaseModel, Field

from canto.core.capability_manifest import CapabilityManifest
from canto.core.local_registry import Registry, RegistryEntry


TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
PLAN_ID_PATTERN = re.compile(r"plan_[0-9]{8}_[a-f0-9]{6}")


class CapabilityMatch(BaseModel):
    name: str
    version: str
    score: int
    reasons: list[str] = Field(default_factory=list)
    intents: list[str] = Field(default_factory=list)
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    risk: str


class WorkflowStep(BaseModel):
    capability: str
    reason: str
    requires: list[str] = Field(default_factory=list)
    produces: list[str] = Field(default_factory=list)


class WorkflowCandidate(BaseModel):
    goal: str
    steps: list[WorkflowStep] = Field(default_factory=list)


class PlanPreview(BaseModel):
    candidate: WorkflowCandidate
    missing_inputs: list[str] = Field(default_factory=list)
    produced_artifacts: list[str] = Field(default_factory=list)


class ExecutionPlan(BaseModel):
    plan_id: str
    candidate: WorkflowCandidate
    missing_inputs: list[str] = Field(default_factory=list)
    produced_artifacts: list[str] = Field(default_factory=list)
    status: str = "draft"
    created_at: str
    approved_at: str | None = None
    capability_versions: dict[str, str] = Field(default_factory=dict)
    capability_providers: dict[str, str] = Field(default_factory=dict)
    error: str | None = None
    completed_at: str | None = None


class PlanExecutionResult(BaseModel):
    plan_id: str
    status: str
    artifacts: dict[str, str] = Field(default_factory=dict)


class PlanStepExplanation(BaseModel):
    capability: str
    version: str
    reason: str
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    risk: str
    missing_values: list[str] = Field(default_factory=list)


class PlanExplanation(BaseModel):
    plan_id: str
    goal: str
    status: str
    steps: list[PlanStepExplanation] = Field(default_factory=list)


class OrchestrationError(ValueError):
    """Raised when a local orchestration plan cannot be managed."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class PlanStore:
    def __init__(self, plans_dir: str | Path):
        self.plans_dir = Path(plans_dir)
        self.plans_dir.mkdir(parents=True, exist_ok=True)

    def save(self, plan: ExecutionPlan) -> None:
        self._validate_plan_id(plan.plan_id)
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
            for requirement in manifest.inputs:
                producers = [
                    producer_name
                    for producer_name, producer_manifest in installed.items()
                    if producer_name != name and requirement in producer_manifest.outputs
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
                    reason=reason or "highest deterministic metadata score",
                    requires=manifest.inputs,
                    produces=manifest.outputs,
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
    def __init__(self, registry: Registry, store: PlanStore):
        self.registry = registry
        self.planner = WorkflowPlanner(registry)
        self.store = store

    def create_plan(self, goal: str, approve: bool = False) -> ExecutionPlan:
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
            manifest = self.registry.inspect(entry.name, entry.version).manifest
            if not manifest.providers:
                raise OrchestrationError(
                    f"Capability {entry.name} does not declare an executable provider"
                )
            versions[entry.name] = entry.version
            providers[entry.name] = sorted(manifest.providers)[0]
        plan = ExecutionPlan(
            plan_id=f"plan_{now[:10].replace('-', '')}_{secrets.token_hex(3)}",
            candidate=preview.candidate,
            missing_inputs=preview.missing_inputs,
            produced_artifacts=preview.produced_artifacts,
            status="approved" if approve else "draft",
            created_at=now,
            approved_at=now if approve else None,
            capability_versions=versions,
            capability_providers=providers,
        )
        self.store.save(plan)
        return plan

    def execute(
        self,
        plan_id: str,
        executor: Callable[[str, str, dict[str, str], list[str]], dict[str, str]],
    ) -> PlanExecutionResult:
        plan = self.store.load(plan_id)
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

        artifacts: dict[str, str] = {}
        try:
            for step in plan.candidate.steps:
                resolved = {
                    requirement: artifacts[requirement]
                    for requirement in step.requires
                    if requirement in artifacts
                }
                missing = [
                    requirement
                    for requirement in step.requires
                    if requirement not in resolved
                ]
                if missing:
                    raise OrchestrationError(
                        f"Step {step.capability} is missing dependencies: {missing}"
                    )
                produced = executor(
                    step.capability,
                    plan.capability_providers[step.capability],
                    resolved,
                    step.produces,
                )
                for output in step.produces:
                    if output not in produced:
                        raise OrchestrationError(
                            f"Step {step.capability} did not produce {output}"
                        )
                artifacts.update(produced)
        except Exception as exc:
            plan.status = "failed"
            plan.error = str(exc)
            self.store.save(plan)
            if isinstance(exc, OrchestrationError):
                raise
            raise OrchestrationError(f"Plan {plan_id} execution failed: {exc}") from exc

        plan.status = "completed"
        plan.completed_at = _now()
        self.store.save(plan)
        return PlanExecutionResult(
            plan_id=plan.plan_id,
            status=plan.status,
            artifacts=artifacts,
        )

    def explain(self, plan_id: str) -> PlanExplanation:
        plan = self.store.load(plan_id)
        steps = []
        for step in plan.candidate.steps:
            version = plan.capability_versions[step.capability]
            installed = self.registry.inspect(step.capability, version)
            steps.append(
                PlanStepExplanation(
                    capability=step.capability,
                    version=version,
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
