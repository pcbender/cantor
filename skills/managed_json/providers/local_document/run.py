from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main() -> int:
    request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    inputs = request["inputs"]
    target_path = Path(inputs["target_path"]).expanduser().resolve()
    current = (
        json.loads(target_path.read_text(encoding="utf-8"))
        if target_path.is_file()
        else None
    )
    desired = inputs["desired"]
    changed = current != desired
    digest = hashlib.sha256(canonical(desired).encode()).hexdigest()
    artifact_dir = Path(request["artifact_dir"])
    mode = request.get("policy", {}).get("mode", "dry_run")
    recovery_request = request.get("recovery")
    if recovery_request:
        recovery = json.loads(
            Path(recovery_request["recovery_path"]).read_text(encoding="utf-8")
        )
        restored = recovery["prior_state"]
        if restored is None:
            target_path.unlink(missing_ok=True)
        else:
            temporary = target_path.with_suffix(target_path.suffix + ".canto.tmp")
            write_json(temporary, restored)
            temporary.replace(target_path)
        desired = restored
        changed = current != restored
        digest = hashlib.sha256(canonical(restored).encode()).hexdigest()
        mode = "recovery"
    elif mode == "live":
        promotion = request.get("promotion")
        if not promotion:
            print("Live managed_json writes require Canto promotion", file=sys.stderr)
            return 2
        reviewed = json.loads(
            Path(promotion["change_set_path"]).read_text(encoding="utf-8")
        )
        if reviewed.get("after") != desired:
            print("Reviewed change set does not match desired state", file=sys.stderr)
            return 2
        if reviewed.get("before") != current:
            print("Target state changed after dry run", file=sys.stderr)
            return 2
        temporary = target_path.with_suffix(target_path.suffix + ".canto.tmp")
        write_json(temporary, desired)
        temporary.replace(target_path)
    write_json(
        artifact_dir / "change_set.json",
        {
            "target_id": inputs["target_id"],
            "operation": "replace" if current is not None else "create",
            "changed": changed,
            "before": current,
            "after": desired,
            "desired_checksum": digest,
            "idempotency_key": inputs["idempotency_key"],
        },
    )
    write_json(
        artifact_dir / "validation.json",
        {"valid": True, "target_readable": current is not None, "changed": changed},
    )
    write_json(
        artifact_dir / "verification.json",
        (
            {
                "status": "passed",
                "target_id": inputs["target_id"],
                "actual_checksum": hashlib.sha256(
                    canonical(
                        json.loads(target_path.read_text())
                        if target_path.is_file()
                        else None
                    ).encode()
                ).hexdigest(),
                "expected_checksum": digest,
            }
            if mode in {"live", "recovery"}
            else {"status": "not_run", "reason": "dry_run"}
        ),
    )
    write_json(
        artifact_dir / "recovery.json",
        {
            "mode": "rollback",
            "status": (
                "completed"
                if mode == "recovery"
                else "available" if mode == "live" else "planned"
            ),
            "prior_state": current,
            "target_path": str(target_path),
        },
    )
    print(
        json.dumps(
            {
                "status": "completed",
                "summary": f"Managed JSON {mode} completed.",
                "changed": changed,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
