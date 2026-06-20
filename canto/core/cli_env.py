from __future__ import annotations

import os


SAFE_ENV_KEYS = {
    "HOME",
    "LANG",
    "LC_ALL",
    "PATH",
    "TERM",
    "TZ",
}

BLOCKED_ENV_KEYS = {
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_BASE_URL",
    "CODEX_API_KEY",
    "CODEX_BASE_URL",
    "GEMINI_API_KEY",
    "GEMINI_BASE_URL",
    "GOOGLE_API_KEY",
    "GOOGLE_BASE_URL",
    "OLLAMA_HOST",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
}


def build_subprocess_env(provider: str | None = None) -> dict[str, str]:
    """Return the bounded environment for subscription/local CLI Workers."""
    return {
        key: value
        for key, value in os.environ.items()
        if key in SAFE_ENV_KEYS and key not in BLOCKED_ENV_KEYS
    }
