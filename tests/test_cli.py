from __future__ import annotations

from typer.testing import CliRunner

import canto.cli as cli_module
from canto.models.schemas import JobRequest


def test_run_prints_job_id_before_processing(runtime, monkeypatch):
    settings, registry, store, service = runtime
    job = service.create_job(
        JobRequest(
            skill="scaffold_tool",
            provider="local_scaffolder",
            inputs={"name": "sample_tool"},
        )
    )
    monkeypatch.setattr(cli_module, "_runtime", lambda: (settings, store, registry, service))
    monkeypatch.setattr(service, "create_job", lambda request: job)
    monkeypatch.setattr(service, "process_job", lambda job_id: job)

    result = CliRunner().invoke(
        cli_module.app,
        ["run", "scaffold_tool", "--provider", "local_scaffolder", "--input", "name=sample_tool"],
    )

    assert result.exit_code == 0
    assert f"Created {job.job_id} (queued); processing..." in result.output
    assert f'"job_id": "{job.job_id}"' in result.output
