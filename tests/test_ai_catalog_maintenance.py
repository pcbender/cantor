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
