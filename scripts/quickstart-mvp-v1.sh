#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CANTO_BIN=${CANTO_BIN:-"$ROOT/.venv/bin/canto"}
DEMO_HOME=$(mktemp -d)
trap 'rm -rf "$DEMO_HOME"' EXIT
export HOME="$DEMO_HOME"

TARGET="$DEMO_HOME/managed.json"
printf '%s\n' '{"status":"before"}' > "$TARGET"

echo "Checking local Canto runtime..."
"$CANTO_BIN" health

echo "Creating deterministic dry run..."
DRY_RUN=$(
  "$CANTO_BIN" run managed_json \
    --provider local_document \
    --input "target_path=$TARGET" \
    --input target_id=quickstart:local \
    --input 'desired={"status":"after"}' \
    --input idempotency_key=quickstart-1
)
DRY_JOB=$(printf '%s' "$DRY_RUN" | python3 -c 'import json,sys; print(json.load(sys.stdin)["job_id"])')

echo "Requesting and approving live promotion..."
PROMOTION=$("$CANTO_BIN" promote "$DRY_JOB")
PROMOTION_ID=$(printf '%s' "$PROMOTION" | python3 -c 'import json,sys; print(json.load(sys.stdin)["approval_id"])')
LIVE=$("$CANTO_BIN" approve "$PROMOTION_ID" --note "MVP quickstart")
LIVE_JOB=$(printf '%s' "$LIVE" | python3 -c 'import json,sys; print(json.load(sys.stdin)["job_id"])')

python3 -c 'import json,sys; assert json.load(open(sys.argv[1])) == {"status":"after"}' "$TARGET"

echo "Requesting and approving rollback..."
RECOVERY=$("$CANTO_BIN" recover "$LIVE_JOB")
RECOVERY_ID=$(printf '%s' "$RECOVERY" | python3 -c 'import json,sys; print(json.load(sys.stdin)["approval_id"])')
"$CANTO_BIN" approve "$RECOVERY_ID" --note "MVP quickstart rollback" >/dev/null

python3 -c 'import json,sys; assert json.load(open(sys.argv[1])) == {"status":"before"}' "$TARGET"
echo "Canto MVP v1 local quickstart passed."
