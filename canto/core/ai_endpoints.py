from __future__ import annotations

import ipaddress
import json
from pathlib import Path
from urllib.parse import urlparse

import yaml
from pydantic import ValidationError

from canto.core.credentials import CredentialError, CredentialVault
from canto.core.state import StateStore
from canto.models.ai_workers import AIEndpointRecord, AIProvider
from canto.models.schemas import utc_now


class AIEndpointError(ValueError):
    pass


CLOUD_PROVIDERS = {"openai", "anthropic", "google", "openai_compatible"}


def endpoint_is_local(endpoint: AIEndpointRecord) -> bool:
    parsed = urlparse(endpoint.base_url)
    host = parsed.hostname
    if endpoint.provider == "ollama" and host:
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return host == "localhost"
    return False


class AIEndpointService:
    RECORD_TYPE = "endpoint"

    def __init__(
        self,
        store: StateStore,
        vault: CredentialVault,
        config_file: str | Path,
    ):
        self.store = store
        self.vault = vault
        self.config_file = Path(config_file)

    def add(
        self,
        endpoint_id: str,
        provider: AIProvider,
        base_url: str,
        *,
        api_key: str | None = None,
        credential_ref: str | None = None,
        configuration: dict | None = None,
    ) -> AIEndpointRecord:
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise AIEndpointError("Endpoint base URL must be an absolute HTTP(S) URL")
        if provider in CLOUD_PROVIDERS and parsed.scheme != "https":
            raise AIEndpointError("Cloud AI endpoints require HTTPS")
        try:
            candidate = AIEndpointRecord(
                endpoint_id=endpoint_id,
                provider=provider,
                base_url=base_url.rstrip("/"),
            )
        except ValidationError as exc:
            raise AIEndpointError(f"Invalid AI endpoint configuration: {exc}") from exc
        if provider == "ollama" and parsed.scheme == "http":
            if not endpoint_is_local(candidate):
                raise AIEndpointError("Plain HTTP Ollama endpoints must use loopback")
        if api_key and credential_ref:
            raise AIEndpointError("Provide an API key or credential reference, not both")
        if api_key:
            credential_ref = self.vault.set("ai", endpoint_id, api_key)
        if provider in CLOUD_PROVIDERS and not credential_ref:
            raise AIEndpointError("Cloud AI endpoints require a vault credential reference")
        if credential_ref:
            if not credential_ref.startswith("vault:ai/"):
                raise AIEndpointError("AI endpoint credentials must use vault:ai/ references")
            try:
                self.vault.resolve_reference(credential_ref)
            except CredentialError as exc:
                raise AIEndpointError(str(exc)) from exc
        current = self.get(endpoint_id, required=False)
        now = utc_now()
        endpoint = AIEndpointRecord(
            endpoint_id=endpoint_id,
            provider=provider,
            base_url=base_url.rstrip("/"),
            credential_ref=credential_ref,
            configuration=configuration or {},
            created_at=current.created_at if current else now,
            updated_at=now,
        )
        self.store.set_ai_record(
            self.RECORD_TYPE, endpoint_id, endpoint.model_dump(mode="json")
        )
        self._write_config()
        return endpoint

    def save(self, endpoint: AIEndpointRecord) -> AIEndpointRecord:
        self.store.set_ai_record(
            self.RECORD_TYPE, endpoint.endpoint_id, endpoint.model_dump(mode="json")
        )
        self._write_config()
        return endpoint

    def get(self, endpoint_id: str, *, required: bool = True) -> AIEndpointRecord | None:
        value = self.store.get_ai_record(self.RECORD_TYPE, endpoint_id)
        if not value:
            if required:
                raise AIEndpointError(f"AI endpoint not found: {endpoint_id}")
            return None
        return AIEndpointRecord.model_validate(value)

    def list(self) -> list[AIEndpointRecord]:
        return [
            AIEndpointRecord.model_validate(value)
            for value in self.store.list_ai_records(self.RECORD_TYPE)
        ]

    def disable(self, endpoint_id: str) -> AIEndpointRecord:
        endpoint = self.get(endpoint_id)
        return self.save(
            endpoint.model_copy(update={"enabled": False, "updated_at": utc_now()})
        )

    def credential(self, endpoint: AIEndpointRecord) -> str | None:
        if not endpoint.credential_ref:
            return None
        return self.vault.resolve_reference(endpoint.credential_ref)

    def _write_config(self) -> None:
        self.config_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        values = {
            "version": 1,
            "endpoints": [
                {
                    "endpoint_id": endpoint.endpoint_id,
                    "provider": endpoint.provider,
                    "base_url": endpoint.base_url,
                    **(
                        {"credential_ref": endpoint.credential_ref}
                        if endpoint.credential_ref
                        else {}
                    ),
                    "enabled": endpoint.enabled,
                    **(
                        {"configuration": endpoint.configuration}
                        if endpoint.configuration
                        else {}
                    ),
                }
                for endpoint in self.list()
            ],
        }
        temporary = self.config_file.with_suffix(".tmp")
        temporary.write_text(yaml.safe_dump(values, sort_keys=False), encoding="utf-8")
        temporary.replace(self.config_file)
        self.config_file.chmod(0o600)

    def export_json(self) -> str:
        return json.dumps(
            [endpoint.model_dump(mode="json") for endpoint in self.list()],
            sort_keys=True,
        )
