from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import uuid4

from canto.core.ai_discovery import ModelCatalogService
from canto.core.state import StateStore
from canto.models.ai_workers import ModelMetadataRecord


class ModelMetadataError(RuntimeError):
    pass


class ModelMetadataService:
    RECORD_TYPE = "model_metadata"

    def __init__(self, store: StateStore, catalog: ModelCatalogService):
        self.store = store
        self.catalog = catalog

    def add_file(
        self,
        model_key: str,
        path: str | Path,
        *,
        source_kind: str,
        source_uri: str | None = None,
        confidence: str = "medium",
        reviewed: bool = False,
    ) -> ModelMetadataRecord:
        self.catalog.get(model_key)
        if source_kind not in {"declared", "curated"}:
            raise ModelMetadataError(
                "Manual metadata source must be declared or curated"
            )
        if not reviewed:
            raise ModelMetadataError(
                "Model metadata must be explicitly reviewed before storage"
            )
        source = Path(path)
        try:
            encoded = source.read_bytes()
            fields = json.loads(encoded)
        except (OSError, json.JSONDecodeError) as exc:
            raise ModelMetadataError(f"Cannot read model metadata: {exc}") from exc
        if not isinstance(fields, dict):
            raise ModelMetadataError("Model metadata file must contain a JSON object")
        record = ModelMetadataRecord(
            metadata_id=f"metadata_{uuid4().hex}",
            model_key=model_key,
            source_kind=source_kind,
            source_uri=source_uri or str(source.resolve()),
            source_checksum=hashlib.sha256(encoded).hexdigest(),
            fields=fields,
            confidence=confidence,
            reviewed=True,
        )
        self.store.set_ai_record(
            self.RECORD_TYPE, record.metadata_id, record.model_dump(mode="json")
        )
        return record
