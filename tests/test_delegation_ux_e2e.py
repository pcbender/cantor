from __future__ import annotations

import subprocess
from pathlib import Path

from canto.core.delegation import DelegationService
from canto.core.delegation_artifacts import DelegationArtifactService
from canto.core.delegation_commands import DelegationCommandService
from canto.core.delegation_comparison import DelegationComparisonService
from canto.core.delegation_conflicts import DelegationConflictService
from canto.core.delegation_dashboard import DelegationDashboardService
from canto.core.delegation_demo import run_delegation_demo
from canto.core.delegation_executor import CodexCliExecutor
from canto.core.delegation_promotion import DelegationPromotionService
from canto.core.delegation_queue import DelegationPromotionQueue
from canto.core.delegation_review import DelegationReviewService
from canto.core.delegation_review_summary import DelegationReviewSummaryService
from canto.core.delegation_workspace import DelegationWorkspaceService, inspect_repository
from canto.core.executor_profiles import ExecutorProfileManager
from canto.core.repository import initialize_repository
from canto.core.state import SqliteStateStore
from canto.models.delegation import DelegationScope, DelegationTask, DelegationVariant


def git(repository: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repository), *args], check=True, capture_output=True)


def test_mvp_v1_2_delegation_daily_workflow(tmp_path):
    repository = tmp_path / "repository"
    repository.mkdir()
    git(repository, "init")
    git(repository, "config", "user.email", "test@example.com")
    git(repository, "config", "user.name", "Test User")
    (repository / "src").mkdir()
    (repository / "src" / "app.py").write_text("value = 1\n")
    git(repository, "add", ".")
    git(repository, "commit", "-m", "initial")
    initialize_repository(repository)

    executable = tmp_path / "scripted-codex"
    executable.write_text("#!/bin/sh\ncat >/dev/null\nprintf 'value = 2\\n' > src/app.py\n")
    executable.chmod(0o755)
    state_file = tmp_path / "canto-home" / "state.sqlite"
    service = DelegationService(SqliteStateStore(state_file))
    workspaces = DelegationWorkspaceService(service, tmp_path / "canto-home" / "work" / "delegations")
    profiles = ExecutorProfileManager(service, tmp_path / "canto-home" / "config" / "executors.yaml")
    profile = profiles.resolve(
        "daily-codex",
        preset="codex-cloud",
        cli_override={"executable": str(executable), "model": "scripted-test"},
    )
    profiles.save(profile)
    source = service.create_task(
        DelegationTask(
            task_id="task_source",
            title="Update app",
            repository=inspect_repository(repository),
            scope=DelegationScope(
                allowed_paths=["src"],
                allowed_commands=["git diff --check"],
                required_commands=["git diff --check"],
            ),
            instructions="Change the fixture value.",
        )
    )
    variants = DelegationComparisonService(service).create_variants(
        source.task_id,
        [
            DelegationVariant(name="concise", prompt_supplement="Use the smallest edit."),
            DelegationVariant(name="explained", prompt_supplement="Explain the edit in output."),
        ],
    )
    for task in variants:
        service.transition(task.task_id, "assigned", updates={"executor_id": profile.executor_id})
        workspaces.prepare(task.task_id)
        launch = CodexCliExecutor(service, workspaces, timeout_seconds=10).launch(task.task_id)
        assert launch.exit_code == 0
        DelegationCommandService(service, workspaces).run(task.task_id, "git diff --check")
        DelegationArtifactService(service, workspaces).capture(task.task_id)

    dashboard = DelegationDashboardService(service, workspaces).list(active_only=True)
    assert {item.task_id for item in dashboard} >= {task.task_id for task in variants}
    comparison = DelegationComparisonService(service).compare(variants[0].comparison_id)
    assert [item.variant_name for item in comparison.variants] == ["concise", "explained"]
    first_summary = DelegationReviewSummaryService(service, workspaces).summarize(variants[0].task_id)
    assert first_summary.acceptance_ready is True
    assert len(first_summary.commands["passed"]) == 1

    review = DelegationReviewService(service, workspaces)
    queue = DelegationPromotionQueue(service, workspaces)
    for task in variants:
        review.accept(task.task_id, "maintainer")
        queue.enqueue(task.task_id, "maintainer")
    conflict = DelegationConflictService(service, workspaces).explain(variants[1].task_id)
    assert any(blocker.code == "queue_overlap" for blocker in conflict.blockers)

    promoted = DelegationPromotionService(service, workspaces).promote(
        variants[0].task_id, "maintainer", "Selected after explicit review"
    )
    assert promoted.status == "promoted"
    assert (repository / "src" / "app.py").read_text() == "value = 2\n"

    reopened = DelegationService(SqliteStateStore(state_file))
    assert reopened.get_task(variants[0].task_id).status == "promoted"
    assert reopened.get_executor_profile("daily-codex").model == "scripted-test"

    demo = run_delegation_demo()
    assert demo.status == "reviewing"
    assert demo.cleaned_up is True
