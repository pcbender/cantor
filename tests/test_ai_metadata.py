from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from canto import cli as cli_module
from canto.core.ai_discovery import ModelCatalogService
from canto.core.ai_metadata import ModelMetadataError, ModelMetadataService
from canto.core.state import MemoryStateStore
from canto.models.ai_workers import AIModelRecord


def catalog_with_model():
    store = MemoryStateStore()
    catalog = ModelCatalogService(store, None)
    model = AIModelRecord(
        model_key="local:coder",
        endpoint_id="local",
        provider="ollama",
        provider_model_id="coder",
        resolved_version="digest",
        catalog_checksum="checksum",
        availability="available",
    )
    store.set_ai_record("model", model.model_key, model.model_dump(mode="json"))
    return store, catalog, model


def test_reviewed_metadata_is_source_labeled_without_changing_model(tmp_path):
    store, catalog, model = catalog_with_model()
    path = tmp_path / "metadata.json"
    path.write_text(json.dumps({"family": "Qwen", "coding_claim": True}))

    record = ModelMetadataService(store, catalog).add_file(
        model.model_key, path, source_kind="curated", reviewed=True
    )

    assert record.source_kind == "curated"
    assert record.source_checksum
    assert record.fields["family"] == "Qwen"
    assert catalog.get(model.model_key).classification == "unvalidated"


def test_metadata_requires_review_and_rejects_observed_source(tmp_path):
    _, catalog, model = catalog_with_model()
    path = tmp_path / "metadata.json"
    path.write_text("{}")
    service = ModelMetadataService(catalog.store, catalog)

    with pytest.raises(ModelMetadataError, match="reviewed"):
        service.add_file(model.model_key, path, source_kind="curated")
    with pytest.raises(ModelMetadataError, match="declared or curated"):
        service.add_file(
            model.model_key, path, source_kind="observed", reviewed=True
        )


def test_metadata_cli_requires_explicit_review(monkeypatch, tmp_path):
    store, catalog, model = catalog_with_model()
    service = ModelMetadataService(store, catalog)
    monkeypatch.setattr(cli_module, "_ai_metadata_service", lambda: service)
    path = tmp_path / "metadata.json"
    path.write_text('{"family": "Qwen"}')
    runner = CliRunner()

    rejected = runner.invoke(
        cli_module.app,
        [
            "ai",
            "model",
            "metadata-add",
            model.model_key,
            str(path),
            "--source-kind",
            "curated",
        ],
    )
    accepted = runner.invoke(
        cli_module.app,
        [
            "ai",
            "model",
            "metadata-add",
            model.model_key,
            str(path),
            "--source-kind",
            "curated",
            "--reviewed",
        ],
    )

    assert rejected.exit_code == 2
    assert "explicitly reviewed" in rejected.stderr
    assert accepted.exit_code == 0
    assert '"source_kind": "curated"' in accepted.stdout
