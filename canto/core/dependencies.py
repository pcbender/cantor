from __future__ import annotations

import importlib.metadata
import shutil
from typing import Any


def check_dependencies(manifests: list[dict[str, Any]]) -> dict[str, Any]:
    system = sorted({item for manifest in manifests for item in manifest.get("dependencies", {}).get("system", [])})
    python = sorted({item for manifest in manifests for item in manifest.get("dependencies", {}).get("python", [])})
    missing_system = [name for name in system if shutil.which(name) is None]
    missing_python = []
    for name in python:
        try:
            importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            missing_python.append(name)

    install_plan = [
        {"type": "python", "command": f"python -m pip install {name}", "approval_required": False}
        for name in missing_python
    ]
    install_plan.extend(
        {"type": "system", "command": f"sudo apt install {name}", "approval_required": True}
        for name in missing_system
    )
    return {
        "status": "ready" if not missing_system and not missing_python else "not_ready",
        "missing": {"system": missing_system, "python": missing_python},
        "install_plan": install_plan,
    }

