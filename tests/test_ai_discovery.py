from __future__ import annotations

from canto.core.ai_discovery import HttpDiscoveryAdapter, ModelCatalogService
from canto.core.ai_endpoints import AIEndpointService
from canto.core.credentials import CredentialVault
from canto.core.state import MemoryStateStore
from canto.models.ai_workers import AIModelRecord


class Response:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class Session:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return Response(self.payload)


def service(tmp_path, provider, url, payload):
    store = MemoryStateStore()
    endpoints = AIEndpointService(store, CredentialVault(tmp_path / "vault"), tmp_path / "ai.yaml")
    kwargs = {} if provider == "ollama" else {"api_key": "secret"}
    endpoints.add("primary", provider, url, **kwargs)
    session = Session(payload)
    return store, endpoints, session, ModelCatalogService(
        store, endpoints, HttpDiscoveryAdapter(session=session)
    )


def test_openai_discovery_persists_exact_model_and_snapshot(tmp_path):
    store, endpoints, session, catalog = service(
        tmp_path,
        "openai",
        "https://api.openai.com",
        {"data": [{"id": "gpt-example-2026-01-01", "supports_tools": True}]},
    )

    snapshot = catalog.discover("primary")

    model = catalog.get("primary:gpt-example-2026-01-01")
    assert model.provider_model_id == "gpt-example-2026-01-01"
    assert model.probe_stale is True
    assert snapshot.models == [model.model_key]
    assert session.calls[0][0].endswith("/v1/models")
    assert session.calls[0][1]["headers"]["Authorization"] == "Bearer secret"
    assert endpoints.get("primary").validation_status == "valid"
    assert store.get_ai_record("catalog_snapshot", snapshot.snapshot_id)


def test_ollama_discovery_uses_digest_as_resolved_version(tmp_path):
    _, _, session, catalog = service(
        tmp_path,
        "ollama",
        "http://127.0.0.1:11434",
        {"models": [{"name": "qwen:14b", "digest": "sha256:abc"}]},
    )

    catalog.discover("primary")

    assert catalog.get("primary:qwen:14b").resolved_version == "sha256:abc"
    assert session.calls[0][0].endswith("/api/tags")


def test_ollama_discovery_accepts_list_capabilities(tmp_path):
    _, _, _, catalog = service(
        tmp_path,
        "ollama",
        "http://127.0.0.1:11434",
        {
            "models": [
                {
                    "name": "qwen:14b",
                    "digest": "sha256:abc",
                    "capabilities": ["completion", "tools"],
                }
            ]
        },
    )

    catalog.discover("primary")

    assert catalog.get("primary:qwen:14b").capabilities["tools"] is True


def test_catalog_change_marks_previously_probed_model_stale(tmp_path):
    store, _, session, catalog = service(
        tmp_path,
        "ollama",
        "http://localhost:11434",
        {"models": [{"name": "qwen:14b", "digest": "old"}]},
    )
    catalog.discover("primary")
    prior = catalog.get("primary:qwen:14b").model_copy(
        update={"classification": "implementation", "probe_stale": False, "probe_version": "1"}
    )
    store.set_ai_record("model", prior.model_key, prior.model_dump(mode="json"))
    session.payload = {"models": [{"name": "qwen:14b", "digest": "new"}]}

    catalog.discover("primary")

    updated = catalog.get("primary:qwen:14b")
    assert updated.resolved_version == "new"
    assert updated.probe_stale is True


def test_legacy_model_record_infers_probe_state_without_new_fields():
    model = AIModelRecord.model_validate(
        {
            "model_key": "local:coder",
            "endpoint_id": "local",
            "provider": "ollama",
            "provider_model_id": "coder",
            "resolved_version": "digest",
            "classification": "implementation",
            "probe_version": "1",
            "probe_stale": False,
            "catalog_checksum": "checksum",
        }
    )

    assert model.availability == "unknown"
    assert model.probe_state == "current"
