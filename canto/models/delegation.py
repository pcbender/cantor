from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from canto.models.schemas import utc_now
from canto.models.ai_workers import PriorityLevel, WorkerSelectionPolicy


DelegationStatus = Literal[
    "draft",
    "assigned",
    "workspace_ready",
    "executor_working",
    "executor_blocked",
    "executor_done",
    "reviewing",
    "revision_requested",
    "accepted",
    "promoting",
    "promoted",
    "promotion_failed",
    "rejected",
    "cancelled",
    "failed",
]


class RepositoryIdentity(BaseModel):
    repo_id: str | None = None
    canonical_path: str
    git_common_dir: str | None = None
    initial_head: str | None = None
    remotes: dict[str, str] = Field(default_factory=dict)


class DelegationScope(BaseModel):
    allowed_paths: list[str] = Field(default_factory=list)
    denied_paths: list[str] = Field(default_factory=list)
    allowed_commands: list[str] = Field(default_factory=list)
    required_commands: list[str] = Field(default_factory=list)
    allow_network: bool = False
    allow_secrets: bool = False


class DelegationTask(BaseModel):
    task_id: str
    title: str
    status: DelegationStatus = "draft"
    repository: RepositoryIdentity
    scope: DelegationScope = Field(default_factory=DelegationScope)
    instructions: str = ""
    comparison_id: str | None = None
    variant_name: str | None = None
    prompt_supplement: str | None = None
    created_by: str = "cantor"
    executor_id: str | None = None
    workspace_id: str | None = None
    latest_result_revision: int = 0
    accepted_result_revision: int | None = None
    worker_priority: PriorityLevel = "balanced"
    worker_policy: WorkerSelectionPolicy | None = None
    selection_decision_id: str | None = None
    selected_model_key: str | None = None
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)


class DelegationWorkspace(BaseModel):
    workspace_id: str
    task_id: str
    path: str
    branch: str
    base_commit: str
    repository: RepositoryIdentity
    allowed_paths: list[str] = Field(default_factory=list)
    denied_paths: list[str] = Field(default_factory=list)
    status: Literal["ready", "removed"] = "ready"
    created_at: str = Field(default_factory=utc_now)
    removed_at: str | None = None


class ExecutorPermissions(BaseModel):
    allow_network: bool = False
    allow_secrets: bool = False
    command_enforcement: Literal["manual_unverified", "canto_observed"] = (
        "manual_unverified"
    )


class ExecutorProfile(BaseModel):
    executor_id: str
    name: str
    harness: Literal["manual", "codex_cli", "api_worker"]
    executable: str | None = None
    configuration: dict[str, Any] = Field(default_factory=dict)
    model_provider: str | None = None
    model: str | None = None
    launch_mode: Literal["manual", "canto"] = "manual"
    permissions: ExecutorPermissions = Field(default_factory=ExecutorPermissions)
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)


class ExecutorSession(BaseModel):
    session_id: str
    task_id: str
    executor_id: str
    status: Literal["prepared", "running", "blocked", "completed", "failed"]
    enforcement: Literal["manual_unverified", "canto_observed"]
    started_at: str | None = None
    ended_at: str | None = None


class ExecutorLaunch(BaseModel):
    launch_id: str
    task_id: str
    session_id: str
    executor_id: str
    argv: list[str]
    cwd: str
    prompt_path: str
    stdout_path: str
    stderr_path: str
    prompt_variant: str | None = None
    prompt_supplement: str | None = None
    token_usage: dict[str, int] | None = None
    workspace_changed: bool | None = None
    outcome: Literal["completed_work", "advisory", "no_work", "failed"] | None = None
    outcome_detail: str | None = None
    exit_code: int | None = None
    timed_out: bool = False
    started_at: str = Field(default_factory=utc_now)
    ended_at: str | None = None


class DelegationMessage(BaseModel):
    message_id: str
    task_id: str
    sender: Literal["orchestrator", "executor"]
    kind: Literal["assignment", "progress", "blocker", "revision", "done"]
    body: str
    created_at: str = Field(default_factory=utc_now)


class DelegationArtifact(BaseModel):
    name: str
    relative_path: str
    sha256: str
    size: int


class DelegationResult(BaseModel):
    result_id: str
    task_id: str
    revision: int
    base_commit: str
    workspace_patch_sha256: str
    artifacts: list[DelegationArtifact] = Field(default_factory=list)
    executor_summary: str = ""
    producing_session_id: str | None = None
    producing_launch_id: str | None = None
    prompt_variant: str | None = None
    created_at: str = Field(default_factory=utc_now)


class DelegationReview(BaseModel):
    review_id: str
    task_id: str
    result_revision: int
    decision: Literal["revision_requested", "accepted", "rejected"]
    reviewer: str
    note: str = ""
    created_at: str = Field(default_factory=utc_now)


class PromotionDecision(BaseModel):
    decision_id: str
    task_id: str
    result_revision: int
    decision: Literal["promote", "cancel"]
    decided_by: str
    note: str = ""
    created_at: str = Field(default_factory=utc_now)


class PromotionResult(BaseModel):
    promotion_id: str
    task_id: str
    result_revision: int
    status: Literal["promoted", "promotion_failed"]
    changed_files: list[str] = Field(default_factory=list)
    repository_head: str
    rollback_attempted: bool = False
    rollback_succeeded: bool | None = None
    error: str | None = None
    created_at: str = Field(default_factory=utc_now)


class CommandRecord(BaseModel):
    record_id: str
    task_id: str
    command: str
    argv: list[str] = Field(default_factory=list)
    cwd: str = "."
    source: Literal["executor_reported", "canto_observed"]
    status: Literal["reported", "passed", "failed", "waived"]
    exit_code: int | None = None
    stdout_path: str | None = None
    stderr_path: str | None = None
    waiver_reason: str | None = None
    created_at: str = Field(default_factory=utc_now)


class DelegationEvent(BaseModel):
    event_id: str
    task_id: str
    event_type: str
    status: DelegationStatus
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now)


class ExecutorPoolEntry(BaseModel):
    executor_id: str
    harness: Literal["manual", "codex_cli"]
    available: bool
    availability_detail: str
    active_tasks: int = 0
    task_ids: list[str] = Field(default_factory=list)


class DelegationTaskStatus(BaseModel):
    task_id: str
    title: str
    status: DelegationStatus
    executor_id: str | None = None
    workspace_id: str | None = None
    latest_result_revision: int = 0
    updated_at: str


class PromotionQueueEntry(BaseModel):
    queue_id: str
    task_id: str
    result_revision: int
    base_commit: str
    changed_files: list[str] = Field(default_factory=list)
    status: Literal["pending", "blocked", "promoted", "failed"] = "pending"
    blockers: list[str] = Field(default_factory=list)
    enqueued_by: str
    created_at: str = Field(default_factory=utc_now)


class DelegationTimelineItem(BaseModel):
    timestamp: str
    kind: str
    record_id: str
    summary: str
    data: dict[str, Any] = Field(default_factory=dict)


class DelegationDashboardTask(BaseModel):
    task_id: str
    title: str
    status: DelegationStatus
    attention: Literal["working", "review", "blocked", "ready", "terminal"]
    executor_id: str | None = None
    harness: str | None = None
    repository: str
    latest_result_revision: int = 0
    accepted_result_revision: int | None = None
    worker_outcome: Literal["completed_work", "advisory", "no_work", "failed"] | None = None
    next_action: str
    updated_at: str


class DelegationDashboardDetail(BaseModel):
    task: DelegationDashboardTask
    repository: RepositoryIdentity
    scope: DelegationScope
    workspace: dict[str, Any] | None = None
    executor: dict[str, Any] | None = None
    sessions: list[dict[str, Any]] = Field(default_factory=list)
    launches: list[dict[str, Any]] = Field(default_factory=list)
    latest_result: dict[str, Any] | None = None
    reviews: list[dict[str, Any]] = Field(default_factory=list)
    commands: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    queue: dict[str, Any] | None = None
    outcome_detail: str | None = None
    next_actions: list[str] = Field(default_factory=list)
    artifact_root: str | None = None


class DelegationVariant(BaseModel):
    name: str
    prompt_supplement: str = ""


class DelegationComparisonItem(BaseModel):
    task_id: str
    variant_name: str
    base_commit: str
    status: DelegationStatus
    result_revision: int | None = None
    changed_files: list[str] = Field(default_factory=list)
    patch_additions: int = 0
    patch_deletions: int = 0
    commands: list[dict[str, Any]] = Field(default_factory=list)
    exit_code: int | None = None
    timed_out: bool = False
    runtime_seconds: float | None = None
    token_usage: dict[str, int] | None = None
    session_id: str | None = None
    launch_id: str | None = None


class DelegationComparison(BaseModel):
    comparison_id: str
    repository: RepositoryIdentity
    base_commit: str
    variants: list[DelegationComparisonItem] = Field(default_factory=list)


class DelegationReviewSummary(BaseModel):
    task_id: str
    status: DelegationStatus
    result_revision: int
    producing_session_id: str | None = None
    producing_launch_id: str | None = None
    executor_id: str | None = None
    prompt_variant: str | None = None
    changed_files: list[str] = Field(default_factory=list)
    patch_additions: int = 0
    patch_deletions: int = 0
    commands: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    missing_commands: list[str] = Field(default_factory=list)
    artifact_checksums_valid: bool
    scope_checks_passed: bool = True
    canonical_head: str | None = None
    base_commit: str
    canonical_clean_for_changed_files: bool = False
    acceptance_ready: bool = False
    promotion_ready: bool = False
    blockers: list[str] = Field(default_factory=list)


class DelegationBlocker(BaseModel):
    code: Literal[
        "queue_overlap",
        "stale_base",
        "dirty_worktree",
        "artifact_checksum",
        "workspace_changed",
        "promotion_failure",
    ]
    message: str
    repository: str
    task_id: str
    result_revision: int | None = None
    conflicting_task_id: str | None = None
    overlapping_paths: list[str] = Field(default_factory=list)
    expected_base: str | None = None
    actual_head: str | None = None
    rollback_attempted: bool = False
    rollback_succeeded: bool | None = None
    safe_actions: list[str] = Field(default_factory=list)


class DelegationConflictReport(BaseModel):
    task_id: str
    blockers: list[DelegationBlocker] = Field(default_factory=list)
