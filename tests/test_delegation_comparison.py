from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from canto.core.delegation import DelegationService
from canto.core.delegation_comparison import ComparisonError, DelegationComparisonService
from canto.core.delegation_workspace import DelegationWorkspaceService, inspect_repository
from canto.core.state import MemoryStateStore
from canto.models.delegation import DelegationScope, DelegationTask, DelegationVariant


def git(repository: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repository), *args], check=True, capture_output=True)


def source_task(tmp_path):
    repository = tmp_path / "repository"
    repository.mkdir()
    git(repository, "init")
    git(repository, "config", "user.email", "test@example.com")
    git(repository, "config", "user.name", "Test User")
    (repository / "src").mkdir()
    (repository / "src" / "app.py").write_text("value = 1\n")
    git(repository, "add", ".")
    git(repository, "commit", "-m", "initial")
    service = DelegationService(MemoryStateStore())
    source = service.create_task(
        DelegationTask(
            task_id="task_source",
            title="Update app",
            repository=inspect_repository(repository),
            scope=DelegationScope(allowed_paths=["src"]),
            instructions="Change the value.",
        )
    )
    return service, source


def test_comparison_variants_are_isolated_sibling_tasks(tmp_path):
    service, source = source_task(tmp_path)
    variants = DelegationComparisonService(service).create_variants(
        source.task_id,
        [
            DelegationVariant(name="small", prompt_supplement="Make the smallest change."),
            DelegationVariant(name="documented", prompt_supplement="Add a comment."),
        ],
    )
    assert variants[0].comparison_id == variants[1].comparison_id
    assert variants[0].task_id != variants[1].task_id
    assert variants[0].repository == variants[1].repository

    workspaces = DelegationWorkspaceService(service, tmp_path / "delegations")
    paths = []
    for task in variants:
        service.transition(task.task_id, "assigned", updates={"executor_id": "manual"})
        paths.append(workspaces.prepare(task.task_id).path)
    assert paths[0] != paths[1]
    assert workspaces.get(variants[0].task_id).base_commit == workspaces.get(variants[1].task_id).base_commit


def test_comparison_requires_two_unique_variants(tmp_path):
    service, source = source_task(tmp_path)
    with pytest.raises(ComparisonError, match="at least two"):
        DelegationComparisonService(service).create_variants(
            source.task_id, [DelegationVariant(name="only")]
        )
    with pytest.raises(ComparisonError, match="unique"):
        DelegationComparisonService(service).create_variants(
            source.task_id,
            [DelegationVariant(name="same"), DelegationVariant(name="same")],
        )


def test_comparison_projection_does_not_select_a_winner(tmp_path):
    service, source = source_task(tmp_path)
    variants = DelegationComparisonService(service).create_variants(
        source.task_id,
        [DelegationVariant(name="a"), DelegationVariant(name="b")],
    )
    comparison = DelegationComparisonService(service).compare(variants[0].comparison_id)
    assert comparison.base_commit == source.repository.initial_head
    assert [item.variant_name for item in comparison.variants] == ["a", "b"]
    assert "winner" not in comparison.model_dump()
