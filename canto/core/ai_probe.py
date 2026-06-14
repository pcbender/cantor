from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from canto.core.ai_discovery import ModelCatalogService
from canto.core.state import StateStore
from canto.models.ai_workers import ProbeAssertion, WorkerProbeResult
from canto.models.schemas import utc_now


PROBE_VERSION = "1"


class WorkerProbeError(RuntimeError):
    pass


@dataclass
class ProbeObservation:
    responded: bool = True
    structured_tool_calls: list[str] = field(default_factory=list)
    detail: str = ""
    estimated_cost_usd: float | None = None
    actual_cost_usd: float | None = None


class WorkerProbeRunner(Protocol):
    def run_probe(self, model_key: str, workspace: Path) -> ProbeObservation: ...


class CodingWorkerProbeService:
    RECORD_TYPE = "probe"

    def __init__(
        self,
        store: StateStore,
        catalog: ModelCatalogService,
        runner: WorkerProbeRunner,
        artifact_root: str | Path,
    ):
        self.store = store
        self.catalog = catalog
        self.runner = runner
        self.artifact_root = Path(artifact_root)

    def probe(self, model_key: str) -> WorkerProbeResult:
        model = self.catalog.get(model_key)
        probe_id = f"probe_{uuid4().hex}"
        root = self.artifact_root / probe_id
        workspace = root / "workspace"
        workspace.mkdir(parents=True)
        (workspace / "PROBE.md").write_text(
            "Use structured tools to create result.txt containing "
            "canto-worker-probe and run a command that creates command.txt "
            "containing probe-ok.\n",
            encoding="utf-8",
        )
        subprocess.run(
            ["git", "init", "-q"], cwd=workspace, check=True, capture_output=True
        )
        observation = ProbeObservation(responded=False)
        failure = ""
        try:
            observation = self.runner.run_probe(model_key, workspace)
        except Exception as exc:  # Provider failures become durable evidence.
            failure = str(exc)
        assertions = [
            ProbeAssertion(
                name="responded",
                passed=observation.responded,
                detail=failure or observation.detail,
            ),
            ProbeAssertion(
                name="structured_file_edit",
                passed=(
                    "write_file" in observation.structured_tool_calls
                    and (workspace / "result.txt").is_file()
                    and (workspace / "result.txt").read_text(encoding="utf-8").strip()
                    == "canto-worker-probe"
                ),
                detail="Worker must edit through a structured tool call",
            ),
            ProbeAssertion(
                name="structured_command",
                passed=(
                    "run_command" in observation.structured_tool_calls
                    and (workspace / "command.txt").is_file()
                    and (workspace / "command.txt").read_text(encoding="utf-8").strip()
                    == "probe-ok"
                ),
                detail="Worker must execute a command through a structured tool call",
            ),
        ]
        if all(item.passed for item in assertions):
            classification = "implementation"
        elif observation.responded:
            classification = "advisory"
        else:
            classification = "unavailable"
        evidence = {
            "probe_version": PROBE_VERSION,
            "model_key": model_key,
            "resolved_version": model.resolved_version,
            "observation": {
                "responded": observation.responded,
                "structured_tool_calls": observation.structured_tool_calls,
                "detail": failure or observation.detail,
            },
            "assertions": [item.model_dump(mode="json") for item in assertions],
        }
        encoded = json.dumps(evidence, indent=2, sort_keys=True).encode()
        evidence_path = root / "evidence.json"
        evidence_path.write_bytes(encoded)
        result = WorkerProbeResult(
            probe_id=probe_id,
            model_key=model_key,
            endpoint_id=model.endpoint_id,
            provider_model_id=model.provider_model_id,
            resolved_version=model.resolved_version,
            probe_version=PROBE_VERSION,
            classification=classification,
            assertions=assertions,
            artifact_root=str(root),
            evidence_checksum=hashlib.sha256(encoded).hexdigest(),
            estimated_cost_usd=observation.estimated_cost_usd,
            actual_cost_usd=observation.actual_cost_usd,
            ended_at=utc_now(),
        )
        self.store.set_ai_record(
            self.RECORD_TYPE, probe_id, result.model_dump(mode="json")
        )
        updated = model.model_copy(
            update={
                "classification": classification,
                "probe_version": PROBE_VERSION,
                "probe_stale": False,
                "updated_at": utc_now(),
            }
        )
        self.store.set_ai_record(
            self.catalog.MODEL_RECORD, model_key, updated.model_dump(mode="json")
        )
        return result

    def list(self, model_key: str | None = None) -> list[WorkerProbeResult]:
        results = [
            WorkerProbeResult.model_validate(value)
            for value in self.store.list_ai_records(self.RECORD_TYPE)
        ]
        return [r for r in results if model_key is None or r.model_key == model_key]

