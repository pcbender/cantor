from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote
from uuid import uuid4

import requests

from canto.core.ai_endpoints import AIEndpointService
from canto.core.state import StateStore
from canto.models.ai_workers import (
    AIEndpointRecord,
    AIModelRecord,
    ModelCatalogSnapshot,
)
from canto.models.schemas import utc_now


class ModelDiscoveryError(RuntimeError):
    pass


def _checksum(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class DiscoveredModel:
    provider_model_id: str
    resolved_version: str
    display_name: str | None = None
    context_tokens: int | None = None
    max_output_tokens: int | None = None
    capabilities: dict[str, bool] | None = None
    metadata: dict[str, Any] | None = None


class DiscoveryAdapter(Protocol):
    def list_models(
        self, endpoint: AIEndpointRecord, credential: str | None
    ) -> tuple[list[DiscoveredModel], Any]: ...


class HttpDiscoveryAdapter:
    def __init__(self, session: requests.Session | None = None, timeout: float = 15):
        self.session = session or requests.Session()
        self.timeout = timeout

    def list_models(
        self, endpoint: AIEndpointRecord, credential: str | None
    ) -> tuple[list[DiscoveredModel], Any]:
        url, headers = self._request(endpoint, credential)
        response = self.session.get(
            url, headers=headers, timeout=self.timeout, allow_redirects=False
        )
        if 300 <= response.status_code < 400:
            raise ModelDiscoveryError("Provider discovery redirects are not followed")
        if response.status_code >= 400:
            raise ModelDiscoveryError(
                f"Model discovery failed for {endpoint.endpoint_id}: HTTP {response.status_code}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise ModelDiscoveryError(
                f"Model discovery returned invalid JSON for {endpoint.endpoint_id}"
            ) from exc
        return self._parse(endpoint, payload), payload

    @staticmethod
    def _request(
        endpoint: AIEndpointRecord, credential: str | None
    ) -> tuple[str, dict[str, str]]:
        base = endpoint.base_url.rstrip("/")
        if endpoint.provider in {"openai", "openai_compatible"}:
            suffix = "/models" if base.endswith("/v1") else "/v1/models"
            return base + suffix, {"Authorization": f"Bearer {credential}"}
        if endpoint.provider == "anthropic":
            return base + "/v1/models", {
                "x-api-key": credential or "",
                "anthropic-version": "2023-06-01",
            }
        if endpoint.provider == "google":
            return base + f"/v1beta/models?key={quote(credential or '')}", {}
        return base + "/api/tags", {}

    @staticmethod
    def _parse(endpoint: AIEndpointRecord, payload: Any) -> list[DiscoveredModel]:
        if endpoint.provider == "ollama":
            items = payload.get("models", [])
            return [
                DiscoveredModel(
                    provider_model_id=item["name"],
                    resolved_version=item.get("digest") or item["name"],
                    display_name=item.get("model") or item["name"],
                    capabilities={"tools": bool(item.get("capabilities", {}).get("tools"))},
                    metadata=item,
                )
                for item in items
            ]
        items = payload.get("models" if endpoint.provider == "google" else "data", [])
        models: list[DiscoveredModel] = []
        for item in items:
            identifier = item.get("name") or item.get("id")
            if not identifier:
                continue
            if endpoint.provider == "google" and identifier.startswith("models/"):
                identifier = identifier.removeprefix("models/")
            version = str(item.get("version") or item.get("id") or identifier)
            context = item.get("inputTokenLimit") or item.get("context_window")
            output = item.get("outputTokenLimit") or item.get("max_tokens")
            methods = item.get("supportedGenerationMethods", [])
            models.append(
                DiscoveredModel(
                    provider_model_id=identifier,
                    resolved_version=version,
                    display_name=item.get("displayName") or item.get("display_name"),
                    context_tokens=context,
                    max_output_tokens=output,
                    capabilities={
                        "tools": bool(item.get("supports_tools", False)),
                        "generate": not methods or "generateContent" in methods,
                    },
                    metadata=item,
                )
            )
        return models


class ModelCatalogService:
    MODEL_RECORD = "model"
    SNAPSHOT_RECORD = "catalog_snapshot"

    def __init__(
        self,
        store: StateStore,
        endpoints: AIEndpointService,
        adapter: DiscoveryAdapter | None = None,
    ):
        self.store = store
        self.endpoints = endpoints
        self.adapter = adapter or HttpDiscoveryAdapter()

    def discover(self, endpoint_id: str) -> ModelCatalogSnapshot:
        endpoint = self.endpoints.get(endpoint_id)
        if not endpoint.enabled:
            raise ModelDiscoveryError(f"AI endpoint is disabled: {endpoint_id}")
        credential = self.endpoints.credential(endpoint)
        models, raw = self.adapter.list_models(endpoint, credential)
        response_checksum = _checksum(raw)
        now = utc_now()
        keys: list[str] = []
        for discovered in models:
            model_key = f"{endpoint_id}:{discovered.provider_model_id}"
            previous = self.get(model_key, required=False)
            item_checksum = _checksum(discovered.metadata or discovered.__dict__)
            changed = bool(
                previous
                and (
                    previous.resolved_version != discovered.resolved_version
                    or previous.catalog_checksum != item_checksum
                )
            )
            record = AIModelRecord(
                model_key=model_key,
                endpoint_id=endpoint_id,
                provider=endpoint.provider,
                provider_model_id=discovered.provider_model_id,
                resolved_version=discovered.resolved_version,
                display_name=discovered.display_name,
                context_tokens=discovered.context_tokens,
                max_output_tokens=discovered.max_output_tokens,
                capabilities=discovered.capabilities or {},
                classification=previous.classification if previous else "unvalidated",
                probe_version=previous.probe_version if previous else None,
                probe_stale=changed or not previous or previous.probe_stale,
                probe_state=(
                    "stale"
                    if changed or (previous and previous.probe_stale)
                    else previous.probe_state
                    if previous
                    else "absent"
                ),
                availability="available",
                availability_reason="returned by endpoint discovery",
                last_seen_at=now,
                runtime_metadata=discovered.metadata or {},
                metadata_provenance=["runtime"],
                catalog_checksum=item_checksum,
                discovered_at=previous.discovered_at if previous else now,
                updated_at=now,
            )
            self.store.set_ai_record(
                self.MODEL_RECORD, model_key, record.model_dump(mode="json")
            )
            keys.append(model_key)
        snapshot = ModelCatalogSnapshot(
            snapshot_id=f"catalog_{uuid4().hex}",
            endpoint_id=endpoint_id,
            models=sorted(keys),
            response_checksum=response_checksum,
        )
        self.store.set_ai_record(
            self.SNAPSHOT_RECORD,
            snapshot.snapshot_id,
            snapshot.model_dump(mode="json"),
        )
        self.endpoints.save(
            endpoint.model_copy(
                update={
                    "validation_status": "valid",
                    "validation_detail": f"Discovered {len(keys)} models",
                    "validated_at": now,
                    "updated_at": now,
                }
            )
        )
        return snapshot

    def get(self, model_key: str, *, required: bool = True) -> AIModelRecord | None:
        value = self.store.get_ai_record(self.MODEL_RECORD, model_key)
        if not value:
            if required:
                raise ModelDiscoveryError(f"AI model not found: {model_key}")
            return None
        return AIModelRecord.model_validate(value)

    def list(self, endpoint_id: str | None = None) -> list[AIModelRecord]:
        models = [
            AIModelRecord.model_validate(value)
            for value in self.store.list_ai_records(self.MODEL_RECORD)
        ]
        return [m for m in models if endpoint_id is None or m.endpoint_id == endpoint_id]
