from __future__ import annotations

import pytest
from typer.testing import CliRunner

from canto import cli as cli_module
from canto.core.ai_discovery import DiscoveredModel
from canto.core.ai_endpoints import AIEndpointService
from canto.core.ai_reconciliation import (
    LocalModelReconciliationService,
    ModelReconciliationError,
)
from canto.core.credentials import CredentialVault
from canto.core.state import MemoryStateStore


class Adapter:
    def __init__(self, models):
        self.models = models
        self.error = None

    def list_models(self, endpoint, credential):
        if self.error:
            raise self.error
        raw = {
            "models": [
                {"name": model.provider_model_id, "digest": model.resolved_version}
                for model in self.models
            ]
        }
        return self.models, raw


def model(name, digest):
    metadata = {"name": name, "digest": digest, "size": 10}
    return DiscoveredModel(name, digest, display_name=name, metadata=metadata)


def service(tmp_path, models):
    store = MemoryStateStore()
    endpoints = AIEndpointService(
        store, CredentialVault(tmp_path / "vault"), tmp_path / "ai.yaml"
    )
    endpoints.add("local", "ollama", "http://localhost:11434")
    adapter = Adapter(models)
    return store, adapter, LocalModelReconciliationService(store, endpoints, adapter)


def test_refresh_adds_changes_and_marks_missing_without_deleting_history(tmp_path):
    store, adapter, reconciler = service(tmp_path, [model("qwen:14b", "old"), model("gone:7b", "v1")])
    first = reconciler.refresh("local")
    qwen = reconciler.catalog.get("local:qwen:14b").model_copy(
        update={
            "classification": "implementation",
            "probe_version": "1",
            "probe_stale": False,
            "probe_state": "current",
        }
    )
    store.set_ai_record("model", qwen.model_key, qwen.model_dump(mode="json"))
    adapter.models = [model("qwen:14b", "new"), model("added:3b", "v1")]

    second = reconciler.refresh("local")

    assert first.added == ["local:gone:7b", "local:qwen:14b"]
    assert second.added == ["local:added:3b"]
    assert second.changed == ["local:qwen:14b"]
    assert second.missing == ["local:gone:7b"]
    assert reconciler.catalog.get("local:qwen:14b").probe_state == "stale"
    missing = reconciler.catalog.get("local:gone:7b")
    assert missing.availability == "missing"
    assert missing.resolved_version == "v1"


def test_unchanged_model_keeps_current_probe(tmp_path):
    store, adapter, reconciler = service(tmp_path, [model("coder:7b", "same")])
    reconciler.refresh("local")
    current = reconciler.catalog.get("local:coder:7b").model_copy(
        update={
            "classification": "implementation",
            "probe_version": "1",
            "probe_stale": False,
            "probe_state": "current",
        }
    )
    store.set_ai_record("model", current.model_key, current.model_dump(mode="json"))

    result = reconciler.refresh("local")

    assert result.unchanged == ["local:coder:7b"]
    assert reconciler.catalog.get("local:coder:7b").probe_state == "current"


def test_failed_refresh_records_uncertainty_without_marking_models_missing(tmp_path):
    _, adapter, reconciler = service(tmp_path, [model("coder:7b", "v1")])
    reconciler.refresh("local")
    adapter.error = RuntimeError("ollama unavailable")

    with pytest.raises(ModelReconciliationError) as caught:
        reconciler.refresh("local")

    assert caught.value.record.authoritative_success is False
    assert reconciler.catalog.get("local:coder:7b").availability == "endpoint_unreachable"
    assert reconciler.latest_reconciliation("local").error == "ollama unavailable"


def test_refresh_rejects_nonlocal_endpoint(tmp_path):
    store = MemoryStateStore()
    endpoints = AIEndpointService(
        store, CredentialVault(tmp_path / "vault"), tmp_path / "ai.yaml"
    )
    endpoints.add("cloud", "openai", "https://api.openai.com", api_key="secret")
    reconciler = LocalModelReconciliationService(store, endpoints, Adapter([]))

    with pytest.raises(ModelReconciliationError, match="loopback Ollama"):
        reconciler.refresh("cloud")


def test_refresh_cli_prints_deterministic_summary(monkeypatch, tmp_path):
    _, _, reconciler = service(
        tmp_path, [model("zeta:7b", "v1"), model("alpha:3b", "v1")]
    )
    monkeypatch.setattr(cli_module, "_ai_reconciliation_service", lambda: reconciler)

    result = CliRunner().invoke(cli_module.app, ["ai", "model", "refresh", "local"])

    assert result.exit_code == 0
    assert result.stdout.splitlines() == [
        "Endpoint: local",
        "Added: 2",
        "Changed: 0",
        "Missing: 0",
        "Unchanged: 0",
        "added: local:alpha:3b",
        "added: local:zeta:7b",
    ]


def test_refresh_cli_supports_json_and_clean_errors(monkeypatch, tmp_path):
    _, adapter, reconciler = service(tmp_path, [model("coder:7b", "v1")])
    monkeypatch.setattr(cli_module, "_ai_reconciliation_service", lambda: reconciler)
    runner = CliRunner()

    success = runner.invoke(
        cli_module.app, ["ai", "model", "refresh", "local", "--json"]
    )
    assert success.exit_code == 0
    assert '"authoritative_success": true' in success.stdout

    adapter.error = RuntimeError("ollama unavailable")
    failure = runner.invoke(cli_module.app, ["ai", "model", "refresh", "local"])
    assert failure.exit_code == 2
    assert "Local model refresh failed for local: ollama unavailable" in failure.stderr
    assert "Traceback" not in failure.stderr
