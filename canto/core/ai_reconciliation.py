from __future__ import annotations

from uuid import uuid4

from canto.core.ai_discovery import (
    DiscoveryAdapter,
    HttpDiscoveryAdapter,
    ModelCatalogService,
    ModelDiscoveryError,
    _checksum,
)
from canto.core.ai_endpoints import AIEndpointService, endpoint_is_local
from canto.core.state import StateStore
from canto.models.ai_workers import (
    AIModelRecord,
    EndpointHealthRecord,
    ModelCatalogSnapshot,
    ModelReconciliationRecord,
)
from canto.models.schemas import utc_now


class ModelReconciliationError(ModelDiscoveryError):
    def __init__(self, message: str, record: ModelReconciliationRecord | None = None):
        self.record = record
        super().__init__(message)


class LocalModelReconciliationService:
    RECONCILIATION_RECORD = "model_reconciliation"

    def __init__(
        self,
        store: StateStore,
        endpoints: AIEndpointService,
        adapter: DiscoveryAdapter | None = None,
    ):
        self.store = store
        self.endpoints = endpoints
        self.adapter = adapter or HttpDiscoveryAdapter()
        self.catalog = ModelCatalogService(store, endpoints, self.adapter)

    def refresh(self, endpoint_id: str) -> ModelReconciliationRecord:
        endpoint = self.endpoints.get(endpoint_id)
        if not endpoint.enabled:
            raise ModelReconciliationError(f"AI endpoint is disabled: {endpoint_id}")
        if endpoint.provider != "ollama" or not endpoint_is_local(endpoint):
            raise ModelReconciliationError(
                "Local model refresh requires a loopback Ollama endpoint"
            )
        previous_snapshot = self._latest_successful_snapshot(endpoint_id)
        previous_models = {model.model_key: model for model in self.catalog.list(endpoint_id)}
        now = utc_now()
        try:
            discovered_models, raw = self.adapter.list_models(
                endpoint, self.endpoints.credential(endpoint)
            )
        except Exception as exc:
            for model in previous_models.values():
                if model.availability != "missing":
                    updated = model.model_copy(
                        update={
                            "availability": "endpoint_unreachable",
                            "availability_reason": str(exc),
                            "updated_at": now,
                        }
                    )
                    self._save_model(updated)
            record = ModelReconciliationRecord(
                reconciliation_id=f"reconcile_{uuid4().hex}",
                endpoint_id=endpoint_id,
                previous_snapshot_id=(
                    previous_snapshot.snapshot_id if previous_snapshot else None
                ),
                authoritative_success=False,
                error=str(exc),
            )
            self._save_reconciliation(record)
            self._save_health(endpoint_id, False, str(exc))
            raise ModelReconciliationError(
                f"Local model refresh failed for {endpoint_id}: {exc}", record
            ) from exc

        current_keys: set[str] = set()
        added: list[str] = []
        changed: list[str] = []
        unchanged: list[str] = []
        for discovered in discovered_models:
            model_key = f"{endpoint_id}:{discovered.provider_model_id}"
            current_keys.add(model_key)
            previous = previous_models.get(model_key)
            item_checksum = _checksum(discovered.metadata or discovered.__dict__)
            is_changed = bool(
                previous
                and (
                    previous.resolved_version != discovered.resolved_version
                    or previous.catalog_checksum != item_checksum
                )
            )
            if previous is None:
                added.append(model_key)
            elif is_changed:
                changed.append(model_key)
            else:
                unchanged.append(model_key)
            record = AIModelRecord(
                model_key=model_key,
                endpoint_id=endpoint_id,
                provider=endpoint.provider,
                provider_model_id=discovered.provider_model_id,
                resolved_version=discovered.resolved_version,
                display_name=discovered.display_name,
                aliases=previous.aliases if previous else [],
                context_tokens=discovered.context_tokens,
                max_output_tokens=discovered.max_output_tokens,
                capabilities=discovered.capabilities or {},
                pricing=previous.pricing if previous else {},
                classification=(previous.classification if previous else "unvalidated"),
                probe_version=previous.probe_version if previous else None,
                probe_stale=(is_changed or previous.probe_stale if previous else True),
                probe_state=(
                    "stale"
                    if is_changed
                    else previous.probe_state
                    if previous
                    else "absent"
                ),
                availability="available",
                availability_reason="returned by successful local refresh",
                last_seen_at=now,
                missing_since=None,
                runtime_metadata=discovered.metadata or {},
                metadata_provenance=sorted(
                    set((previous.metadata_provenance if previous else []) + ["runtime"])
                ),
                catalog_checksum=item_checksum,
                discovered_at=previous.discovered_at if previous else now,
                updated_at=now,
            )
            self._save_model(record)

        missing = sorted(set(previous_models) - current_keys)
        for model_key in missing:
            previous = previous_models[model_key]
            updated = previous.model_copy(
                update={
                    "availability": "missing",
                    "availability_reason": "absent from successful local refresh",
                    "missing_since": previous.missing_since or now,
                    "updated_at": now,
                }
            )
            self._save_model(updated)

        snapshot = ModelCatalogSnapshot(
            snapshot_id=f"catalog_{uuid4().hex}",
            endpoint_id=endpoint_id,
            models=sorted(current_keys),
            response_checksum=_checksum(raw),
            mode="refresh",
            authoritative_success=True,
            added=sorted(added),
            changed=sorted(changed),
            missing=missing,
            unchanged=sorted(unchanged),
        )
        self.store.set_ai_record(
            self.catalog.SNAPSHOT_RECORD,
            snapshot.snapshot_id,
            snapshot.model_dump(mode="json"),
        )
        reconciliation = ModelReconciliationRecord(
            reconciliation_id=f"reconcile_{uuid4().hex}",
            endpoint_id=endpoint_id,
            previous_snapshot_id=(
                previous_snapshot.snapshot_id if previous_snapshot else None
            ),
            current_snapshot_id=snapshot.snapshot_id,
            authoritative_success=True,
            added=snapshot.added,
            changed=snapshot.changed,
            missing=snapshot.missing,
            unchanged=snapshot.unchanged,
        )
        self._save_reconciliation(reconciliation)
        self._save_health(endpoint_id, True, f"Refreshed {len(current_keys)} models")
        self.endpoints.save(
            endpoint.model_copy(
                update={
                    "validation_status": "valid",
                    "validation_detail": f"Refreshed {len(current_keys)} local models",
                    "validated_at": now,
                    "updated_at": now,
                }
            )
        )
        return reconciliation

    def list_reconciliations(
        self, endpoint_id: str | None = None
    ) -> list[ModelReconciliationRecord]:
        records = [
            ModelReconciliationRecord.model_validate(value)
            for value in self.store.list_ai_records(self.RECONCILIATION_RECORD)
        ]
        return [
            record
            for record in records
            if endpoint_id is None or record.endpoint_id == endpoint_id
        ]

    def latest_reconciliation(
        self, endpoint_id: str
    ) -> ModelReconciliationRecord | None:
        records = self.list_reconciliations(endpoint_id)
        return max(records, key=lambda record: record.created_at) if records else None

    def _latest_successful_snapshot(
        self, endpoint_id: str
    ) -> ModelCatalogSnapshot | None:
        snapshots = [
            ModelCatalogSnapshot.model_validate(value)
            for value in self.store.list_ai_records(self.catalog.SNAPSHOT_RECORD)
            if value.get("endpoint_id") == endpoint_id
            and value.get("authoritative_success", True)
        ]
        return max(snapshots, key=lambda item: item.discovered_at) if snapshots else None

    def _save_model(self, model: AIModelRecord) -> None:
        self.store.set_ai_record(
            self.catalog.MODEL_RECORD, model.model_key, model.model_dump(mode="json")
        )

    def _save_reconciliation(self, record: ModelReconciliationRecord) -> None:
        self.store.set_ai_record(
            self.RECONCILIATION_RECORD,
            record.reconciliation_id,
            record.model_dump(mode="json"),
        )

    def _save_health(self, endpoint_id: str, available: bool, detail: str) -> None:
        record = EndpointHealthRecord(
            health_id=f"health_{uuid4().hex}",
            endpoint_id=endpoint_id,
            available=available,
            detail=detail,
        )
        self.store.set_ai_record(
            "endpoint_health", record.health_id, record.model_dump(mode="json")
        )
