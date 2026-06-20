from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from canto.models.schemas import utc_now


AIProvider = Literal["openai", "anthropic", "google", "openai_compatible", "ollama"]
WorkerClassification = Literal[
    "implementation", "advisory", "unavailable", "unvalidated"
]
PriorityLevel = Literal["economy", "balanced", "quality", "urgent"]
WorkerTransport = Literal["http", "cli"]
ModelAvailability = Literal["available", "missing", "endpoint_unreachable", "unknown"]
ProbeState = Literal["current", "stale", "absent"]
MetadataSourceKind = Literal["runtime", "declared", "curated", "observed"]


class AIEndpointRecord(BaseModel):
    endpoint_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    provider: AIProvider
    base_url: str
    credential_ref: str | None = None
    enabled: bool = True
    validation_status: Literal["unvalidated", "valid", "invalid"] = "unvalidated"
    validation_detail: str = ""
    validated_at: str | None = None
    capabilities: dict[str, Any] = Field(default_factory=dict)
    configuration: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)


class ModelPricing(BaseModel):
    currency: str = "USD"
    input_per_million: float | None = Field(default=None, ge=0)
    cached_input_per_million: float | None = Field(default=None, ge=0)
    output_per_million: float | None = Field(default=None, ge=0)
    source: str | None = None
    version: str | None = None


class AIModelRecord(BaseModel):
    model_key: str
    endpoint_id: str
    provider: AIProvider
    provider_model_id: str
    resolved_version: str
    display_name: str | None = None
    aliases: list[str] = Field(default_factory=list)
    context_tokens: int | None = Field(default=None, ge=1)
    max_output_tokens: int | None = Field(default=None, ge=1)
    capabilities: dict[str, bool] = Field(default_factory=dict)
    pricing: ModelPricing = Field(default_factory=ModelPricing)
    classification: WorkerClassification = "unvalidated"
    probe_version: str | None = None
    probe_stale: bool = True
    probe_state: ProbeState = "absent"
    availability: ModelAvailability = "unknown"
    availability_reason: str = ""
    last_seen_at: str | None = None
    missing_since: str | None = None
    runtime_metadata: dict[str, Any] = Field(default_factory=dict)
    metadata_provenance: list[str] = Field(default_factory=list)
    catalog_checksum: str
    discovered_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)

    @model_validator(mode="before")
    @classmethod
    def infer_legacy_probe_state(cls, value):
        if isinstance(value, dict) and "probe_state" not in value:
            if value.get("probe_version") and not value.get("probe_stale", True):
                value = {**value, "probe_state": "current"}
            elif value.get("probe_version"):
                value = {**value, "probe_state": "stale"}
        return value


class ModelCatalogSnapshot(BaseModel):
    snapshot_id: str
    endpoint_id: str
    models: list[str] = Field(default_factory=list)
    response_checksum: str
    mode: Literal["discover", "refresh"] = "discover"
    authoritative_success: bool = True
    added: list[str] = Field(default_factory=list)
    changed: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    unchanged: list[str] = Field(default_factory=list)
    discovered_at: str = Field(default_factory=utc_now)


class ModelReconciliationRecord(BaseModel):
    reconciliation_id: str
    endpoint_id: str
    previous_snapshot_id: str | None = None
    current_snapshot_id: str | None = None
    authoritative_success: bool
    added: list[str] = Field(default_factory=list)
    changed: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    unchanged: list[str] = Field(default_factory=list)
    error: str | None = None
    created_at: str = Field(default_factory=utc_now)


class ModelMetadataRecord(BaseModel):
    metadata_id: str
    model_key: str
    source_kind: MetadataSourceKind
    source_uri: str | None = None
    source_checksum: str | None = None
    fields: dict[str, Any] = Field(default_factory=dict)
    confidence: Literal["low", "medium", "high"] = "medium"
    reviewed: bool = False
    created_at: str = Field(default_factory=utc_now)


class ProbeAssertion(BaseModel):
    name: str
    passed: bool
    detail: str = ""


class WorkerProbeResult(BaseModel):
    probe_id: str
    model_key: str
    endpoint_id: str
    provider_model_id: str
    resolved_version: str
    probe_version: str
    classification: WorkerClassification
    assertions: list[ProbeAssertion] = Field(default_factory=list)
    artifact_root: str | None = None
    evidence_checksum: str | None = None
    estimated_cost_usd: float | None = Field(default=None, ge=0)
    actual_cost_usd: float | None = Field(default=None, ge=0)
    started_at: str = Field(default_factory=utc_now)
    ended_at: str | None = None


class WorkerBudgetPolicy(BaseModel):
    enabled: bool = False
    max_estimated_usd: float | None = Field(default=None, ge=0)
    max_actual_usd: float | None = Field(default=None, ge=0)
    max_input_tokens: int | None = Field(default=None, ge=1)
    max_output_tokens: int | None = Field(default=None, ge=1)
    max_turns: int | None = Field(default=None, ge=1)
    max_tool_calls: int | None = Field(default=None, ge=1)
    max_wall_seconds: int | None = Field(default=None, ge=1)
    allow_unknown_pricing: bool = False


class WorkerSelectionPolicy(BaseModel):
    priority: PriorityLevel = "balanced"
    allowed_transports: list[WorkerTransport] = Field(default_factory=list)
    allowed_endpoints: list[str] = Field(default_factory=list)
    allowed_providers: list[AIProvider] = Field(default_factory=list)
    allowed_models: list[str] = Field(default_factory=list)
    preferred_models: list[str] = Field(default_factory=list)
    allowed_cli_profile_pools: list[str] = Field(default_factory=list)
    preferred_cli_profile_pools: list[str] = Field(default_factory=list)
    allowed_cli_profiles: list[str] = Field(default_factory=list)
    preferred_cli_profiles: list[str] = Field(default_factory=list)
    prefer_subscription_cli: bool = False
    api_fallback_requires_approval: bool = True
    orchestrator_provider: str | None = None
    cloud_allowed: bool = False
    cloud_fallback_allowed: bool = False
    local_first: bool = True
    required_classification: Literal["implementation", "advisory"] = "implementation"
    budget: WorkerBudgetPolicy = Field(default_factory=WorkerBudgetPolicy)


class CandidateScore(BaseModel):
    model_key: str
    eligible: bool
    rejection_reasons: list[str] = Field(default_factory=list)
    components: dict[str, float] = Field(default_factory=dict)
    estimated_cost_usd: float | None = None
    score: float | None = None


class WorkerSelectionDecision(BaseModel):
    decision_id: str
    task_id: str
    policy: WorkerSelectionPolicy
    catalog_snapshot_ids: list[str] = Field(default_factory=list)
    candidates: list[CandidateScore] = Field(default_factory=list)
    selected_model_key: str | None = None
    reason: str
    created_at: str = Field(default_factory=utc_now)


class WorkerUsageRecord(BaseModel):
    usage_id: str
    task_id: str
    session_id: str | None = None
    decision_id: str | None = None
    model_key: str
    endpoint_id: str
    provider_model_id: str
    resolved_version: str
    input_tokens: int = Field(default=0, ge=0)
    cached_input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    reasoning_tokens: int = Field(default=0, ge=0)
    turns: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    tool_names: list[str] = Field(default_factory=list)
    estimated_cost_usd: float | None = Field(default=None, ge=0)
    actual_cost_usd: float | None = Field(default=None, ge=0)
    provider_request_ids: list[str] = Field(default_factory=list)
    terminal_reason: str = ""
    started_at: str = Field(default_factory=utc_now)
    ended_at: str | None = None


class EndpointHealthRecord(BaseModel):
    health_id: str
    endpoint_id: str
    available: bool
    detail: str = ""
    latency_ms: float | None = Field(default=None, ge=0)
    cooldown_until: str | None = None
    checked_at: str = Field(default_factory=utc_now)
