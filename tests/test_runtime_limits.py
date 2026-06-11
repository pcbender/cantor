from __future__ import annotations

import json
from dataclasses import replace

import pytest

from canto.core.runner import RunnerError, effective_limits, run_provider


def make_provider(tmp_path, source, **extra):
    manifest = tmp_path / "provider.yaml"
    manifest.write_text("name: limited\n", encoding="utf-8")
    script = tmp_path / "run.py"
    script.write_text(source, encoding="utf-8")
    value = {
        "runner": {"type": "python", "entrypoint": "run.py"},
        "permissions": {
            "network_read": False,
            "network_write": False,
            "destructive": False,
        },
        "_manifest_path": str(manifest),
    }
    value.update(extra)
    return value


def test_provider_limits_can_only_lower_global_ceilings(runtime, tmp_path):
    settings, _, _, _ = runtime
    provider = make_provider(
        tmp_path,
        "",
        limits={
            "wall_seconds": 999,
            "cpu_seconds": 2,
            "memory_bytes": 1_000_000,
            "artifact_bytes": 2000,
        },
    )

    limits = effective_limits(provider, settings)

    assert limits["wall_seconds"] == settings.provider_timeout_seconds
    assert limits["cpu_seconds"] == 2
    assert limits["memory_bytes"] == 1_000_000
    assert limits["artifact_bytes"] == 2000


def test_artifact_limit_fails_job(runtime, tmp_path):
    settings, _, _, _ = runtime
    settings = replace(settings, max_job_artifact_bytes=32)
    provider = make_provider(
        tmp_path,
        """import json, os, sys
from pathlib import Path
Path(os.environ['CANTO_ARTIFACT_DIR'], 'large.txt').write_text('x' * 64)
print(json.dumps({'status': 'completed', 'summary': 'done'}))
""",
    )
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()

    with pytest.raises(RunnerError, match="artifacts exceed"):
        run_provider(provider, {}, artifact_dir, settings)


def test_network_permission_fails_closed_without_allowlist_enforcement(
    runtime, tmp_path
):
    settings, _, _, _ = runtime
    provider = make_provider(
        tmp_path,
        "print('unused')\n",
        permissions={"network_read": True, "network_write": False},
    )

    with pytest.raises(RunnerError, match="egress_enforcement"):
        run_provider(
            provider,
            {"policy": {"approved_domains": ["example.com"]}},
            tmp_path,
            settings,
        )


def test_network_provider_requires_approved_domains(runtime, tmp_path):
    settings, _, _, _ = runtime
    provider = make_provider(tmp_path, "print('unused')\n")
    provider["permissions"]["network_read"] = True
    provider["runner"]["egress_enforcement"] = "provider_allowlist"

    with pytest.raises(RunnerError, match="no approved egress domains"):
        run_provider(provider, {"policy": {}}, tmp_path, settings)
