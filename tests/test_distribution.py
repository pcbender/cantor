from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path


def test_wheel_contains_builtin_skills_and_tools(tmp_path):
    root = Path(__file__).parents[1]
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            ".",
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            str(tmp_path),
        ],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    wheel = next(tmp_path.glob("*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
    assert "skills/managed_json/skill.yaml" in names
    assert "skills/managed_json/providers/local_document/run.py" in names
    assert "tools/http_fetch/tool.yaml" in names
    assert not any("__pycache__" in name or name.endswith(".pyc") for name in names)
