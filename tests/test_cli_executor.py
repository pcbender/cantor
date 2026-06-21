from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from canto.core.cli_executor import (
    ClaudeCliAdapter,
    CliExecutionResult,
    CliExecutor,
    CodexCliAdapter,
    GeminiCliAdapter,
    WorkerAuthError,
    adapter_for_profile,
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


def test_codex_ollama_command_adds_canto_state_dir_and_loopback_network(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("CANTO_HOME", str(tmp_path / "canto-home"))
    monkeypatch.setattr(
        "canto.core.cli_executor.shutil.which",
        lambda value: f"/usr/bin/{value}",
    )
    profile = ExecutorProfile(
        executor_id="codex-ollama",
        name="Codex Ollama",
        harness="codex_cli",
        model_provider="ollama",
        model="qwen3.6:35b-a3b",
        launch_mode="canto",
    )

    command = CodexCliAdapter().build_argv(profile, tmp_path / "workspace")

    assert command[1:4] == ["exec", "--sandbox", "workspace-write"]
    assert command[command.index("--add-dir") + 1] == str(
        (tmp_path / "canto-home").resolve()
    )
    assert command[command.index("-c") + 1] == (
        "sandbox_workspace_write.network_access=true"
    )
    assert command[command.index("--cd") + 1] == str((tmp_path / "workspace").resolve())
    assert command[-1] == "-"


def test_codex_cloud_command_enables_network_for_nested_worker(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("CANTO_HOME", str(tmp_path / "canto-home"))
    monkeypatch.setattr(
        "canto.core.cli_executor.shutil.which",
        lambda value: f"/usr/bin/{value}",
    )
    profile = ExecutorProfile(
        executor_id="codex-cloud",
        name="Codex Cloud",
        harness="codex_cli",
        model_provider="openai",
        model="gpt-5.4-mini",
        launch_mode="canto",
    )

    command = CodexCliAdapter().build_argv(profile, tmp_path / "workspace")

    assert command[command.index("--add-dir") + 1] == str(
        (tmp_path / "canto-home").resolve()
    )
    assert command[command.index("-c") + 1] == (
        "sandbox_workspace_write.network_access=true"
    )


def test_codex_explicit_network_permission_enables_network_for_local_profile(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("CANTO_HOME", str(tmp_path / "canto-home"))
    monkeypatch.setattr(
        "canto.core.cli_executor.shutil.which",
        lambda value: f"/usr/bin/{value}",
    )
    profile = ExecutorProfile(
        executor_id="codex-local-network",
        name="Codex Local Network",
        harness="codex_cli",
        model_provider="ollama",
        launch_mode="canto",
        permissions={"allow_network": True},
    )

    command = CodexCliAdapter().build_argv(profile, tmp_path / "workspace")

    assert command[command.index("-c") + 1] == (
        "sandbox_workspace_write.network_access=true"
    )


def test_adapter_for_profile_supports_claude_and_gemini_profiles():
    assert isinstance(
        adapter_for_profile(
            ExecutorProfile(
                executor_id="claude",
                name="Claude",
                harness="claude_cli",
            )
        ),
        ClaudeCliAdapter,
    )
    assert isinstance(
        adapter_for_profile(
            ExecutorProfile(
                executor_id="gemini",
                name="Gemini",
                harness="gemini_cli",
            )
        ),
        GeminiCliAdapter,
    )


def test_claude_command_uses_print_mode_and_workspace_scope(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "canto.core.cli_executor.shutil.which",
        lambda value: f"/usr/bin/{value}",
    )
    profile = ExecutorProfile(
        executor_id="claude",
        name="Claude",
        harness="claude_cli",
        model="sonnet",
        launch_mode="canto",
    )

    command = ClaudeCliAdapter().build_argv(profile, tmp_path)

    assert command[:2] == ["/usr/bin/claude", "--print"]
    assert "--input-format" in command
    assert command[command.index("--add-dir") + 1] == str(tmp_path.resolve())
    assert command[command.index("--model") + 1] == "sonnet"


def test_gemini_command_uses_headless_sandboxed_auto_edit(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "canto.core.cli_executor.shutil.which",
        lambda value: f"/usr/bin/{value}",
    )
    profile = ExecutorProfile(
        executor_id="gemini",
        name="Gemini",
        harness="gemini_cli",
        model="gemini-2.5-flash",
        launch_mode="canto",
    )

    command = GeminiCliAdapter().build_argv(profile, tmp_path)

    assert Path(command[0]).name in {"gemini", "gemini.js"}
    assert command[1:3] == ["--prompt", ""]
    assert "--skip-trust" in command
    assert "--sandbox" in command
    assert command[command.index("--approval-mode") + 1] == "auto_edit"
    assert command[command.index("--model") + 1] == "gemini-2.5-flash"
