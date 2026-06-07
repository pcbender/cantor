from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def main() -> int:
    request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    artifact_dir = Path(request["artifact_dir"])
    inputs = request["inputs"]
    name = inputs["name"]
    if not re.fullmatch(r"[a-z][a-z0-9_]{1,63}", name):
        raise ValueError("Tool name must be lowercase snake_case and 2-64 characters")
    description = inputs.get("description", "TODO tool description")
    manifest = f"""name: {name}
version: 0.1.0
type: tool
description: {description}
runtime:
  language: python
  entrypoint: run.py
dependencies:
  system: [python3]
permissions:
  network_read: false
  destructive: false
risk_level: 1
"""
    runner = '''from __future__ import annotations

import json
import sys


def main() -> int:
    print(json.dumps({"status": "completed", "summary": "TODO"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''
    (artifact_dir / "tool.yaml").write_text(manifest, encoding="utf-8")
    (artifact_dir / "run.py").write_text(runner, encoding="utf-8")
    (artifact_dir / "README.md").write_text(f"# {name}\n\nUnregistered Canto tool scaffold.\n", encoding="utf-8")
    (artifact_dir / "test_tool.py").write_text("def test_tool_placeholder():\n    assert True\n", encoding="utf-8")
    print(json.dumps({"status": "completed", "summary": f"Created unregistered scaffold for tool {name}.", "artifacts": {"scaffold_manifest": "tool.yaml", "scaffold_runner": "run.py", "scaffold_readme": "README.md", "scaffold_test": "test_tool.py"}, "warnings": ["Scaffold is not registered."], "needs_human": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

