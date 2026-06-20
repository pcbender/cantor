from __future__ import annotations

from canto.core.cli_env import BLOCKED_ENV_KEYS, build_subprocess_env


def test_cli_worker_environment_uses_allowlist_and_strips_api_keys(monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("HOME", "/home/example")
    monkeypatch.setenv("LANG", "C.UTF-8")
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret")
    monkeypatch.setenv("GEMINI_API_KEY", "secret")
    monkeypatch.setenv("GOOGLE_API_KEY", "secret")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.invalid")
    monkeypatch.setenv("UNRELATED_SECRET", "secret")

    env = build_subprocess_env("codex")

    assert env["HOME"] == "/home/example"
    assert env["LANG"] == "C.UTF-8"
    assert env["PATH"] == "/usr/bin"
    assert set(env) <= {"HOME", "LANG", "LC_ALL", "PATH", "TERM", "TZ"}
    assert BLOCKED_ENV_KEYS.isdisjoint(env)
