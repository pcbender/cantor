from __future__ import annotations

import json
import sys
from pathlib import Path


request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
artifact = Path(request["artifact_dir"]) / "mvp-v1-demo.json"
artifact.write_text(
    json.dumps(
        {
            "contract_version": "1.0",
            "credential_received": bool(request["inputs"]["demo_token_ref"]),
            "status": "completed",
        },
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)
print(json.dumps({"status": "completed", "summary": "MVP v1 demo complete."}))
