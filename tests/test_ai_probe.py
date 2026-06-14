from __future__ import annotations

from canto.core.ai_discovery import DiscoveredModel, ModelCatalogService
from canto.core.ai_endpoints import AIEndpointService
from canto.core.ai_probe import CodingWorkerProbeService, ProbeObservation
from canto.core.credentials import CredentialVault
from canto.core.state import MemoryStateStore


class CatalogAdapter:
    def list_models(self, endpoint, credential):
        raw = {"models": [{"name": "coder", "digest": "v1"}]}
        return [DiscoveredModel("coder", "v1", metadata=raw["models"][0])], raw


class WorkingRunner:
    def run_probe(self, model_key, workspace):
        (workspace / "result.txt").write_text("canto-worker-probe\n")
        (workspace / "command.txt").write_text("probe-ok\n")
        return ProbeObservation(
            structured_tool_calls=["write_file", "run_command"],
            detail="completed",
        )


class TextOnlyRunner:
    def run_probe(self, model_key, workspace):
        return ProbeObservation(responded=True, detail="printed a tool call as text")


def catalog(tmp_path):
    store = MemoryStateStore()
    endpoints = AIEndpointService(store, CredentialVault(tmp_path / "vault"), tmp_path / "ai.yaml")
    endpoints.add("ollama", "ollama", "http://localhost:11434")
    service = ModelCatalogService(store, endpoints, CatalogAdapter())
    service.discover("ollama")
    return store, service


def test_probe_classifies_structured_editing_worker_for_implementation(tmp_path):
    store, models = catalog(tmp_path)
    service = CodingWorkerProbeService(store, models, WorkingRunner(), tmp_path / "probes")

    result = service.probe("ollama:coder")

    assert result.classification == "implementation"
    assert all(assertion.passed for assertion in result.assertions)
    assert models.get("ollama:coder").probe_stale is False
    assert models.get("ollama:coder").classification == "implementation"


def test_probe_classifies_tool_text_without_actions_as_advisory(tmp_path):
    store, models = catalog(tmp_path)
    result = CodingWorkerProbeService(
        store, models, TextOnlyRunner(), tmp_path / "probes"
    ).probe("ollama:coder")

    assert result.classification == "advisory"
    assert result.assertions[0].passed is True
    assert result.assertions[1].passed is False
