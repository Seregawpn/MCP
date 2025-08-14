#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR"

echo "[MBP-0] Starting smoke demos..."

# Hint about MCP server
echo "If MCP server isn't running, start it in another terminal:"
echo "  source .venv/bin/activate && mcp run mcp_server.py"

# Scenario A: Browser summary
echo "\n[Scenario A] Browser summary (navigate -> close_banners -> extract)"
python3 orchestrator_mbp0.py --command "browser: summary https://example.com" --auto-yes | cat

# Scenario B: Files read
echo "\n[Scenario B] Files read (search -> read_text)"
python3 orchestrator_mbp0.py --command "files: MBP-0 план.md" --auto-yes | cat

echo "\n[MBP-0] Done. Logs are under agent_runs/<uuid>/"
