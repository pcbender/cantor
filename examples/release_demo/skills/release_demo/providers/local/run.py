import json
import sys
from pathlib import Path


request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
artifact = Path(request["artifact_dir"]) / "release-demo.json"
artifact.write_text(
    json.dumps(
        {
            "contract_version": "1.0",
            "demo": "canto-v2.2",
            "status": "completed",
        },
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)
print(json.dumps({"status": "completed", "summary": "Release demo complete."}))
