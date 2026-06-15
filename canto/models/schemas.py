from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class Policy(BaseModel):
    mode: Literal["dry_run", "live"] = "dry_run"
    allow_network: bool = False
    allow_filesystem_write: bool = True
    allow_destructive: bool = False
    approved_domains: list[str] = Field(default_factory=list)


class JobRequest(BaseModel):
    skill: str
    provider: str
    goal: str = ""
    inputs: dict[str, Any] = Field(default_factory=dict)
    policy: Policy = Field(default_factory=Policy)
    requested_by: str = "echo"
    approval_id: str | None = None


class Job(BaseModel):
    job_id: str
    status: Literal[
        "queued",
        "checking_dependencies",
        "waiting_for_dependency",
        "waiting_for_approval",
        "running",
        "completed",
        "failed",
        "cancelled",
        "rejected",
    ]
    created_at: str
    updated_at: str
    requested_by: str
    skill: str
    provider: str
    goal: str
    inputs: dict[str, Any]
    policy: Policy
    artifact_dir: str
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    requires_approval: bool = False
    approval_id: str | None = None
    promotion: dict[str, Any] | None = None
    recovery: dict[str, Any] | None = None


class ApprovalDecision(BaseModel):
    approved_by: str = "cantor"
    note: str = ""


class RejectionDecision(BaseModel):
    rejected_by: str = "cantor"
    reason: str


class Approval(BaseModel):
    approval_id: str
    subject_kind: Literal["job", "plan", "memory"] | None = None
    subject_id: str | None = None
    job_id: str | None = None
    plan_id: str | None = None
    step_capability: str | None = None
    skill: str | None = None
    provider: str | None = None
    reason: str
    risk_level: int
    status: Literal["pending", "approved", "rejected"] = "pending"
    created_at: str
    updated_at: str
    decided_by: str | None = None
    note: str = ""
    promotion: dict[str, Any] | None = None
    recovery: dict[str, Any] | None = None
