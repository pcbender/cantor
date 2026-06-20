from __future__ import annotations

from canto.core.ai_selection import (
    TaskEstimate,
    WorkerSelectionService,
    compose_worker_policy,
)
from canto.core.state import MemoryStateStore
from canto.models.ai_workers import (
    AIEndpointRecord,
    AIModelRecord,
    EndpointHealthRecord,
    ModelPricing,
    WorkerBudgetPolicy,
    WorkerSelectionPolicy,
)


def model(key, endpoint, provider, *, cost=1.0, context=32000):
    return AIModelRecord(
        model_key=key,
        endpoint_id=endpoint,
        provider=provider,
        provider_model_id=key,
        resolved_version="v1",
        context_tokens=context,
        classification="implementation",
        probe_stale=False,
        probe_state="current",
        availability="available",
        catalog_checksum="checksum",
        pricing=ModelPricing(input_per_million=cost, output_per_million=cost),
    )


def test_policy_composition_never_widens_cloud_or_allowlists():
    global_policy = WorkerSelectionPolicy(
        cloud_allowed=True,
        allowed_transports=["cli", "http"],
        allowed_providers=["openai", "anthropic"],
        allowed_cli_profiles=["codex", "claude"],
        budget=WorkerBudgetPolicy(enabled=True, max_estimated_usd=2),
    )
    repo_policy = WorkerSelectionPolicy(
        priority="economy",
        cloud_allowed=False,
        allowed_transports=["cli"],
        allowed_providers=["openai"],
        preferred_models=["openai:small", "openai:large"],
        allowed_cli_profiles=["codex"],
        preferred_cli_profiles=["codex"],
        prefer_subscription_cli=True,
        budget=WorkerBudgetPolicy(enabled=True, max_estimated_usd=1),
    )

    result = compose_worker_policy(global_policy, repo_policy)

    assert result.cloud_allowed is False
    assert result.allowed_transports == ["cli"]
    assert result.allowed_providers == ["openai"]
    assert result.preferred_models == ["openai:small", "openai:large"]
    assert result.allowed_cli_profiles == ["codex"]
    assert result.preferred_cli_profiles == ["codex"]
    assert result.prefer_subscription_cli is True
    assert result.budget.max_estimated_usd == 1


def test_selection_is_deterministic_local_first_and_persisted():
    store = MemoryStateStore()
    selector = WorkerSelectionService(store)
    endpoints = {
        "local": AIEndpointRecord(endpoint_id="local", provider="ollama", base_url="http://localhost:11434"),
        "cloud": AIEndpointRecord(endpoint_id="cloud", provider="openai", base_url="https://api.openai.com"),
    }
    models = [
        model("cloud:small", "cloud", "openai", cost=0.1),
        model("local:coder", "local", "ollama", cost=0),
    ]

    decision = selector.select(
        "task-1", models, endpoints, WorkerSelectionPolicy(cloud_allowed=True)
    )

    assert decision.selected_model_key == "local:coder"
    assert selector.explain(decision.decision_id)["selected"] == "local:coder"


def test_explicit_model_preference_controls_first_choice_and_keeps_fallback():
    store = MemoryStateStore()
    selector = WorkerSelectionService(store)
    endpoint = AIEndpointRecord(
        endpoint_id="local", provider="ollama", base_url="http://localhost:11434"
    )
    smaller = model("local:gemma", "local", "ollama")
    preferred = model("local:qwen", "local", "ollama")
    policy = WorkerSelectionPolicy(
        allowed_models=[smaller.model_key, preferred.model_key],
        preferred_models=[preferred.model_key, smaller.model_key],
    )

    first = selector.select(
        "task-preferred", [smaller, preferred], {"local": endpoint}, policy
    )
    fallback = selector.select(
        "task-fallback", [smaller], {"local": endpoint}, policy
    )

    assert first.selected_model_key == preferred.model_key
    assert fallback.selected_model_key == smaller.model_key


def test_selection_reports_stale_probe_and_budget_rejections():
    store = MemoryStateStore()
    selector = WorkerSelectionService(store)
    endpoint = AIEndpointRecord(endpoint_id="cloud", provider="openai", base_url="https://api.openai.com")
    stale = model("cloud:stale", "cloud", "openai").model_copy(update={"probe_stale": True})
    costly = model("cloud:costly", "cloud", "openai", cost=100)
    policy = WorkerSelectionPolicy(
        cloud_allowed=True,
        budget=WorkerBudgetPolicy(enabled=True, max_estimated_usd=0.01),
    )

    decision = selector.select(
        "task-2",
        [stale, costly],
        {"cloud": endpoint},
        policy,
        TaskEstimate(input_tokens=1000, output_tokens=1000),
    )

    assert decision.selected_model_key is None
    reasons = {item.model_key: item.rejection_reasons for item in decision.candidates}
    assert "coding-worker probe is stale" in reasons["cloud:stale"]
    assert "estimated cost exceeds task budget" in reasons["cloud:costly"]


def test_selection_rejects_missing_local_model_with_specific_reason():
    store = MemoryStateStore()
    selector = WorkerSelectionService(store)
    endpoint = AIEndpointRecord(
        endpoint_id="local", provider="ollama", base_url="http://localhost:11434"
    )
    missing = model("local:gone", "local", "ollama").model_copy(
        update={"availability": "missing"}
    )

    decision = selector.select(
        "task-3", [missing], {"local": endpoint}, WorkerSelectionPolicy()
    )

    assert decision.selected_model_key is None
    assert decision.candidates[0].rejection_reasons == [
        "local model availability is missing"
    ]


def test_selection_distinguishes_absent_probe_from_stale_probe():
    store = MemoryStateStore()
    selector = WorkerSelectionService(store)
    endpoint = AIEndpointRecord(
        endpoint_id="local", provider="ollama", base_url="http://localhost:11434"
    )
    unprobed = model("local:new", "local", "ollama").model_copy(
        update={"probe_state": "absent", "probe_stale": True}
    )

    decision = selector.select(
        "task-4", [unprobed], {"local": endpoint}, WorkerSelectionPolicy()
    )

    assert decision.candidates[0].rejection_reasons == [
        "coding-worker probe is absent"
    ]


def test_selection_rejects_latest_explicitly_unhealthy_endpoint():
    store = MemoryStateStore()
    selector = WorkerSelectionService(store)
    endpoint = AIEndpointRecord(
        endpoint_id="local", provider="ollama", base_url="http://localhost:11434"
    )
    store.set_ai_record(
        "endpoint_health",
        "health-old",
        EndpointHealthRecord(
            health_id="health-old",
            endpoint_id="local",
            available=True,
            checked_at="2026-06-15T10:00:00Z",
        ).model_dump(mode="json"),
    )
    store.set_ai_record(
        "endpoint_health",
        "health-new",
        EndpointHealthRecord(
            health_id="health-new",
            endpoint_id="local",
            available=False,
            checked_at="2026-06-15T11:00:00Z",
        ).model_dump(mode="json"),
    )

    decision = selector.select(
        "task-5",
        [model("local:coder", "local", "ollama")],
        {"local": endpoint},
        WorkerSelectionPolicy(),
    )

    assert decision.selected_model_key is None
    assert "endpoint is currently unhealthy" in decision.candidates[0].rejection_reasons
