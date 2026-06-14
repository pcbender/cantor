from __future__ import annotations

import json

from typer.testing import CliRunner

import canto.cli as cli_module
from canto.core.delegation import DelegationService
from canto.core.delegation_dashboard import DelegationDashboardService
from canto.core.delegation_workspace import DelegationWorkspaceService
from canto.core.state import MemoryStateStore
from canto.models.delegation import (
    DelegationTask,
    ExecutorProfile,
    RepositoryIdentity,
)


def dashboard_runtime(tmp_path):
    service = DelegationService(MemoryStateStore())
    workspaces = DelegationWorkspaceService(service, tmp_path / "delegations")
    service.set_executor_profile(
        ExecutorProfile(executor_id="manual", name="Manual", harness="manual")
    )
    for task_id, title in (("task_work", "Working"), ("task_review", "Review")):
        service.create_task(
            DelegationTask(
                task_id=task_id,
                title=title,
                repository=RepositoryIdentity(canonical_path="/repo"),
            )
        )
        service.transition(task_id, "assigned", updates={"executor_id": "manual"})
    service.store.set_delegation_task(
        "task_work",
        {
            **service.get_task("task_work").model_dump(mode="json"),
            "status": "executor_working",
        },
    )
    service.store.set_delegation_task(
        "task_review",
        {
            **service.get_task("task_review").model_dump(mode="json"),
            "status": "reviewing",
            "latest_result_revision": 1,
        },
    )
    return service, workspaces


def test_dashboard_prioritizes_review_attention_and_projects_next_action(tmp_path):
    service, workspaces = dashboard_runtime(tmp_path)

    rows = DelegationDashboardService(service, workspaces).list()

    assert [row.task_id for row in rows] == ["task_review", "task_work"]
    assert rows[0].attention == "review"
    assert rows[0].next_action == "accept"
    assert rows[1].next_action == "message"


def test_dashboard_detail_groups_command_evidence(tmp_path):
    service, workspaces = dashboard_runtime(tmp_path)
    service.store.append_delegation_record(
        "task_review",
        "commands",
        "command_1",
        {
            "record_id": "command_1",
            "task_id": "task_review",
            "command": "pytest",
            "source": "canto_observed",
            "status": "passed",
        },
    )

    detail = DelegationDashboardService(service, workspaces).detail("task_review")

    assert detail.commands["passed"][0]["command"] == "pytest"
    assert detail.next_actions == ["accept", "revise", "reject"]


def test_dashboard_cli_has_human_and_json_views(tmp_path, monkeypatch):
    service, workspaces = dashboard_runtime(tmp_path)
    monkeypatch.setattr(
        cli_module, "_delegation_runtime", lambda: (service, workspaces)
    )
    runner = CliRunner()

    human = runner.invoke(cli_module.app, ["delegate", "dashboard"])
    machine = runner.invoke(cli_module.app, ["delegate", "dashboard", "--json"])
    detail = runner.invoke(
        cli_module.app, ["delegate", "dashboard", "task_review"]
    )

    assert human.exit_code == 0
    assert "ATTENTION\tSTATUS\tTASK" in human.output
    assert json.loads(machine.output)[0]["task_id"] == "task_review"
    assert "Next: accept, revise, reject" in detail.output


def test_executor_done_dashboard_allows_revision_when_capture_has_no_result(tmp_path):
    service, workspaces = dashboard_runtime(tmp_path)
    current = service.get_task("task_work").model_dump(mode="json")
    service.store.set_delegation_task(
        "task_work", {**current, "status": "executor_done"}
    )

    detail = DelegationDashboardService(service, workspaces).detail("task_work")

    assert detail.next_actions == ["capture", "revise"]


def test_executor_done_advisory_output_blocks_capture_and_points_to_evidence(tmp_path):
    service, workspaces = dashboard_runtime(tmp_path)
    current = service.get_task("task_work").model_dump(mode="json")
    service.store.set_delegation_task(
        "task_work", {**current, "status": "executor_done"}
    )
    service.store.append_delegation_record(
        "task_work",
        "launches",
        "launch_1",
        {
            "launch_id": "launch_1",
            "task_id": "task_work",
            "session_id": "session_1",
            "executor_id": "manual",
            "argv": ["worker"],
            "cwd": "/workspace",
            "prompt_path": "/artifacts/prompt.md",
            "stdout_path": "/artifacts/stdout.log",
            "stderr_path": "/artifacts/stderr.log",
            "workspace_changed": False,
            "outcome": "advisory",
            "outcome_detail": "Worker described tool calls but changed no files",
        },
    )

    detail = DelegationDashboardService(service, workspaces).detail("task_work")

    assert detail.task.attention == "blocked"
    assert detail.task.worker_outcome == "advisory"
    assert detail.next_actions == ["revise"]
    assert "changed no files" in detail.outcome_detail


def test_dashboard_cli_prints_advisory_outcome_and_output_path(tmp_path, monkeypatch):
    service, workspaces = dashboard_runtime(tmp_path)
    current = service.get_task("task_work").model_dump(mode="json")
    service.store.set_delegation_task(
        "task_work", {**current, "status": "executor_done"}
    )
    service.store.append_delegation_record(
        "task_work",
        "launches",
        "launch_1",
        {
            "launch_id": "launch_1",
            "task_id": "task_work",
            "session_id": "session_1",
            "executor_id": "manual",
            "argv": ["worker"],
            "cwd": "/workspace",
            "prompt_path": "/artifacts/prompt.md",
            "stdout_path": "/artifacts/stdout.log",
            "stderr_path": "/artifacts/stderr.log",
            "outcome": "advisory",
            "outcome_detail": "Advisory output only",
        },
    )
    monkeypatch.setattr(
        cli_module, "_delegation_runtime", lambda: (service, workspaces)
    )

    result = CliRunner().invoke(
        cli_module.app, ["delegate", "dashboard", "task_work"]
    )

    assert result.exit_code == 0
    assert "Worker outcome: advisory" in result.output
    assert "Worker output: /artifacts/stdout.log" in result.output
    assert "Next: revise" in result.output
