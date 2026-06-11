from __future__ import annotations

from pathlib import Path

import pytest

from canto.core.delegation_commands import CommandError, DelegationCommandService
from canto.core.delegation_promotion import DelegationPromotionService, PromotionError
from canto.core.delegation_review import DelegationReviewService
from tests.test_delegation_artifacts import executor_done
from tests.test_delegation_review import capture


def working_with_command(tmp_path, command: str):
    service, workspaces, workspace = executor_done(tmp_path)
    task = service.get_task("task_1")
    value = task.model_dump(mode="json")
    value["scope"]["allowed_commands"] = [command]
    value["scope"]["required_commands"] = [command]
    service.store.set_delegation_task("task_1", value)
    service.store.set_delegation_task(
        "task_1", {**value, "status": "executor_working"}
    )
    return service, workspaces, workspace


def test_observed_command_records_output_and_satisfies_requirement(tmp_path):
    command = "./check.sh"
    service, workspaces, workspace = working_with_command(tmp_path, command)
    script = workspace / "check.sh"
    script.write_text("#!/bin/sh\nprintf 'ok\\n'\n")
    script.chmod(0o755)
    commands = DelegationCommandService(service, workspaces)

    record = commands.run("task_1", command)

    assert record.status == "passed"
    assert record.source == "canto_observed"
    assert Path(record.stdout_path).read_text() == "ok\n"
    assert commands.unmet_required("task_1") == []


def test_manual_report_does_not_satisfy_required_command(tmp_path):
    command = "./check.sh"
    service, workspaces, _ = working_with_command(tmp_path, command)
    commands = DelegationCommandService(service, workspaces)

    commands.report("task_1", command, passed=True)

    assert commands.unmet_required("task_1") == [command]


def test_command_rejects_shell_operators_and_workspace_escape(tmp_path):
    service, workspaces, _ = working_with_command(tmp_path, "echo ok")
    commands = DelegationCommandService(service, workspaces)

    with pytest.raises(CommandError, match="control operators"):
        commands.run("task_1", "echo ok && touch bad")
    with pytest.raises(CommandError, match="escapes workspace"):
        commands.run("task_1", "echo ok", "../")


def test_promotion_requires_observed_command_or_waiver(tmp_path):
    service, workspaces, _, _ = capture(tmp_path)
    task = service.get_task("task_1")
    value = task.model_dump(mode="json")
    value["scope"]["required_commands"] = ["pytest"]
    service.store.set_delegation_task("task_1", value)
    DelegationReviewService(service, workspaces).accept("task_1", "reviewer")
    promotions = DelegationPromotionService(service, workspaces)

    with pytest.raises(PromotionError, match="Required commands"):
        promotions.promote("task_1", "orchestrator")

    DelegationCommandService(service, workspaces).waive(
        "task_1", "pytest", "Fixture has no executable test suite"
    )
    assert promotions.promote("task_1", "orchestrator").status == "promoted"
