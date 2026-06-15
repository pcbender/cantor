from __future__ import annotations

from canto.core.ai_readiness import ai_worker_readiness_checks
from canto.core.state import MemoryStateStore
from canto.models.ai_workers import (
    AIEndpointRecord,
    AIModelRecord,
    WorkerSelectionPolicy,
)


def save(store, kind, key, value):
    store.set_ai_record(kind, key, value.model_dump(mode="json"))


def model(key, endpoint, provider):
    return AIModelRecord(
        model_key=key,
        endpoint_id=endpoint,
        provider=provider,
        provider_model_id=key.split(":", 1)[1],
        resolved_version="v1",
        classification="implementation",
        probe_version="1",
        probe_stale=False,
        probe_state="current",
        availability="available",
        catalog_checksum="checksum",
    )


def test_readiness_reports_missing_policy_cloud_models_and_optional_local_warning():
    store = MemoryStateStore()
    save(
        store,
        "endpoint",
        "openai-primary",
        AIEndpointRecord(
            endpoint_id="openai-primary",
            provider="openai",
            base_url="https://api.openai.com",
        ),
    )
    policy = WorkerSelectionPolicy(
        cloud_allowed=True,
        local_first=True,
        allowed_endpoints=["openai-primary"],
        allowed_models=["openai-primary:missing"],
    )

    checks = {check.name: check for check in ai_worker_readiness_checks(store, policy)}

    assert checks["ai_worker_models"].valid is False
    assert "openai-primary:missing=missing" in checks["ai_worker_models"].detail
    assert checks["ai_local_models"].valid is False
    assert checks["ai_local_models"].severity == "warning"
    assert checks["ai_cloud_models"].valid is False


def test_readiness_reports_ready_local_and_cloud_models():
    store = MemoryStateStore()
    local_endpoint = AIEndpointRecord(
        endpoint_id="local", provider="ollama", base_url="http://localhost:11434"
    )
    cloud_endpoint = AIEndpointRecord(
        endpoint_id="cloud", provider="openai", base_url="https://api.openai.com"
    )
    save(store, "endpoint", "local", local_endpoint)
    save(store, "endpoint", "cloud", cloud_endpoint)
    save(store, "model", "local:coder", model("local:coder", "local", "ollama"))
    save(store, "model", "cloud:coder", model("cloud:coder", "cloud", "openai"))
    policy = WorkerSelectionPolicy(cloud_allowed=True)

    checks = {check.name: check for check in ai_worker_readiness_checks(store, policy)}

    assert checks["ai_local_models"].valid is True
    assert checks["ai_cloud_models"].valid is True


def test_unconfigured_default_policy_reports_warning_without_blocking():
    checks = {
        check.name: check
        for check in ai_worker_readiness_checks(
            MemoryStateStore(), WorkerSelectionPolicy()
        )
    }

    assert checks["ai_local_models"].valid is False
    assert checks["ai_local_models"].severity == "warning"
    assert checks["ai_cloud_models"].valid is True


def test_explicit_local_only_policy_blocks_when_model_is_missing():
    policy = WorkerSelectionPolicy(
        cloud_allowed=False,
        allowed_endpoints=["local"],
        allowed_models=["local:coder"],
    )

    checks = {
        check.name: check
        for check in ai_worker_readiness_checks(MemoryStateStore(), policy)
    }

    assert checks["ai_worker_endpoints"].valid is False
    assert checks["ai_worker_models"].valid is False
    assert checks["ai_local_models"].valid is False
    assert checks["ai_local_models"].severity == "error"
