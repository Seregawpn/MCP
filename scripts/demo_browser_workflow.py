import asyncio
import json
from typing import Any, Dict, List, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def call(session: ClientSession, tool: str, args: Dict[str, Any]) -> Dict[str, Any]:
	res = await session.call_tool(tool, arguments=args)
	structured = getattr(res, "structuredContent", None)
	return structured or {"status": "unknown", "raw": True}


def pick_by_role(items: List[Dict[str, Any]], role: str, name_contains: Optional[str] = None) -> Optional[Dict[str, Any]]:
	for it in items:
		if it.get("role") == role:
			name = (it.get("name") or "").lower()
			if name_contains is None or name_contains.lower() in name:
				return it
	return None


def pick_first(items: List[Dict[str, Any]], role: str) -> Optional[Dict[str, Any]]:
	for it in items:
		if it.get("role") == role:
			return it
	return None


async def main() -> None:
	server = StdioServerParameters(command="python3", args=["mcp_server.py"])
	async with stdio_client(server) as (read, write):
		async with ClientSession(read, write) as session:
			await session.initialize()

			print("- Navigate wikipedia.org ...")
			print(json.dumps(await call(session, "browser_navigate", {"url": "https://wikipedia.org"}), ensure_ascii=False, indent=2))
			print(json.dumps(await call(session, "browser_wait", {"network_idle": True}), ensure_ascii=False, indent=2))

			print("- List interactives (first 50) ...")
			lst = await call(session, "browser_list_interactives", {"limit": 50})
			print(json.dumps(lst, ensure_ascii=False, indent=2))
			items = lst.get("result", {}).get("items", [])

			# find search textbox
			textbox = pick_by_role(items, "textbox", name_contains="search") or pick_first(items, "textbox")
			if textbox:
				print("- Type into textbox ...")
				print(json.dumps(await call(session, "browser_act", {"id": textbox["id"], "action": "type", "text": "playwright"}), ensure_ascii=False, indent=2))
				print(json.dumps(await call(session, "browser_press", {"key": "Enter"}), ensure_ascii=False, indent=2))
				print(json.dumps(await call(session, "browser_wait", {"network_idle": True}), ensure_ascii=False, indent=2))

			print("- Extract summary ...")
			print(json.dumps(await call(session, "browser_extract", {"mode": "summary"}), ensure_ascii=False, indent=2))

			print("- Scroll down/up ...")
			print(json.dumps(await call(session, "browser_scroll", {"to": "bottom"}), ensure_ascii=False, indent=2))
			print(json.dumps(await call(session, "browser_scroll", {"to": "top"}), ensure_ascii=False, indent=2))

			print("- List interactives again ...")
			lst2 = await call(session, "browser_list_interactives", {"limit": 50})
			print(json.dumps(lst2, ensure_ascii=False, indent=2))
			items2 = lst2.get("result", {}).get("items", [])
			link = pick_first(items2, "link")
			if link:
				print("- Open first link in new tab ...")
				print(json.dumps(await call(session, "browser_open_in_new_tab", {"id": link["id"]}), ensure_ascii=False, indent=2))
				print(json.dumps(await call(session, "browser_switch_tab", {"index": 1}), ensure_ascii=False, indent=2))

			print("- Overlay show/hide ...")
			print(json.dumps(await call(session, "browser_overlay_show", {"scheme": "high-contrast"}), ensure_ascii=False, indent=2))
			print(json.dumps(await call(session, "browser_overlay_hide", {}), ensure_ascii=False, indent=2))

			print("- Back / Forward / Reload ...")
			print(json.dumps(await call(session, "browser_back", {}), ensure_ascii=False, indent=2))
			print(json.dumps(await call(session, "browser_forward", {}), ensure_ascii=False, indent=2))
			print(json.dumps(await call(session, "browser_reload", {}), ensure_ascii=False, indent=2))


if __name__ == "__main__":
	asyncio.run(main())

