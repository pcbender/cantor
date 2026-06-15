from __future__ import annotations

from canto.core.ai_endpoints import CLOUD_PROVIDERS, endpoint_is_local
from canto.core.state import StateStore
from canto.models.ai_workers import (
    AIEndpointRecord,
    AIModelRecord,
    WorkerSelectionPolicy,
)
from canto.core.repository import RepositoryDoctorCheck


def ai_worker_readiness_checks(
    store: StateStore, policy: WorkerSelectionPolicy
) -> list[RepositoryDoctorCheck]:
    endpoints = {
        value["endpoint_id"]: AIEndpointRecord.model_validate(value)
        for value in store.list_ai_records("endpoint")
    }
    models = {
        value["model_key"]: AIModelRecord.model_validate(value)
        for value in store.list_ai_records("model")
    }
    health = _latest_health(store)
    checks = [_endpoint_check(endpoints, policy)]
    checks.append(_model_check(models, endpoints, health, policy))
    checks.append(_local_check(models, endpoints, health, policy))
    checks.append(_cloud_check(models, endpoints, health, policy))
    return checks


def _endpoint_check(
    endpoints: dict[str, AIEndpointRecord], policy: WorkerSelectionPolicy
) -> RepositoryDoctorCheck:
    missing = [key for key in policy.allowed_endpoints if key not in endpoints]
    disabled = [
        key
        for key in policy.allowed_endpoints
        if key in endpoints and not endpoints[key].enabled
    ]
    problems = []
    if missing:
        problems.append("missing=" + ",".join(sorted(missing)))
    if disabled:
        problems.append("disabled=" + ",".join(sorted(disabled)))
    return RepositoryDoctorCheck(
        name="ai_worker_endpoints",
        valid=not problems,
        detail="configured policy endpoints are available" if not problems else "; ".join(problems),
    )


def _model_check(
    models: dict[str, AIModelRecord],
    endpoints: dict[str, AIEndpointRecord],
    health: dict[str, bool],
    policy: WorkerSelectionPolicy,
) -> RepositoryDoctorCheck:
    if not policy.allowed_models:
        return RepositoryDoctorCheck(
            name="ai_worker_models",
            valid=True,
            detail="no explicit model allowlist",
        )
    statuses = {
        key: _model_status(models.get(key), endpoints, health, policy)
        for key in policy.allowed_models
    }
    invalid = {key: value for key, value in statuses.items() if value != "ready"}
    detail = ", ".join(f"{key}={value}" for key, value in sorted(statuses.items()))
    return RepositoryDoctorCheck(
        name="ai_worker_models",
        valid=not invalid,
        detail=detail,
    )


def _local_check(
    models: dict[str, AIModelRecord],
    endpoints: dict[str, AIEndpointRecord],
    health: dict[str, bool],
    policy: WorkerSelectionPolicy,
) -> RepositoryDoctorCheck:
    local_models = [
        model
        for model in models.values()
        if (endpoint := endpoints.get(model.endpoint_id)) and endpoint_is_local(endpoint)
    ]
    ready = [
        model.model_key
        for model in local_models
        if _model_status(model, endpoints, health, policy) == "ready"
    ]
    unavailable = [
        f"{model.model_key}={_model_status(model, endpoints, health, policy)}"
        for model in local_models
        if model.model_key not in ready
    ]
    required = not policy.cloud_allowed and bool(
        policy.allowed_endpoints
        or policy.allowed_models
        or policy.allowed_providers
    )
    if ready:
        detail = "ready=" + ",".join(sorted(ready))
        if unavailable:
            detail += "; unavailable=" + ",".join(sorted(unavailable))
        return RepositoryDoctorCheck(
            name="ai_local_models", valid=True, detail=detail, severity="warning"
        )
    detail = (
        "no configured local models"
        if not local_models
        else "unavailable=" + ",".join(sorted(unavailable))
    )
    return RepositoryDoctorCheck(
        name="ai_local_models",
        valid=False,
        detail=detail,
        severity="error" if required else "warning",
    )


def _cloud_check(
    models: dict[str, AIModelRecord],
    endpoints: dict[str, AIEndpointRecord],
    health: dict[str, bool],
    policy: WorkerSelectionPolicy,
) -> RepositoryDoctorCheck:
    cloud_models = [
        model
        for model in models.values()
        if (endpoint := endpoints.get(model.endpoint_id))
        and endpoint.provider in CLOUD_PROVIDERS
    ]
    ready = [
        model.model_key
        for model in cloud_models
        if _model_status(model, endpoints, health, policy) == "ready"
    ]
    if not policy.cloud_allowed:
        return RepositoryDoctorCheck(
            name="ai_cloud_models",
            valid=True,
            detail="cloud use is disabled by repository policy",
            severity="warning",
        )
    required = bool(
        policy.allowed_endpoints
        or policy.allowed_models
        or policy.allowed_providers
    )
    return RepositoryDoctorCheck(
        name="ai_cloud_models",
        valid=bool(ready),
        detail=(
            "ready=" + ",".join(sorted(ready))
            if ready
            else "no ready cloud models"
        ),
        severity="error" if required else "warning",
    )


def _model_status(
    model: AIModelRecord | None,
    endpoints: dict[str, AIEndpointRecord],
    health: dict[str, bool],
    policy: WorkerSelectionPolicy,
) -> str:
    if model is None:
        return "missing"
    endpoint = endpoints.get(model.endpoint_id)
    if endpoint is None:
        return "endpoint_missing"
    if not endpoint.enabled:
        return "endpoint_disabled"
    if health.get(model.endpoint_id) is False:
        return "endpoint_unhealthy"
    if model.provider == "ollama" and model.availability != "available":
        return model.availability
    if model.probe_state != "current" or model.probe_stale:
        return f"probe_{model.probe_state}"
    if model.classification != policy.required_classification:
        return f"classification_{model.classification}"
    return "ready"


def _latest_health(store: StateStore) -> dict[str, bool]:
    latest: dict[str, tuple[str, bool]] = {}
    for value in store.list_ai_records("endpoint_health"):
        endpoint_id = value.get("endpoint_id")
        if not endpoint_id:
            continue
        checked_at = value.get("checked_at", "")
        if endpoint_id not in latest or checked_at > latest[endpoint_id][0]:
            latest[endpoint_id] = (checked_at, bool(value.get("available")))
    return {key: value[1] for key, value in latest.items()}
