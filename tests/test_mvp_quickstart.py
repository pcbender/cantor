from __future__ import annotations

import os
import subprocess
from pathlib import Path


def test_mvp_quickstart_script():
    root = Path(__file__).parents[1]
    env = os.environ.copy()
    env["CANTO_BIN"] = str(root / ".venv" / "bin" / "canto")

    result = subprocess.run(
        ["sh", str(root / "scripts" / "quickstart-mvp-v1.sh")],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Canto MVP v1 local quickstart passed." in result.stdout
