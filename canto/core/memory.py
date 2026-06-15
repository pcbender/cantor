from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from canto.core.state import StateStore
from canto.models.memory import (
    MemoryActivationPolicy,
    MemoryContextPack,
    MemoryEvent,
    MemoryItem,
    MemoryProject,
    MemoryRecallResult,
    MemorySourceRef,
)
from canto.models.schemas import Approval, utc_now


class MemoryServiceError(RuntimeError):
    pass


LEGAL_TRANSITIONS = {
    "observed": {"proposed", "expired", "deleted"},
    "proposed": {"active", "rejected", "expired", "deleted"},
    "active": {"superseded", "expired", "deleted"},
    "superseded": {"deleted"},
    "expired": {"deleted"},
    "rejected": {"deleted"},
    "deleted": set(),
}

BUDGETS = {
    "startup": (12, 2500),
    "resolve-reference": (5, 750),
    "review": (20, 4000),
    "planning": (24, 5000),
}

SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\b(?:sk-|ghp_|github_pat_)[A-Za-z0-9_-]{8,}"),
    re.compile(r"(?i)\b(?:api[_-]?key|password|secret|token)\s*[:=]\s*['\"]?[A-Za-z0-9_./+\-=]{12,}"),
    re.compile(r"(?i)\bAWS_SECRET_ACCESS_KEY\s*[:=]\s*\S+"),
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_time(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def estimate_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4)


def ensure_no_secret(value: Any) -> None:
    text = json.dumps(value, sort_keys=True) if not isinstance(value, str) else value
    if any(pattern.search(text) for pattern in SECRET_PATTERNS):
        raise MemoryServiceError("Memory content was rejected because it contains secret-like material")


class MemoryService:
    def __init__(self, store: StateStore):
        self.store = store

    def status(self) -> dict[str, Any]:
        items = [MemoryItem.model_validate(value) for value in self.store.list_memory_items()]
        projects = self.store.list_memory_projects()
        return {
            "available": self.store.ping(),
            "items": len(items),
            "active": sum(item.status == "active" for item in items),
            "proposed": sum(item.status == "proposed" for item in items),
            "projects": len(projects),
        }

    def propose(
        self,
        *,
        scope: str,
        type: str,
        title: str,
        body: str,
        source_kind: str,
        source_ref: str,
        author_kind: str,
        author_id: str,
        confidence: str = "uncertain",
        aliases: list[str] | None = None,
        tags: list[str] | None = None,
        freshness: str | None = None,
        observed: bool = False,
        low_value: bool = False,
        auto_activate: bool = True,
        activation_policy: MemoryActivationPolicy | None = None,
    ) -> MemoryItem:
        ensure_no_secret({"title": title, "body": body, "source_ref": source_ref})
        self._validate_source(source_kind, source_ref)
        repo_id = scope.removeprefix("repo:") if scope.startswith("repo:") else None
        project_id = scope.removeprefix("project:") if scope.startswith("project:") else None
        if project_id and not self.store.get_memory_project(project_id):
            raise MemoryServiceError(f"Unknown memory project: {project_id}")
        item = MemoryItem(
            memory_id=f"memory_{uuid4().hex}",
            scope=scope,
            type=type,
            status="observed" if observed else "proposed",
            title=title.strip(),
            body=body.strip(),
            confidence=confidence,
            source=MemorySourceRef(kind=source_kind, ref=source_ref, freshness=freshness),
            author_kind=author_kind,
            author_id=author_id,
            aliases=sorted(set(aliases or []), key=str.casefold),
            tags=sorted(set(tags or []), key=str.casefold),
            repo_id=repo_id,
            project_id=project_id,
            low_value=low_value,
        )
        self.store.set_memory_item(item.memory_id, item.model_dump(mode="json"))
        self._event(item.memory_id, "observed" if observed else "proposed", author_kind, author_id)
        self._record_conflicts(item)
        if auto_activate and item.status == "proposed":
            activated = self.activate_by_orchestrator(
                item.memory_id,
                activation_policy or MemoryActivationPolicy(),
            )
            if activated is not None:
                return activated
        return item

    def get(self, memory_id: str) -> MemoryItem:
        value = self.store.get_memory_item(memory_id)
        if not value:
            raise MemoryServiceError(f"Unknown memory item: {memory_id}")
        return MemoryItem.model_validate(value)

    def list(self, statuses: set[str] | None = None) -> list[MemoryItem]:
        hidden = {"rejected", "expired", "superseded", "deleted"}
        items = [MemoryItem.model_validate(value) for value in self.store.list_memory_items()]
        if statuses is None:
            return [item for item in items if item.status not in hidden]
        return [item for item in items if item.status in statuses]

    def request_approval(
        self, memory_id: str, requested_by: str, actor_kind: str = "developer"
    ) -> Approval:
        item = self.get(memory_id)
        if item.status != "proposed":
            raise MemoryServiceError("Only proposed memory can request approval")
        if item.approval_id:
            raw = self.store.get_approval(item.approval_id)
            if raw:
                return Approval.model_validate(raw)
        now = utc_now()
        approval = Approval(
            approval_id=f"approval_{uuid4().hex}",
            subject_kind="memory",
            subject_id=item.memory_id,
            reason=f"Activate memory: {item.title}",
            risk_level=1,
            created_at=now,
            updated_at=now,
            note=f"Requested by {requested_by}",
        )
        self.store.set_approval(approval.approval_id, approval.model_dump(mode="json"))
        item.approval_id = approval.approval_id
        if not self.store.transition_memory_item(item.memory_id, {"proposed"}, item.model_dump(mode="json")):
            raise MemoryServiceError("Memory proposal changed while requesting approval")
        self._event(
            item.memory_id,
            "approval_requested",
            actor_kind,
            requested_by,
            {"approval_id": approval.approval_id},
        )
        return approval

    def activate_by_orchestrator(
        self, memory_id: str, policy: MemoryActivationPolicy | None = None
    ) -> MemoryItem | None:
        policy = policy or MemoryActivationPolicy()
        item = self.get(memory_id)
        allowed, reason, evidence = self._orchestrator_activation_allowed(item, policy)
        if not allowed:
            self._event(
                item.memory_id,
                "orchestrator_activation_skipped",
                "system",
                "memory-service",
                {"reason": reason, "policy": policy.model_dump(mode="json")},
            )
            return None
        approval = self.request_approval(
            item.memory_id,
            f"orchestrator:{policy.orchestrator_id}",
            actor_kind="system",
        )
        return self.decide_approval(
            approval.approval_id,
            approve=True,
            actor=f"orchestrator:{policy.orchestrator_id}",
            note=json.dumps(
                {
                    "policy": "bounded_orchestrator",
                    "reason": reason,
                    "evidence": evidence,
                },
                sort_keys=True,
            ),
            actor_kind="system",
        )

    def decide_approval(
        self,
        approval_id: str,
        *,
        approve: bool,
        actor: str,
        note: str,
        actor_kind: str = "developer",
    ) -> MemoryItem:
        raw = self.store.get_approval(approval_id)
        if not raw:
            raise MemoryServiceError(f"Unknown approval: {approval_id}")
        approval = Approval.model_validate(raw)
        if approval.subject_kind != "memory" or not approval.subject_id:
            raise MemoryServiceError("Approval is not for memory")
        if approval.status != "pending":
            raise MemoryServiceError(f"Approval is already {approval.status}")
        item = self.get(approval.subject_id)
        if item.status != "proposed" or item.approval_id != approval_id:
            raise MemoryServiceError("Memory proposal is not awaiting this approval")
        approval.status = "approved" if approve else "rejected"
        approval.updated_at = utc_now()
        approval.decided_by = actor
        approval.note = note
        item.status = "active" if approve else "rejected"
        item.reviewed_at = utc_now()
        if not self.store.transition_memory_approval(
            approval_id,
            item.memory_id,
            {"pending"},
            {"proposed"},
            approval.model_dump(mode="json"),
            item.model_dump(mode="json"),
        ):
            raise MemoryServiceError("Approval or memory proposal changed concurrently")
        self._event(item.memory_id, "activated" if approve else "rejected", actor_kind, actor, {"approval_id": approval_id, "note": note})
        return item

    def transition(self, memory_id: str, target: str, actor: str, reason: str = "") -> MemoryItem:
        item = self.get(memory_id)
        if target not in LEGAL_TRANSITIONS[item.status]:
            raise MemoryServiceError(f"Illegal memory transition: {item.status} -> {target}")
        previous = item.status
        item.status = target
        if target == "deleted":
            item.deleted_at = utc_now()
        if not self.store.transition_memory_item(memory_id, {previous}, item.model_dump(mode="json")):
            raise MemoryServiceError("Memory item changed concurrently")
        self._event(memory_id, target, "developer", actor, {"reason": reason})
        return item

    def supersede(self, old_id: str, replacement_id: str, actor: str) -> MemoryItem:
        old = self.get(old_id)
        replacement = self.get(replacement_id)
        if old.status != "active" or replacement.status != "active":
            raise MemoryServiceError("Supersession requires active old and replacement memory")
        old.status = "superseded"
        old.superseded_by = replacement_id
        if not self.store.transition_memory_item(old_id, {"active"}, old.model_dump(mode="json")):
            raise MemoryServiceError("Memory item changed concurrently")
        self._event(old_id, "superseded", "developer", actor, {"replacement_id": replacement_id})
        return old

    def purge(self, memory_id: str, actor: str, reason: str) -> None:
        if not reason.strip():
            raise MemoryServiceError("Purge requires a reason")
        item = self.get(memory_id)
        self._event(memory_id, "purged", "developer", actor, {"reason": reason, "title": item.title})
        if not self.store.delete_memory_item(memory_id):
            raise MemoryServiceError(f"Unknown memory item: {memory_id}")

    def create_project(self, label: str, created_by: str) -> MemoryProject:
        project = MemoryProject(project_id=f"project_{uuid4().hex}", label=label.strip(), created_by=created_by)
        self.store.set_memory_project(project.project_id, project.model_dump(mode="json"))
        return project

    def get_project(self, project_id: str) -> MemoryProject:
        value = self.store.get_memory_project(project_id)
        if not value:
            raise MemoryServiceError(f"Unknown memory project: {project_id}")
        return MemoryProject.model_validate(value)

    def list_projects(self) -> list[MemoryProject]:
        return [MemoryProject.model_validate(value) for value in self.store.list_memory_projects()]

    def link_repository(self, project_id: str, repo_id: str, actor: str) -> MemoryProject:
        project = self.get_project(project_id)
        project.repository_ids = sorted(set([*project.repository_ids, repo_id]))
        project.updated_at = utc_now()
        self.store.set_memory_project(project_id, project.model_dump(mode="json"))
        return project

    def unlink_repository(self, project_id: str, repo_id: str, actor: str) -> MemoryProject:
        project = self.get_project(project_id)
        project.repository_ids = [value for value in project.repository_ids if value != repo_id]
        project.updated_at = utc_now()
        self.store.set_memory_project(project_id, project.model_dump(mode="json"))
        return project

    def allowed_scopes(self, repo_id: str, requested: list[str]) -> list[str]:
        eligible = {f"repo:{repo_id}", "global:terminology"}
        eligible.update(
            f"project:{project.project_id}"
            for project in self.list_projects()
            if repo_id in project.repository_ids
        )
        return sorted(set(requested) & eligible)

    def recall(
        self,
        query: str,
        scopes: list[str],
        *,
        types: set[str] | None = None,
        max_items: int = 12,
        max_tokens: int = 2500,
        include_observations: bool = False,
    ) -> MemoryRecallResult:
        terms = {term for term in re.findall(r"[a-z0-9_@.-]+", query.casefold()) if len(term) > 1}
        ranked: list[tuple[int, MemoryItem]] = []
        for item in (MemoryItem.model_validate(value) for value in self.store.search_memory_items(query)):
            if item.scope not in scopes or (types and item.type not in types):
                continue
            if item.status != "active" and not (include_observations and item.status == "observed"):
                continue
            haystack = " ".join([item.title, item.body, *item.aliases, *item.tags]).casefold()
            score = sum(3 if term in item.title.casefold() else 1 for term in terms if term in haystack)
            if not terms or score:
                ranked.append((score, item))
        ranked.sort(key=lambda value: (-value[0], value[1].memory_id))
        selected: list[MemoryItem] = []
        tokens = 0
        for _, item in ranked:
            cost = estimate_tokens(f"{item.title}\n{item.body}")
            if len(selected) >= max_items or tokens + cost > max_tokens:
                continue
            selected.append(item)
            tokens += cost
        return MemoryRecallResult(items=selected, estimated_tokens=tokens, truncated=len(selected) < len(ranked))

    def resolve(self, reference: str, scopes: list[str]) -> MemoryRecallResult:
        normalized = reference.casefold().strip()
        candidates = []
        for item in (MemoryItem.model_validate(value) for value in self.store.list_memory_items()):
            names = {item.title.casefold().strip(), *(alias.casefold().strip() for alias in item.aliases)}
            if item.scope in scopes and item.status == "active" and normalized in names:
                candidates.append(item)
        return MemoryRecallResult(items=sorted(candidates, key=lambda item: item.memory_id), estimated_tokens=sum(estimate_tokens(item.title + item.body) for item in candidates))

    def context_pack(self, profile: str, scopes: list[str], query: str = "") -> MemoryContextPack:
        if profile not in BUDGETS:
            raise MemoryServiceError(f"Unknown context-pack profile: {profile}")
        max_items, max_tokens = BUDGETS[profile]
        result = self.recall(query, scopes, max_items=max_items, max_tokens=max_tokens)
        sections: dict[str, list[MemoryItem]] = {}
        mapping = {"terminology": "glossary", "decision": "decisions", "constraint": "constraints", "outcome": "outcomes", "known_trap": "known_traps", "open_question": "open_questions"}
        for item in result.items:
            sections.setdefault(mapping.get(item.type, "source_pointers"), []).append(item)
        return MemoryContextPack(profile=profile, scopes=scopes, sections=sections, estimated_tokens=result.estimated_tokens)

    def run_retention(self, actor: str = "system") -> list[str]:
        expired: list[str] = []
        now = _now()
        for item in self.list(statuses={"observed", "proposed", "active"}):
            age = now - (_parse_time(item.created_at) or now)
            days = 7 if item.status == "observed" and item.low_value else 30 if item.status == "observed" else 90 if item.status == "proposed" or item.type == "summary" else None
            if days is None or age < timedelta(days=days):
                continue
            if item.status == "proposed" and item.approval_id:
                raw = self.store.get_approval(item.approval_id)
                if raw and raw.get("status") == "pending":
                    approval = Approval.model_validate(raw)
                    approval.status = "rejected"
                    approval.updated_at = utc_now()
                    approval.decided_by = "system"
                    approval.note = "Expired by memory retention policy"
                    expired_item = item.model_copy(update={"status": "expired"})
                    if not self.store.transition_memory_approval(
                        approval.approval_id,
                        item.memory_id,
                        {"pending"},
                        {"proposed"},
                        approval.model_dump(mode="json"),
                        expired_item.model_dump(mode="json"),
                    ):
                        continue
                    self._event(item.memory_id, "expired", "system", actor, {"reason": "retention policy"})
                    expired.append(item.memory_id)
                    continue
            self.transition(item.memory_id, "expired", actor, "retention policy")
            expired.append(item.memory_id)
        return expired

    def export(self, *, include_deleted: bool = False) -> list[dict[str, Any]]:
        items = [MemoryItem.model_validate(value) for value in self.store.list_memory_items()]
        if not include_deleted:
            items = [item for item in items if item.status != "deleted"]
        return [item.model_dump(mode="json") for item in sorted(items, key=lambda item: item.memory_id)]

    def audit(self, memory_id: str | None = None) -> list[dict[str, Any]]:
        return self.store.get_memory_events(memory_id)

    def _event(self, memory_id: str, event_type: str, actor_kind: str, actor_id: str, payload: dict | None = None) -> None:
        safe_payload = payload or {}
        ensure_no_secret(safe_payload)
        event = MemoryEvent(event_id=f"memory_event_{uuid4().hex}", memory_id=memory_id, event_type=event_type, actor_kind=actor_kind, actor_id=actor_id, payload=safe_payload)
        self.store.append_memory_event(memory_id, event.model_dump(mode="json"))

    def _record_conflicts(self, item: MemoryItem) -> None:
        names = {item.title.casefold().strip(), *(alias.casefold().strip() for alias in item.aliases)}
        conflicts = []
        for value in self.store.list_memory_items():
            other = MemoryItem.model_validate(value)
            if other.memory_id == item.memory_id or other.scope != item.scope or other.status != "active":
                continue
            other_names = {other.title.casefold().strip(), *(alias.casefold().strip() for alias in other.aliases)}
            if names & other_names and item.body.strip() != other.body.strip():
                conflicts.append(other.memory_id)
        if conflicts:
            self._event(item.memory_id, "conflict_detected", "system", "memory-service", {"conflicts_with": sorted(conflicts)})

    def _orchestrator_activation_allowed(
        self, item: MemoryItem, policy: MemoryActivationPolicy
    ) -> tuple[bool, str, dict[str, Any]]:
        if policy.mode != "bounded_orchestrator":
            return False, "policy mode requires Developer approval", {}
        if item.status != "proposed":
            return False, f"memory status is {item.status}", {}
        scope_kind = item.scope.split(":", 1)[0]
        if scope_kind not in policy.auto_activate_scopes:
            return False, f"scope {item.scope} requires Developer approval", {}
        if policy.require_distinct_proposer_and_approver and item.author_id == f"orchestrator:{policy.orchestrator_id}":
            return False, "proposer and Orchestrator approver are the same", {}
        aliases_allowed = (
            policy.allow_non_conflicting_aliases
            and item.type == "terminology"
            and bool(item.aliases)
            and item.confidence in {"supported", "verified"}
        )
        if item.type not in policy.auto_activate_types and not aliases_allowed:
            return False, f"type {item.type} requires Developer approval", {}
        governed = self._source_is_governed(item.source.kind, item.source.ref)
        if policy.require_governed_source and not governed:
            return False, f"source {item.source.kind} is not governed", {}
        events = self.audit(item.memory_id)
        if policy.require_no_conflicts and any(event["event_type"] == "conflict_detected" for event in events):
            return False, "conflict detected", {}
        if self._orchestrator_decision_count(policy.orchestrator_id, item.source.ref) >= policy.max_auto_activations_per_task:
            return False, "per-task auto-activation limit reached", {}
        if self._orchestrator_decision_count(
            policy.orchestrator_id, None, today_only=True
        ) >= policy.max_auto_activations_per_day:
            return False, "daily auto-activation limit reached", {}
        return True, "bounded Orchestrator policy passed", {
            "scope": item.scope,
            "type": item.type,
            "source_kind": item.source.kind,
            "source_ref": item.source.ref,
            "aliases_allowed": aliases_allowed,
        }

    def _source_is_governed(self, kind: str, ref: str) -> bool:
        if kind in {"job", "plan", "approval", "delegation_task", "executor_session", "executor_launch", "delegation_result", "artifact", "commit"}:
            return True
        return kind == "repository_path" and not Path(ref).is_absolute()

    def _orchestrator_decision_count(
        self, orchestrator_id: str, source_ref: str | None, *, today_only: bool = False
    ) -> int:
        marker = f"orchestrator:{orchestrator_id}"
        count = 0
        today = _now().date()
        for event in self.audit():
            if event.get("event_type") != "activated" or event.get("actor_id") != marker:
                continue
            if today_only:
                created = _parse_time(event.get("created_at"))
                if not created or created.date() != today:
                    continue
            if source_ref is None:
                count += 1
                continue
            memory_id = event.get("memory_id")
            if memory_id:
                try:
                    if self.get(memory_id).source.ref == source_ref:
                        count += 1
                except MemoryServiceError:
                    pass
        return count

    def _validate_source(self, kind: str, ref: str) -> None:
        lookup = {
            "job": self.store.get_job,
            "plan": self.store.get_plan,
            "approval": self.store.get_approval,
            "delegation_task": self.store.get_delegation_task,
        }.get(kind)
        if lookup and not lookup(ref):
            raise MemoryServiceError(f"Unknown {kind} source reference: {ref}")
        delegated = {
            "executor_session": ("sessions", "session_id"),
            "executor_launch": ("launches", "launch_id"),
            "delegation_result": ("results", "result_id"),
        }.get(kind)
        if delegated:
            record_type, id_field = delegated
            found = any(
                record.get(id_field) == ref
                for task in self.store.list_delegation_tasks()
                for record in self.store.get_delegation_records(task["task_id"], record_type)
            )
            if not found:
                raise MemoryServiceError(f"Unknown {kind} source reference: {ref}")
        if kind == "artifact":
            job_id, separator, name = ref.partition(":")
            if not separator or not self.store.get_job(job_id) or not any(
                artifact.get("name") == name for artifact in self.store.get_artifacts(job_id)
            ):
                raise MemoryServiceError(f"Unknown artifact source reference: {ref}")
        if kind == "repository_path" and Path(ref).is_absolute():
            raise MemoryServiceError("Repository path source references must be relative")
        if kind == "commit" and not re.fullmatch(r"[0-9a-fA-F]{7,64}", ref):
            raise MemoryServiceError("Commit source references must be Git object IDs")
