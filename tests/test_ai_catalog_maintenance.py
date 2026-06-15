from __future__ import annotations

import pytest
from typer.testing import CliRunner

from canto import cli as cli_module
from canto.core.ai_reconciliation import (
    ModelCatalogMaintenanceError,
    ModelCatalogMaintenanceService,
)
from canto.core.state import MemoryStateStore, SqliteStateStore
from canto.models.ai_workers import AIModelRecord
from canto.models.delegation import (
    DelegationResult,
    DelegationTask,
    ExecutorLaunch,
    ExecutorSession,
    RepositoryIdentity,
)


def model(key: str, availability: str = "missing") -> AIModelRecord:
    return AIModelRecord(
        model_key=key,
        endpoint_id="local",
        provider="ollama",
        provider_model_id=key.removeprefix("local:"),
        resolved_version="digest",
        catalog_checksum="checksum",
        availability=availability,
    )


@pytest.mark.parametrize("store_kind", ["memory", "sqlite"])
def test_ai_record_delete_round_trip(store_kind, tmp_path):
    store = (
        MemoryStateStore()
        if store_kind == "memory"
        else SqliteStateStore(tmp_path / "state.sqlite")
    )
    store.set_ai_record("model", "local:gone", model("local:gone").model_dump(mode="json"))

    assert store.delete_ai_record("model", "local:gone") is True
    assert store.delete_ai_record("model", "local:gone") is False


def test_status_groups_lifecycle_fields_and_show_includes_evidence():
    store = MemoryStateStore()
    missing = model("local:gone")
    store.set_ai_record("model", missing.model_key, missing.model_dump(mode="json"))
    store.set_ai_record(
        "probe",
        "probe-1",
        {
            "probe_id": "probe-1",
            "model_key": missing.model_key,
            "endpoint_id": "local",
            "provider_model_id": "gone",
            "resolved_version": "digest",
            "probe_version": "1",
            "classification": "implementation",
        },
    )
    service = ModelCatalogMaintenanceService(store)

    status = service.status("local")
    detail = service.show(missing.model_key)

    assert status["availability"] == {"missing": ["local:gone"]}
    assert detail["latest_probe"]["probe_id"] == "probe-1"
    assert detail["references"] == ["probe"]


def test_forget_requires_unavailable_unreferenced_model():
    store = MemoryStateStore()
    service = ModelCatalogMaintenanceService(store)
    available = model("local:present", "available")
    store.set_ai_record("model", available.model_key, available.model_dump(mode="json"))

    with pytest.raises(ModelCatalogMaintenanceError, match="available model"):
        service.forget(available.model_key)

    missing = model("local:gone")
    store.set_ai_record("model", missing.model_key, missing.model_dump(mode="json"))
    store.set_ai_record(
        "usage", "usage-1", {"usage_id": "usage-1", "model_key": missing.model_key}
    )
    with pytest.raises(ModelCatalogMaintenanceError, match="usage"):
        service.forget(missing.model_key)

    store.delete_ai_record("usage", "usage-1")
    service.forget(missing.model_key)
    assert store.get_ai_record("model", missing.model_key) is None


def test_status_show_and_forget_cli(monkeypatch):
    store = MemoryStateStore()
    missing = model("local:gone")
    store.set_ai_record("model", missing.model_key, missing.model_dump(mode="json"))
    service = ModelCatalogMaintenanceService(store)
    monkeypatch.setattr(
        cli_module, "_ai_catalog_maintenance_service", lambda: service
    )
    runner = CliRunner()

    status = runner.invoke(
        cli_module.app, ["ai", "model", "status", "--endpoint", "local"]
    )
    shown = runner.invoke(
        cli_module.app, ["ai", "model", "show", missing.model_key]
    )
    forgotten = runner.invoke(
        cli_module.app, ["ai", "model", "forget", missing.model_key]
    )

    assert status.exit_code == 0
    assert "missing: 1" in status.stdout
    assert shown.exit_code == 0
    assert '"availability": "missing"' in shown.stdout
    assert forgotten.exit_code == 0
    assert forgotten.stdout == "Forgot local:gone\n"


def test_forget_detects_retained_session_and_result_after_task_selection_changes():
    store = MemoryStateStore()
    model_record = model("local:old-worker")
    store.set_ai_record(
        "model", model_record.model_key, model_record.model_dump(mode="json")
    )
    task = DelegationTask(
        task_id="task-1",
        title="Fallback fixture",
        repository=RepositoryIdentity(canonical_path="/tmp/repo", initial_head="abc"),
        selected_model_key="cloud:fallback",
    )
    store.set_delegation_task(task.task_id, task.model_dump(mode="json"))
    session = ExecutorSession(
        session_id="session-old",
        task_id=task.task_id,
        executor_id="ai:local:old-worker",
        status="failed",
        enforcement="canto_observed",
    )
    launch = ExecutorLaunch(
        launch_id="launch-old",
        task_id=task.task_id,
        session_id=session.session_id,
        executor_id=session.executor_id,
        argv=["canto-api-worker", "local:old-worker"],
        cwd="/tmp/workspace",
        prompt_path="prompt.md",
        stdout_path="stdout.log",
        stderr_path="stderr.log",
    )
    result = DelegationResult(
        result_id="result-old",
        task_id=task.task_id,
        revision=1,
        base_commit="abc",
        workspace_patch_sha256="checksum",
        producing_session_id=session.session_id,
        producing_launch_id=launch.launch_id,
    )
    store.append_delegation_record(
        task.task_id, "sessions", session.session_id, session.model_dump(mode="json")
    )
    store.append_delegation_record(
        task.task_id, "launches", launch.launch_id, launch.model_dump(mode="json")
    )
    store.append_delegation_record(
        task.task_id, "results", result.result_id, result.model_dump(mode="json")
    )
    service = ModelCatalogMaintenanceService(store)

    assert service.references(model_record.model_key) == [
        "delegation_session",
        "result",
    ]
    with pytest.raises(ModelCatalogMaintenanceError, match="delegation_session, result"):
        service.forget(model_record.model_key)
