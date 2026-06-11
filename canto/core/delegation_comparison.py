from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from canto.core.delegation import DelegationError, DelegationService
from canto.models.delegation import (
    DelegationComparison,
    DelegationComparisonItem,
    DelegationTask,
    DelegationVariant,
)


class ComparisonError(DelegationError):
    pass


def _runtime(started_at: str, ended_at: str | None) -> float | None:
    if not ended_at:
        return None
    return max(
        0.0,
        (datetime.fromisoformat(ended_at) - datetime.fromisoformat(started_at)).total_seconds(),
    )


def _patch_stats(patch: str) -> tuple[int, int]:
    additions = sum(1 for line in patch.splitlines() if line.startswith("+") and not line.startswith("+++"))
    deletions = sum(1 for line in patch.splitlines() if line.startswith("-") and not line.startswith("---"))
    return additions, deletions


class DelegationComparisonService:
    def __init__(self, delegation: DelegationService):
        self.delegation = delegation

    def create_variants(
        self,
        source_task_id: str,
        variants: list[DelegationVariant],
    ) -> list[DelegationTask]:
        source = self.delegation.get_task(source_task_id)
        if source.status != "draft":
            raise ComparisonError("Comparison variants must be created from a draft task")
        if len(variants) < 2:
            raise ComparisonError("A comparison requires at least two variants")
        names = [variant.name.strip() for variant in variants]
        if any(not name for name in names) or len(names) != len(set(names)):
            raise ComparisonError("Comparison variant names must be non-empty and unique")
        comparison_id = source.comparison_id or f"comparison_{uuid4().hex}"
        created: list[DelegationTask] = []
        for variant in variants:
            task = source.model_copy(
                update={
                    "task_id": f"task_{uuid4().hex}",
                    "comparison_id": comparison_id,
                    "variant_name": variant.name,
                    "prompt_supplement": variant.prompt_supplement,
                }
            )
            created.append(self.delegation.create_task(task))
        return created

    def compare(self, comparison_id: str) -> DelegationComparison:
        tasks = sorted(
            (task for task in self.delegation.list_tasks() if task.comparison_id == comparison_id),
            key=lambda task: (task.variant_name or "", task.task_id),
        )
        if len(tasks) < 2:
            raise ComparisonError(f"Comparison requires at least two sibling tasks: {comparison_id}")
        repository = tasks[0].repository
        if any(task.repository != repository for task in tasks[1:]):
            raise ComparisonError("Comparison tasks have incompatible repository identities")
        base_commits: set[str] = set()
        items: list[DelegationComparisonItem] = []
        for task in tasks:
            workspaces = self.delegation.get_records(task.task_id, "workspaces")
            base_commit = workspaces[-1]["base_commit"] if workspaces else (task.repository.initial_head or "")
            base_commits.add(base_commit)
            results = self.delegation.get_records(task.task_id, "results")
            result = results[-1] if results else None
            changed_files: list[str] = []
            additions = deletions = 0
            if result:
                artifacts = {item["name"]: item for item in result.get("artifacts", [])}
                workspace_path = Path(workspaces[-1]["path"])
                artifact_root = workspace_path.parent / "artifacts"
                changed = artifacts.get("changed_files.json")
                patch = artifacts.get("proposal.diff")
                if changed:
                    values = json.loads((artifact_root / changed["relative_path"]).read_text(encoding="utf-8"))
                    changed_files = [value["path"] for value in values]
                if patch:
                    additions, deletions = _patch_stats(
                        (artifact_root / patch["relative_path"]).read_text(encoding="utf-8")
                    )
            launches = self.delegation.get_records(task.task_id, "launches")
            launch = launches[-1] if launches else None
            items.append(
                DelegationComparisonItem(
                    task_id=task.task_id,
                    variant_name=task.variant_name or task.task_id,
                    base_commit=base_commit,
                    status=task.status,
                    result_revision=result.get("revision") if result else None,
                    changed_files=changed_files,
                    patch_additions=additions,
                    patch_deletions=deletions,
                    commands=self.delegation.get_records(task.task_id, "commands"),
                    exit_code=launch.get("exit_code") if launch else None,
                    timed_out=bool(launch and launch.get("timed_out")),
                    runtime_seconds=_runtime(launch["started_at"], launch.get("ended_at")) if launch else None,
                    token_usage=launch.get("token_usage") if launch else None,
                    session_id=result.get("producing_session_id") if result else (launch.get("session_id") if launch else None),
                    launch_id=result.get("producing_launch_id") if result else (launch.get("launch_id") if launch else None),
                )
            )
        if len(base_commits) != 1:
            raise ComparisonError("Comparison tasks have incompatible Git bases")
        return DelegationComparison(
            comparison_id=comparison_id,
            repository=repository,
            base_commit=next(iter(base_commits)),
            variants=items,
        )
