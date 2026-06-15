from __future__ import annotations

from canto.core.ai_discovery import DiscoveredModel
from canto.core.ai_endpoints import AIEndpointService
from canto.core.ai_probe import CodingWorkerProbeService, ProbeObservation
from canto.core.ai_reconciliation import (
    LocalModelReconciliationService,
    ModelCatalogMaintenanceService,
)
from canto.core.ai_selection import WorkerSelectionService
from canto.core.credentials import CredentialVault
from canto.core.state import MemoryStateStore
from canto.models.ai_workers import WorkerSelectionPolicy


class FakeOllama:
    def __init__(self):
        self.models = [
            DiscoveredModel(
                "qwen2.5-coder:14b",
                "sha256:one",
                metadata={"name": "qwen2.5-coder:14b", "digest": "sha256:one"},
            )
        ]
        self.calls = []

    def list_models(self, endpoint, credential):
        self.calls.append(endpoint.endpoint_id)
        return self.models, {
            "models": [
                {
                    "name": item.provider_model_id,
                    "digest": item.resolved_version,
                }
                for item in self.models
            ]
        }


class WorkingRunner:
    def run_probe(self, model_key, workspace):
        (workspace / "result.txt").write_text("canto-worker-probe\n")
        (workspace / "command.txt").write_text("probe-ok\n")
        return ProbeObservation(
            structured_tool_calls=["write_file", "run_command"], detail="complete"
        )


def test_offline_local_catalog_refresh_probe_select_and_remove(tmp_path):
    store = MemoryStateStore()
    endpoints = AIEndpointService(
        store, CredentialVault(tmp_path / "vault"), tmp_path / "ai.yaml"
    )
    endpoint = endpoints.add("local", "ollama", "http://localhost:11434")
    adapter = FakeOllama()
    reconciliation = LocalModelReconciliationService(store, endpoints, adapter)
    model_key = "local:qwen2.5-coder:14b"

    added = reconciliation.refresh("local")
    assert added.added == [model_key]
    assert reconciliation.catalog.get(model_key).probe_state == "absent"

    probe = CodingWorkerProbeService(
        store,
        reconciliation.catalog,
        WorkingRunner(),
        tmp_path / "probes",
    ).probe(model_key)
    assert probe.classification == "implementation"

    selected = WorkerSelectionService(store).select(
        "task-local",
        reconciliation.catalog.list("local"),
        {"local": endpoint},
        WorkerSelectionPolicy(),
    )
    assert selected.selected_model_key == model_key

    adapter.models = []
    removed = reconciliation.refresh("local")
    assert removed.missing == [model_key]
    status = ModelCatalogMaintenanceService(store).status("local")
    assert status["availability"] == {"missing": [model_key]}

    rejected = WorkerSelectionService(store).select(
        "task-after-removal",
        reconciliation.catalog.list("local"),
        {"local": endpoint},
        WorkerSelectionPolicy(),
    )
    assert rejected.selected_model_key is None
    assert "local model availability is missing" in (
        rejected.candidates[0].rejection_reasons
    )
    assert adapter.calls == ["local", "local"]
