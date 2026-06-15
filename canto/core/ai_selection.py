from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, TypeVar
from uuid import uuid4

from canto.core.ai_endpoints import endpoint_is_local
from canto.core.state import StateStore
from canto.models.ai_workers import (
    AIEndpointRecord,
    AIModelRecord,
    CandidateScore,
    WorkerBudgetPolicy,
    WorkerSelectionDecision,
    WorkerSelectionPolicy,
)


class WorkerSelectionError(RuntimeError):
    pass


T = TypeVar("T")


def _narrow(values: Iterable[list[T]]) -> list[T]:
    constrained = [set(value) for value in values if value]
    if not constrained:
        return []
    result = constrained[0]
    for value in constrained[1:]:
        result &= value
    return sorted(result)  # type: ignore[type-var]


def _minimum(policies: list[WorkerBudgetPolicy], field: str):
    values = [getattr(policy, field) for policy in policies if getattr(policy, field) is not None]
    return min(values) if values else None


def _preference(layers: list[WorkerSelectionPolicy]) -> list[str]:
    for layer in reversed(layers):
        if layer.preferred_models:
            return list(layer.preferred_models)
    return []


def compose_worker_policy(
    *layers: WorkerSelectionPolicy | None,
) -> WorkerSelectionPolicy:
    """Compose global, repository, and task policy without widening authority."""
    active = [layer for layer in layers if layer is not None]
    if not active:
        return WorkerSelectionPolicy()
    budgets = [layer.budget for layer in active]
    return WorkerSelectionPolicy(
        priority=active[-1].priority,
        allowed_endpoints=_narrow(layer.allowed_endpoints for layer in active),
        allowed_providers=_narrow(layer.allowed_providers for layer in active),
        allowed_models=_narrow(layer.allowed_models for layer in active),
        preferred_models=_preference(active),
        cloud_allowed=all(layer.cloud_allowed for layer in active),
        cloud_fallback_allowed=all(layer.cloud_fallback_allowed for layer in active),
        local_first=any(layer.local_first for layer in active),
        required_classification=(
            "implementation"
            if any(layer.required_classification == "implementation" for layer in active)
            else "advisory"
        ),
        budget=WorkerBudgetPolicy(
            enabled=any(policy.enabled for policy in budgets),
            max_estimated_usd=_minimum(budgets, "max_estimated_usd"),
            max_actual_usd=_minimum(budgets, "max_actual_usd"),
            max_input_tokens=_minimum(budgets, "max_input_tokens"),
            max_output_tokens=_minimum(budgets, "max_output_tokens"),
            max_turns=_minimum(budgets, "max_turns"),
            max_tool_calls=_minimum(budgets, "max_tool_calls"),
            max_wall_seconds=_minimum(budgets, "max_wall_seconds"),
            allow_unknown_pricing=all(policy.allow_unknown_pricing for policy in budgets),
        ),
    )


@dataclass(frozen=True)
class TaskEstimate:
    input_tokens: int = 8_000
    output_tokens: int = 4_000
    minimum_context_tokens: int = 16_000


def estimate_model_cost(model: AIModelRecord, estimate: TaskEstimate) -> float | None:
    if model.provider == "ollama":
        return 0.0
    pricing = model.pricing
    if pricing.input_per_million is None or pricing.output_per_million is None:
        return None
    return (
        estimate.input_tokens * pricing.input_per_million
        + estimate.output_tokens * pricing.output_per_million
    ) / 1_000_000


class WorkerSelectionService:
    RECORD_TYPE = "selection"

    def __init__(self, store: StateStore):
        self.store = store

    def select(
        self,
        task_id: str,
        models: list[AIModelRecord],
        endpoints: dict[str, AIEndpointRecord],
        policy: WorkerSelectionPolicy,
        estimate: TaskEstimate | None = None,
        catalog_snapshot_ids: list[str] | None = None,
    ) -> WorkerSelectionDecision:
        estimate = estimate or TaskEstimate()
        endpoint_health = self._latest_endpoint_health()
        candidates = [
            self._score(
                model,
                endpoints.get(model.endpoint_id),
                endpoint_health.get(model.endpoint_id),
                policy,
                estimate,
            )
            for model in models
        ]
        eligible = [candidate for candidate in candidates if candidate.eligible]
        eligible.sort(key=lambda item: (-(item.score or 0), item.model_key))
        selected = eligible[0].model_key if eligible else None
        reason = (
            f"Selected {selected} as the highest deterministic {policy.priority} score"
            if selected
            else "No model satisfied the composed Worker policy"
        )
        decision = WorkerSelectionDecision(
            decision_id=f"selection_{uuid4().hex}",
            task_id=task_id,
            policy=policy,
            catalog_snapshot_ids=catalog_snapshot_ids or [],
            candidates=candidates,
            selected_model_key=selected,
            reason=reason,
        )
        self.store.set_ai_record(
            self.RECORD_TYPE, decision.decision_id, decision.model_dump(mode="json")
        )
        return decision

    @staticmethod
    def _score(
        model: AIModelRecord,
        endpoint: AIEndpointRecord | None,
        endpoint_healthy: bool | None,
        policy: WorkerSelectionPolicy,
        estimate: TaskEstimate,
    ) -> CandidateScore:
        rejected: list[str] = []
        if endpoint is None or not endpoint.enabled:
            rejected.append("endpoint is missing or disabled")
        if endpoint_healthy is False:
            rejected.append("endpoint is currently unhealthy")
        local = bool(endpoint and endpoint_is_local(endpoint))
        if not local and not policy.cloud_allowed:
            rejected.append("cloud use is not authorized")
        if policy.allowed_endpoints and model.endpoint_id not in policy.allowed_endpoints:
            rejected.append("endpoint is not allowed")
        if policy.allowed_providers and model.provider not in policy.allowed_providers:
            rejected.append("provider is not allowed")
        if policy.allowed_models and model.model_key not in policy.allowed_models:
            rejected.append("model is not allowed")
        if model.provider == "ollama" and model.availability != "available":
            rejected.append(f"local model availability is {model.availability}")
        if model.probe_state == "absent":
            rejected.append("coding-worker probe is absent")
        elif model.probe_stale or model.probe_state == "stale":
            rejected.append("coding-worker probe is stale")
        if model.classification != policy.required_classification:
            rejected.append(
                f"requires {policy.required_classification} classification; got {model.classification}"
            )
        if model.context_tokens and model.context_tokens < estimate.minimum_context_tokens:
            rejected.append("context window is below the task estimate")
        cost = estimate_model_cost(model, estimate)
        budget = policy.budget
        if budget.enabled and cost is None and not budget.allow_unknown_pricing:
            rejected.append("pricing is unknown under an enabled budget")
        if (
            budget.enabled
            and budget.max_estimated_usd is not None
            and cost is not None
            and cost > budget.max_estimated_usd
        ):
            rejected.append("estimated cost exceeds task budget")
        components: dict[str, float] = {}
        if not rejected:
            if model.model_key in policy.preferred_models:
                rank = policy.preferred_models.index(model.model_key)
                components["preference"] = 10_000.0 - rank
            else:
                components["preference"] = 0.0
            components["local"] = 1000.0 if local and policy.local_first else 0.0
            components["cost"] = 100.0 / (1.0 + (cost or 0.0) * 100)
            context = float(model.context_tokens or estimate.minimum_context_tokens)
            components["capacity"] = min(context / 100_000, 10.0)
            if policy.priority == "economy":
                score = components["preference"] + components["local"] + components["cost"] * 10 - components["capacity"]
            elif policy.priority == "quality":
                score = components["preference"] + components["local"] * 0.1 + components["capacity"] * 100 + components["cost"]
            elif policy.priority == "urgent":
                score = components["preference"] + components["local"] * 0.25 + components["capacity"] * 50 + components["cost"]
            else:
                score = components["preference"] + components["local"] * 0.5 + components["cost"] * 5 + components["capacity"] * 20
        else:
            score = None
        return CandidateScore(
            model_key=model.model_key,
            eligible=not rejected,
            rejection_reasons=rejected,
            components=components,
            estimated_cost_usd=cost,
            score=score,
        )

    def _latest_endpoint_health(self) -> dict[str, bool]:
        latest: dict[str, tuple[str, bool]] = {}
        for value in self.store.list_ai_records("endpoint_health"):
            endpoint_id = value.get("endpoint_id")
            checked_at = value.get("checked_at", "")
            if not endpoint_id:
                continue
            current = latest.get(endpoint_id)
            if current is None or checked_at > current[0]:
                latest[endpoint_id] = (checked_at, bool(value.get("available")))
        return {endpoint_id: value[1] for endpoint_id, value in latest.items()}

    def explain(self, decision_id: str) -> dict:
        value = self.store.get_ai_record(self.RECORD_TYPE, decision_id)
        if not value:
            raise WorkerSelectionError(f"Worker selection not found: {decision_id}")
        decision = WorkerSelectionDecision.model_validate(value)
        return {
            "decision_id": decision.decision_id,
            "selected": decision.selected_model_key,
            "reason": decision.reason,
            "priority": decision.policy.priority,
            "candidates": [candidate.model_dump(mode="json") for candidate in decision.candidates],
        }
