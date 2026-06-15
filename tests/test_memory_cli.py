from __future__ import annotations

import json

from typer.testing import CliRunner

import canto.cli as cli_module


def test_memory_cli_propose_approve_list_and_audit(monkeypatch, tmp_path):
    monkeypatch.setenv("CANTO_HOME", str(tmp_path / ".canto"))
    runner = CliRunner()

    proposed = runner.invoke(
        cli_module.app,
        [
            "memory", "propose",
            "--scope", "repo:repo_test",
            "--type", "terminology",
            "--title", "Developer",
            "--body", "The authorized person governing work.",
            "--alias", "Cantor",
        ],
    )
    assert proposed.exit_code == 0, proposed.output
    item = json.loads(proposed.output)

    requested = runner.invoke(
        cli_module.app, ["memory", "request-approval", item["memory_id"]]
    )
    assert requested.exit_code == 0, requested.output
    approval = json.loads(requested.output)
    assert approval["subject_kind"] == "memory"

    approved = runner.invoke(cli_module.app, ["approve", approval["approval_id"]])
    assert approved.exit_code == 0, approved.output
    assert json.loads(approved.output)["status"] == "active"

    listed = runner.invoke(cli_module.app, ["memory", "list"])
    assert listed.exit_code == 0, listed.output
    assert [value["memory_id"] for value in json.loads(listed.output)] == [item["memory_id"]]

    audit = runner.invoke(
        cli_module.app, ["memory", "audit", "--memory-id", item["memory_id"]]
    )
    assert audit.exit_code == 0, audit.output
    assert [value["event_type"] for value in json.loads(audit.output)] == [
        "proposed", "orchestrator_activation_skipped", "approval_requested", "activated"
    ]


def test_memory_cli_project_identity(monkeypatch, tmp_path):
    monkeypatch.setenv("CANTO_HOME", str(tmp_path / ".canto"))
    runner = CliRunner()
    created = runner.invoke(cli_module.app, ["memory", "project", "create", "Migration"])
    assert created.exit_code == 0, created.output
    project = json.loads(created.output)
    assert project["project_id"].startswith("project_")
    listed = runner.invoke(cli_module.app, ["memory", "project", "list"])
    assert listed.exit_code == 0
    assert json.loads(listed.output)[0]["project_id"] == project["project_id"]


def test_memory_cli_defaults_to_bounded_orchestrator_approval(monkeypatch, tmp_path):
    monkeypatch.setenv("CANTO_HOME", str(tmp_path / ".canto"))
    runner = CliRunner()

    # Create a governed source directly through the state file used by the CLI.
    from canto.core.state import SqliteStateStore
    from canto.core.local_registry import Registry as CapabilityRegistry

    state = SqliteStateStore(CapabilityRegistry.local().store.paths.state_file)
    state.set_job("job_cli", {"job_id": "job_cli", "status": "completed"})

    proposed = runner.invoke(
        cli_module.app,
        [
            "memory", "propose",
            "--scope", "repo:repo_test",
            "--type", "outcome",
            "--title", "CLI outcome",
            "--body", "CLI outcome was observed.",
            "--source-kind", "job",
            "--source-ref", "job_cli",
            "--confidence", "supported",
        ],
    )
    assert proposed.exit_code == 0, proposed.output
    item = json.loads(proposed.output)
    assert item["status"] == "active"
    approval = state.get_approval(item["approval_id"])
    assert approval["decided_by"] == "orchestrator:local"


def test_read_only_memory_status_reports_missing_state_without_traceback(monkeypatch, tmp_path):
    monkeypatch.setenv("CANTO_HOME", str(tmp_path / ".canto"))
    result = CliRunner().invoke(cli_module.app, ["memory", "status"])
    assert result.exit_code != 0
    assert "state database does not exist" in result.output
    assert "Traceback" not in result.output
