#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")"/.. && pwd)"
SITES_FILE="$ROOT_DIR/data/top_sites.txt"

if [[ ! -f "$SITES_FILE" ]]; then
  echo "Sites list not found: $SITES_FILE" >&2
  exit 1
fi

source "$ROOT_DIR/.venv/bin/activate"

count=0
while IFS= read -r domain; do
  [[ -z "$domain" ]] && continue
  echo "[RUN] $domain" | cat
  python3 "$ROOT_DIR/orchestrator_mbp0.py" --command "browser: https://$domain" --auto-yes | cat || true
  count=$((count+1))
  # small delay to avoid rate limiting
  sleep 1
done < "$SITES_FILE"

echo "Done. Processed $count domains." | cat

