from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import canto.core.runner as runner_module
from canto.core.runner import RunnerError, run_provider
from canto.core.runner_contract import RunnerContractError, validate_runner_contract


def provider(tmp_path, runtime, entrypoint):
    manifest = tmp_path / "provider.yaml"
    manifest.write_text("name: test\n", encoding="utf-8")
    return {
        "name": "test",
        "runner": {"type": runtime, "entrypoint": entrypoint},
        "_manifest_path": str(manifest),
    }


def test_node_adapter_uses_shared_protocol(runtime, tmp_path):
    settings, _, _, _ = runtime
    script = tmp_path / "run.js"
    script.write_text(
        """const fs = require('fs');
const request = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
console.log(JSON.stringify({status: 'completed', summary: request.inputs.value}));
""",
        encoding="utf-8",
    )
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()

    result = run_provider(
        provider(tmp_path, "node", "run.js"),
        {"inputs": {"value": "node-ok"}},
        artifact_dir,
        settings,
    )

    assert result["summary"] == "node-ok"


def test_binary_adapter_uses_shared_protocol(runtime, tmp_path):
    settings, _, _, _ = runtime
    script = tmp_path / "run.sh"
    script.write_text(
        "#!/bin/sh\nprintf '%s\\n' '{\"status\":\"completed\",\"summary\":\"binary-ok\"}'\n",
        encoding="utf-8",
    )
    os.chmod(script, 0o700)
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()

    result = run_provider(
        provider(tmp_path, "binary", "run.sh"),
        {"inputs": {}},
        artifact_dir,
        settings,
    )

    assert result["summary"] == "binary-ok"


def test_container_adapter_fails_clearly_without_runtime(runtime, tmp_path, monkeypatch):
    settings, _, _, _ = runtime
    manifest = tmp_path / "provider.yaml"
    manifest.write_text("name: container\n", encoding="utf-8")
    container_provider = {
        "runner": {"type": "container", "image": "local/test:1", "command": ["run"]},
        "_manifest_path": str(manifest),
    }
    monkeypatch.setattr(runner_module.shutil, "which", lambda name: None)

    with pytest.raises(RunnerError, match="container runtime"):
        run_provider(container_provider, {}, tmp_path, settings)


def test_runner_contract_rejects_invalid_container():
    with pytest.raises(RunnerContractError, match="requires image"):
        validate_runner_contract(
            {"runner": {"type": "container", "command": ["run"]}}
        )
