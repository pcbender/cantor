from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from canto.core.cli_executor import (
    CliExecutionResult,
    CliExecutor,
    CodexCliAdapter,
    WorkerAuthError,
)
from canto.models.delegation import ExecutorProfile


class StubAdapter:
    provider = "stub"

    def __init__(self, argv):
        self.argv = argv
        self.completed = None

    def build_argv(self, profile, workspace):
        return list(self.argv)

    def parse(self, completed, workspace, *, base_commit, allowed_paths, denied_paths):
        self.completed = completed
        return CliExecutionResult(
            stdout=completed.stdout,
            stderr=completed.stderr,
            exit_code=completed.returncode,
            workspace_changed=False,
            outcome="advisory",
            outcome_detail="stub parsed",
        )

    def assert_auth(self, profile=None):
        return None

    def map_quota(self, completed):
        return False


def profile() -> ExecutorProfile:
    return ExecutorProfile(
        executor_id="stub",
        name="Stub",
        harness="codex_cli",
        launch_mode="canto",
    )


def test_cli_executor_runs_with_prompt_and_scrubbed_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    script = tmp_path / "worker.py"
    script.write_text(
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "Path('prompt.txt').write_text(sys.stdin.read(), encoding='utf-8')\n"
        "Path('env.json').write_text(json.dumps(dict(os.environ)), encoding='utf-8')\n"
        "print('done')\n",
        encoding="utf-8",
    )
    adapter = StubAdapter([sys.executable, str(script)])

    result = CliExecutor(adapter, timeout_seconds=10).run(
        profile(),
        tmp_path,
        "bounded prompt",
        base_commit="HEAD",
        allowed_paths=[],
        denied_paths=[],
    )

    assert result.exit_code == 0
    assert result.stdout == "done\n"
    assert (tmp_path / "prompt.txt").read_text(encoding="utf-8") == "bounded prompt"
    env = json.loads((tmp_path / "env.json").read_text(encoding="utf-8"))
    assert "OPENAI_API_KEY" not in env


def test_cli_executor_timeout_returns_launch_evidence(tmp_path):
    adapter = StubAdapter(
        [sys.executable, "-c", "import time; time.sleep(5)"]
    )

    result = CliExecutor(adapter, timeout_seconds=1).run(
        profile(),
        tmp_path,
        "prompt",
        base_commit="HEAD",
        allowed_paths=[],
        denied_paths=[],
    )

    assert result.timed_out is True
    assert adapter.completed is None


def test_codex_auth_preflight_accepts_subscription_auth(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    auth = tmp_path / ".codex" / "auth.json"
    auth.parent.mkdir()
    auth.write_text(
        json.dumps({"auth_mode": "chatgpt", "OPENAI_API_KEY": None}),
        encoding="utf-8",
    )

    CodexCliAdapter().assert_auth()


def test_codex_auth_preflight_rejects_api_key_auth(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    auth = tmp_path / ".codex" / "auth.json"
    auth.parent.mkdir()
    auth.write_text(
        json.dumps({"auth_mode": "api", "OPENAI_API_KEY": "secret"}),
        encoding="utf-8",
    )

    with pytest.raises(WorkerAuthError, match="subscription auth"):
        CodexCliAdapter().assert_auth()


def test_codex_auth_preflight_skips_local_ollama_profile():
    CodexCliAdapter().assert_auth(
        ExecutorProfile(
            executor_id="local",
            name="Local",
            harness="codex_cli",
            model_provider="ollama",
        )
    )
