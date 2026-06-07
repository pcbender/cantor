from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from canto.config import Settings
from canto.core.jobs import JobService
from canto.core.registry import Registry
from canto.core.state import MemoryStateStore


@pytest.fixture()
def runtime(tmp_path: Path):
    root = Path(__file__).resolve().parent.parent
    shutil.copytree(root / "skills", tmp_path / "skills")
    shutil.copytree(root / "tools", tmp_path / "tools")
    settings = Settings(
        root_dir=tmp_path,
        redis_url="redis://unused",
        host="127.0.0.1",
        port=8765,
        provider_timeout_seconds=10,
        max_provider_output_bytes=1_048_576,
    )
    registry = Registry(settings.skills_dir, settings.tools_dir)
    store = MemoryStateStore()
    service = JobService(settings, registry, store)
    return settings, registry, store, service

