import json
from pathlib import Path

import pytest

from canto.core.capability_manifest import CapabilityManifest
from canto.core.local_registry import RegistryEntry
from canto.core.orchestration import ExecutionPlan, PlanExplanation, WorkflowStep


SCHEMA_DIR = Path(__file__).parents[1] / "docs" / "schemas"


@pytest.mark.parametrize(
    ("filename", "model"),
    [
        ("capability-manifest.schema.json", CapabilityManifest),
        ("execution-plan.schema.json", ExecutionPlan),
        ("workflow-step.schema.json", WorkflowStep),
        ("plan-explanation.schema.json", PlanExplanation),
        ("package-metadata.schema.json", RegistryEntry),
    ],
)
def test_checked_in_json_schema_matches_model(filename, model):
    checked_in = json.loads((SCHEMA_DIR / filename).read_text(encoding="utf-8"))

    assert checked_in == model.model_json_schema()
