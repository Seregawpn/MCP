import argparse
import json
import os
import sys
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List

try:
  import yaml  # type: ignore
except Exception:
  yaml = None

# MCP client
import asyncio
from mcp import ClientSession, StdioServerParameters  # type: ignore
from mcp.client.stdio import stdio_client  # type: ignore

from urllib.parse import urlparse

CONFIG_DIR = os.path.join(os.path.dirname(__file__), "config")
RUNS_DIR = os.path.join(os.path.dirname(__file__), "agent_runs")


TOOL_NAME_MAP: Dict[str, str] = {
  "browser.navigate": "browser_navigate",
  "browser.close_banners": "browser_close_banners",
  "browser.extract": "browser_extract",
  "files.search": "files_search",
  "files.read_text": "files_read_text",
}


def _now_iso() -> str:
  return datetime.utcnow().isoformat() + "Z"


def _ensure_dir(path: str) -> None:
  os.makedirs(path, exist_ok=True)


def load_yaml_config(name: str) -> Dict[str, Any]:
  path = os.path.join(CONFIG_DIR, name)
  if not os.path.exists(path):
    return {}
  if yaml is None:
    return {}
  with open(path, "r", encoding="utf-8") as f:
    return yaml.safe_load(f) or {}


def write_event(run_dir: str, event: Dict[str, Any]) -> None:
  _ensure_dir(run_dir)
  events_path = os.path.join(run_dir, "events.jsonl")
  with open(events_path, "a", encoding="utf-8") as f:
    f.write(json.dumps(event, ensure_ascii=False) + "\n")


def write_meta(run_dir: str, meta: Dict[str, Any]) -> None:
  _ensure_dir(run_dir)
  meta_path = os.path.join(run_dir, "meta.json")
  with open(meta_path, "w", encoding="utf-8") as f:
    json.dump(meta, f, ensure_ascii=False, indent=2)


def classify_command(natural_command: str) -> Dict[str, Any]:
  text = natural_command.strip().lower()
  if text.startswith("browser:") or "http" in text or "browser" in text:
    tokens = natural_command.split()
    url = None
    for tok in tokens:
      if tok.startswith("http://") or tok.startswith("https://"):
        url = tok
        break
    if url is None:
      url = "https://example.com"
    return {"intent": "browser_summary", "url": url}
  if text.startswith("files:") or "files" in text or "прочитай файл" in text:
    path = None
    if ":" in natural_command:
      path = natural_command.split(":", 1)[1].strip()
    if not path:
      path = "MBP-0 план.md"
    return {"intent": "files_read", "path": path}
  return {"intent": "browser_summary", "url": "https://example.com"}


def build_plan(intent: Dict[str, Any]) -> List[Dict[str, Any]]:
  steps: List[Dict[str, Any]] = []
  if intent["intent"] == "browser_summary":
    steps.append({"tool": "browser.navigate", "args": {"url": intent["url"]}})
    steps.append({"tool": "browser.extract", "args": {"mode": "summary"}})
    return steps
  if intent["intent"] == "files_read":
    steps.append({"tool": "files.search", "args": {"query": os.path.basename(intent["path"])}})
    steps.append({"tool": "files.read_text", "args": {"path": intent["path"], "max_chars": 500}})
    return steps
  return steps


def render_plan_text(steps: List[Dict[str, Any]]) -> str:
  parts = []
  for idx, st in enumerate(steps, 1):
    parts.append(f"{idx}) {st['tool']} {st['args']}")
  return "; ".join(parts)


def op_level(tool_name: str, security_cfg: Dict[str, Any]) -> int:
  ops = security_cfg.get("operations", {})
  for level in ("level2", "level1", "level0"):
    if tool_name in set(ops.get(level, [])):
      return int(level[-1])
  return 1


def require_confirmation(auto_yes: bool, steps: List[Dict[str, Any]], security_cfg: Dict[str, Any]) -> bool:
  if auto_yes:
    return True
  max_level = 0
  for st in steps:
    lvl = op_level(st["tool"], security_cfg)
    if lvl > max_level:
      max_level = lvl
  print("Подтвердите выполнение плана (да/нет):", flush=True)
  ans = sys.stdin.readline().strip().lower()
  if ans not in ("да", "ok", "ок", "yes", "y", "д", "ага"):
    return False
  if max_level >= 2:
    print("Требуется вторичное подтверждение для рискованных операций (да/нет):", flush=True)
    ans2 = sys.stdin.readline().strip().lower()
    if ans2 not in ("да", "ok", "ок", "yes", "y", "д", "ага"):
      return False
  return True


def extract_host(url: str) -> str:
  try:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
      host = host[4:]
    return host
  except Exception:
    return ""


def is_host_allowed(host: str, security_cfg: Dict[str, Any]) -> Dict[str, Any]:
  domains = security_cfg.get("domains", {})
  allow = domains.get("allow", []) or []
  deny = domains.get("deny", []) or []
  if host in deny:
    return {"allowed": False, "reason": "denied_explicit"}
  if "*" in allow:
    return {"allowed": True, "reason": "allowed_wildcard"}
  if host in allow:
    return {"allowed": True, "reason": "allowed_explicit"}
  if allow:
    return {"allowed": False, "reason": "not_in_allow_list"}
  return {"allowed": True, "reason": "no_allow_list"}


def evaluate_plan_security(steps: List[Dict[str, Any]], security_cfg: Dict[str, Any]) -> Dict[str, Any]:
  decisions: List[Dict[str, Any]] = []
  blocked = False
  for st in steps:
    if st["tool"] == "browser.navigate":
      url = st.get("args", {}).get("url", "")
      host = extract_host(url)
      decision = is_host_allowed(host, security_cfg)
      decisions.append({"tool": st["tool"], "url": url, "host": host, **decision})
      if not decision["allowed"]:
        blocked = True
  return {"decisions": decisions, "blocked": blocked}


def get_timeout_and_retries(tool_name: str, timeouts_cfg: Dict[str, Any]) -> Dict[str, int]:
  # tool_name is logical, e.g., "browser.navigate"
  try:
    section, op = tool_name.split(".", 1)
  except Exception:
    section, op = "browser", "navigate"
  section_cfg = timeouts_cfg.get(section, {}) if isinstance(timeouts_cfg, dict) else {}
  op_cfg = section_cfg.get(op, {}) if isinstance(section_cfg, dict) else {}
  timeout = int(op_cfg.get("timeout", 15))
  retries = int(op_cfg.get("retries", 1))
  return {"timeout": timeout, "retries": retries}


async def call_with_retry_and_timeout(session: ClientSession, mapped_tool: str, args: Dict[str, Any], logical_tool: str, timeouts_cfg: Dict[str, Any], run_dir: str, run_id: str) -> Dict[str, Any]:
  policy = get_timeout_and_retries(logical_tool, timeouts_cfg)
  timeout_s = max(1, int(policy["timeout"]))
  retries = max(0, int(policy["retries"]))
  backoffs = [0.5, 1.0, 1.5]
  attempt = 0
  last_error: Any = None
  while attempt <= retries:
    try:
      coro = session.call_tool(mapped_tool, arguments=args)
      call_result = await asyncio.wait_for(coro, timeout=timeout_s)
      structured = getattr(call_result, "structuredContent", None)
      if structured is None:
        text_blocks = []
        for c in getattr(call_result, "content", []) or []:
          try:
            text = getattr(c, "text", None)
            if text:
              text_blocks.append(text)
          except Exception:
            pass
        return {"status": "ok", "text": "\n".join(text_blocks)}
      return structured
    except asyncio.TimeoutError as e:
      last_error = {"status": "error", "error": "network_timeout", "details": str(e)}
    except Exception as e:
      last_error = {"status": "error", "error": str(e)}
    # optional fallback for future click/type
    if logical_tool in ("browser.click", "browser.type") and attempt == 0:
      try:
        await session.call_tool("browser_close_banners", arguments={})
        write_event(run_dir, {"ts": _now_iso(), "type": "retry_fallback", "tool": logical_tool, "action": "browser_close_banners", "run_id": run_id})
      except Exception:
        pass
    if attempt < retries:
      backoff = backoffs[attempt] if attempt < len(backoffs) else backoffs[-1]
      write_event(run_dir, {"ts": _now_iso(), "type": "retry", "tool": logical_tool, "attempt": attempt + 1, "backoff_s": backoff, "run_id": run_id, "error": last_error})
      await asyncio.sleep(backoff)
    attempt += 1
  return last_error or {"status": "error", "error": "unknown"}


async def execute_steps_via_mcp(steps: List[Dict[str, Any]], timeouts_cfg: Dict[str, Any], run_dir: str, run_id: str) -> List[Dict[str, Any]]:
  server_params = StdioServerParameters(command="python3", args=["mcp_server.py"])  # stdio transport
  results: List[Dict[str, Any]] = []
  async with stdio_client(server_params) as (read, write):
    async with ClientSession(read, write) as session:
      await session.initialize()
      # throttle for post-hook close_banners (seconds)
      last_close_ts = 0.0
      for st in steps:
        mapped = TOOL_NAME_MAP.get(st["tool"], st["tool"])
        args = st["args"]
        write_event(run_dir, {"ts": _now_iso(), "type": "tool_call", "tool": mapped, "args": args, "run_id": run_id})
        res_obj = await call_with_retry_and_timeout(session, mapped, args, st["tool"], timeouts_cfg, run_dir, run_id)
        results.append({"tool": st["tool"], "result": res_obj})
        write_event(run_dir, {"ts": _now_iso(), "type": "tool_result", "tool": mapped, "result": res_obj, "run_id": run_id})
        # Post-hook: auto close banners after risky actions
        try:
          trigger = st["tool"] in (
            "browser.navigate",
            "browser.reload",
            "browser.open_in_new_tab",
            "browser.switch_tab",
            "browser.act",
            "browser.overlay_act",
          )
          now_ts = time.monotonic()
          if trigger and (now_ts - last_close_ts) >= 2.0:
            cb_args = {
              "time_budget_ms": 2500,
              "max_passes": 3,
              "strategy": "safe",
              "languages": ["en", "ru"],
              "return_details": False,
            }
            write_event(run_dir, {"ts": _now_iso(), "type": "post_hook_call", "hook": "browser_close_banners", "args": cb_args, "run_id": run_id})
            hook_res = await session.call_tool("browser_close_banners", arguments=cb_args)
            try:
              hook_struct = getattr(hook_res, "structuredContent", None)
            except Exception:
              hook_struct = None
            write_event(run_dir, {"ts": _now_iso(), "type": "post_hook_result", "hook": "browser_close_banners", "result": hook_struct or {}, "run_id": run_id})
            last_close_ts = now_ts
        except Exception:
          # best-effort; ignore post-hook errors
          pass
  return results


def main() -> None:
  parser = argparse.ArgumentParser()
  parser.add_argument("--command", required=False, default="browser: summary https://example.com")
  parser.add_argument("--auto-yes", action="store_true")
  args = parser.parse_args()

  run_id = str(uuid.uuid4())
  run_dir = os.path.join(RUNS_DIR, run_id)
  _ensure_dir(run_dir)

  security_cfg = load_yaml_config("security.yml")
  timeouts_cfg = load_yaml_config("timeouts.yml")

  meta = {
    "run_id": run_id,
    "started_at": _now_iso(),
    "command": args.command,
    "configs": {
      "security": bool(security_cfg),
      "timeouts": bool(timeouts_cfg),
    },
  }
  write_meta(run_dir, meta)
  write_event(run_dir, {"ts": _now_iso(), "type": "command_received", "command": args.command, "run_id": run_id})

  intent = classify_command(args.command)
  steps = build_plan(intent)
  plan_text = render_plan_text(steps)
  write_event(run_dir, {"ts": _now_iso(), "type": "plan_created", "plan": steps, "run_id": run_id})

  sec_eval = evaluate_plan_security(steps, security_cfg)
  write_event(run_dir, {"ts": _now_iso(), "type": "security_evaluation", **sec_eval, "run_id": run_id})
  if sec_eval.get("blocked"):
    write_event(run_dir, {"ts": _now_iso(), "type": "error", "error": "not_whitelisted", "run_id": run_id})
    print("Отклонено политикой безопасности (whitelist).")
    return

  print(f"План: {plan_text}")
  write_event(run_dir, {"ts": _now_iso(), "type": "confirmation_requested", "level": "auto" if args.auto_yes else "manual", "run_id": run_id})

  if not require_confirmation(args.auto_yes, steps, security_cfg):
    write_event(run_dir, {"ts": _now_iso(), "type": "user_cancelled", "run_id": run_id})
    print("Отменено пользователем.")
    return

  results: List[Dict[str, Any]] = asyncio.run(execute_steps_via_mcp(steps, timeouts_cfg, run_dir, run_id))

  write_event(run_dir, {"ts": _now_iso(), "type": "summary", "results": results, "run_id": run_id})
  print("Готово. Итоги записаны в:", run_dir)


if __name__ == "__main__":
  main()
