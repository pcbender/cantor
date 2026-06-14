from __future__ import annotations

import json

import pytest

from canto.core.ai_endpoints import AIEndpointError, AIEndpointService
from canto.core.credentials import CredentialVault
from canto.core.state import MemoryStateStore, SqliteStateStore


@pytest.mark.parametrize("store_kind", ["memory", "sqlite"])
def test_endpoint_records_persist_without_plaintext_key(tmp_path, store_kind):
    store = (
        MemoryStateStore()
        if store_kind == "memory"
        else SqliteStateStore(tmp_path / "state.sqlite")
    )
    vault = CredentialVault(tmp_path / "vault")
    service = AIEndpointService(store, vault, tmp_path / "config" / "ai-endpoints.yaml")

    endpoint = service.add(
        "openai-primary",
        "openai",
        "https://api.openai.com",
        api_key="secret-value",
    )

    assert endpoint.credential_ref == "vault:ai/openai-primary"
    assert service.get("openai-primary").provider == "openai"
    assert "secret-value" not in json.dumps(store.list_ai_records("endpoint"))
    assert "secret-value" not in service.config_file.read_text()
    assert service.config_file.stat().st_mode & 0o777 == 0o600


def test_cloud_endpoint_requires_https_and_vault_reference(tmp_path):
    service = AIEndpointService(
        MemoryStateStore(), CredentialVault(tmp_path / "vault"), tmp_path / "ai.yaml"
    )

    with pytest.raises(AIEndpointError, match="HTTPS"):
        service.add("cloud", "openai_compatible", "http://models.example.com", api_key="x")
    with pytest.raises(AIEndpointError, match="vault"):
        service.add("cloud", "anthropic", "https://api.anthropic.com")


def test_local_ollama_allows_loopback_without_key(tmp_path):
    service = AIEndpointService(
        MemoryStateStore(), CredentialVault(tmp_path / "vault"), tmp_path / "ai.yaml"
    )

    endpoint = service.add("local-ollama", "ollama", "http://127.0.0.1:11434")

    assert endpoint.credential_ref is None
    with pytest.raises(AIEndpointError, match="loopback"):
        service.add("remote", "ollama", "http://models.example.com:11434")


def test_invalid_endpoint_id_does_not_store_supplied_secret(tmp_path):
    vault = CredentialVault(tmp_path / "vault")
    service = AIEndpointService(MemoryStateStore(), vault, tmp_path / "ai.yaml")

    with pytest.raises(AIEndpointError, match="Invalid AI endpoint"):
        service.add("INVALID ID", "openai", "https://api.openai.com", api_key="secret")

    assert vault.list() == []
