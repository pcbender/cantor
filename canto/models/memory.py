from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from canto.models.schemas import utc_now


MemoryStatus = Literal[
    "observed",
    "proposed",
    "active",
    "superseded",
    "expired",
    "rejected",
    "deleted",
]
MemoryType = Literal[
    "terminology",
    "decision",
    "preference",
    "constraint",
    "fact",
    "observation",
    "outcome",
    "known_trap",
    "open_question",
    "summary",
    "source_pointer",
]
MemoryConfidence = Literal["verified", "supported", "derived", "observed", "uncertain"]


class MemorySourceRef(BaseModel):
    kind: str
    ref: str
    freshness: str | None = None
    resolved: bool = True


class MemoryItem(BaseModel):
    memory_id: str
    scope: str
    type: MemoryType
    status: MemoryStatus
    title: str
    body: str
    confidence: MemoryConfidence = "uncertain"
    source: MemorySourceRef
    author_kind: Literal["developer", "worker", "system"]
    author_id: str
    aliases: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    approval_id: str | None = None
    repo_id: str | None = None
    project_id: str | None = None
    low_value: bool = False
    created_at: str = Field(default_factory=utc_now)
    reviewed_at: str | None = None
    expires_at: str | None = None
    superseded_by: str | None = None
    deleted_at: str | None = None

    @model_validator(mode="after")
    def validate_scope_identity(self) -> "MemoryItem":
        if self.scope.startswith("repo:") and self.repo_id != self.scope.removeprefix("repo:"):
            raise ValueError("Repository scope must match repo_id")
        if self.scope.startswith("project:") and self.project_id != self.scope.removeprefix("project:"):
            raise ValueError("Project scope must match project_id")
        if self.scope == "global:terminology" and self.type != "terminology":
            raise ValueError("Global scope is limited to terminology")
        if not (
            self.scope == "global:terminology"
            or self.scope.startswith("repo:")
            or self.scope.startswith("project:")
            or self.scope.startswith("job:")
            or self.scope.startswith("plan:")
            or self.scope.startswith("delegation:")
            or self.scope.startswith("session:")
        ):
            raise ValueError(f"Unsupported memory scope: {self.scope}")
        return self


class MemoryEvent(BaseModel):
    event_id: str
    memory_id: str
    event_type: str
    actor_kind: Literal["developer", "worker", "system"]
    actor_id: str
    payload: dict = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now)


class MemoryLink(BaseModel):
    link_id: str
    from_memory_id: str
    to_memory_id: str
    relation: str
    created_at: str = Field(default_factory=utc_now)


class MemoryProject(BaseModel):
    project_id: str
    label: str
    created_by: str
    repository_ids: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)


class MemoryRecallResult(BaseModel):
    items: list[MemoryItem]
    estimated_tokens: int
    truncated: bool = False


class MemoryContextPack(BaseModel):
    profile: Literal["startup", "resolve-reference", "review", "planning"]
    scopes: list[str]
    sections: dict[str, list[MemoryItem]]
    estimated_tokens: int


class MemoryActivationPolicy(BaseModel):
    mode: Literal["bounded_orchestrator", "developer_only"] = "bounded_orchestrator"
    orchestrator_id: str = "local"
    auto_activate_types: list[MemoryType] = Field(
        default_factory=lambda: ["outcome", "source_pointer"]
    )
    auto_activate_scopes: list[Literal["repo", "project"]] = Field(
        default_factory=lambda: ["repo", "project"]
    )
    require_governed_source: bool = True
    require_no_conflicts: bool = True
    require_distinct_proposer_and_approver: bool = True
    allow_non_conflicting_aliases: bool = True
    max_auto_activations_per_task: int = 5
    max_auto_activations_per_day: int = 25
