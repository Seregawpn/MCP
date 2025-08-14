import asyncio
import json
from typing import Any, Dict, List, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SITES: List[str] = [
    # Энциклопедии/новости/блоги
    "https://wikipedia.org",
    "https://www.bbc.com",
    "https://www.cnn.com",
    "https://www.nytimes.com",
    "https://news.ycombinator.com",
    "https://medium.com",
    # Тех/доки
    "https://github.com",
    "https://stackoverflow.com",
    "https://www.mozilla.org",
    "https://developer.apple.com",
    # Корпоративные/продуктовые
    "https://www.apple.com",
    "https://www.microsoft.com",
    "https://www.adobe.com",
    "https://www.cloudflare.com",
    # Крупные площадки/видео/маркетплейсы
    "https://www.amazon.com",
    "https://www.youtube.com",
    # Shopify (маркетинг + несколько витрин)
    "https://www.shopify.com/",
    "https://avone-demo.myshopify.com/",
    "https://minimog-home.myshopify.com/",
    # E-commerce/маркетплейсы/демо-магазины
    "https://books.toscrape.com/",
    "https://demostore.x-cart.com/",
    "https://magento.softwaretestingboard.com/",
    "https://demo.opencart.com/",
    # Учебные/тестовые площадки
    "https://www.w3schools.com/",
    "https://the-internet.herokuapp.com/upload",
    "https://the-internet.herokuapp.com/download",
    # Прочие
    "https://example.com",
    "https://about.google",
    "https://www.reddit.com",
    "https://www.imdb.com",
]

async def call(session: ClientSession, tool: str, args: Dict[str, Any]) -> Dict[str, Any]:
	res = await session.call_tool(tool, arguments=args)
	structured = getattr(res, "structuredContent", None)
	if structured:
		return structured
	content = getattr(res, "content", None)
	if content:
		try:
			if isinstance(content, list) and content:
				first = content[0]
				if isinstance(first, dict):
					text = first.get("text") or first.get("data") or ""
					if isinstance(text, str) and text.strip().startswith("{"):
						return json.loads(text)
					return {"status": "unknown", "raw": True, "content": content}
		except Exception:
			return {"status": "unknown", "raw": True}
	return {"status": "unknown", "raw": True}


def find_first(items: List[Dict[str, Any]], role: str, name_contains: Optional[str] = None) -> Optional[Dict[str, Any]]:
	for it in items:
		if it.get("role") == role:
			name = (it.get("name") or "").lower()
			if name_contains is None or name_contains.lower() in name:
				return it
	return None

async def test_site(session: ClientSession, url: str) -> Dict[str, Any]:
	res: Dict[str, Any] = {"url": url, "steps": {}}
	try:
		res["steps"]["navigate"] = await call(session, "browser_navigate", {"url": url})
		_ = await call(session, "browser_close_banners", {})
		_ = await call(session, "browser_wait", {"network_idle": True})

		li = await call(session, "browser_list_interactives", {"limit": 120})
		res["steps"]["list_interactives"] = li
		_ = await call(session, "browser_overlay_show", {"scheme": "high-contrast"})
		items = li.get("result", {}).get("items", [])

		# Type into a textbox if present
		textbox = find_first(items, "textbox")
		if textbox:
			res["steps"]["type"] = await call(session, "browser_act", {"id": textbox["id"], "action": "type", "text": "test"})
			_ = await call(session, "browser_press", {"key": "Enter"})
			_ = await call(session, "browser_wait", {"network_idle": True})

		# Click a search or generic button if present
		button = find_first(items, "button", "search") or find_first(items, "button")
		if button:
			idx = items.index(button) + 1
			res["steps"]["click_button"] = await call(session, "browser_overlay_act", {"index": idx, "action": "click", "limit": 120})
			_ = await call(session, "browser_wait", {"network_idle": True})

		# Scrolls
		res["steps"]["scroll_bottom"] = await call(session, "browser_scroll", {"to": "bottom"})
		res["steps"]["scroll_top"] = await call(session, "browser_scroll", {"to": "top"})
		res["steps"]["scroll_delta"] = await call(session, "browser_scroll", {"by_x": 0, "by_y": 300})

		# Overlay
		res["steps"]["overlay_show"] = await call(session, "browser_overlay_show", {"scheme": "high-contrast"})
		res["steps"]["overlay_hide"] = await call(session, "browser_overlay_hide", {})

		# Extract
		res["steps"]["extract"] = await call(session, "browser_extract", {"mode": "summary"})

		# Links: безопасный клик по первой ссылке (без открытия новой вкладки), затем back
		link = find_first(items, "link")
		if link:
			idx = items.index(link) + 1
			res["steps"]["click_link"] = await call(session, "browser_overlay_act", {"index": idx, "action": "click", "limit": 120})
			_ = await call(session, "browser_wait", {"network_idle": True})
			res["steps"]["back_after_link"] = await call(session, "browser_back", {})
			_ = await call(session, "browser_wait", {"network_idle": True})

		# Find by text/role and click
		# Попытка найти часто встречающиеся разделы: about/contact/help/shop
		find_res = await call(session, "browser_find", {"role": "link", "text": "about", "limit": 200})
		res["steps"]["find_about"] = find_res
		fi = find_res.get("items") if find_res.get("status") == "ok" else []
		if isinstance(fi, list) and fi:
			res["steps"]["act_find"] = await call(session, "browser_act", {"id": fi[0]["id"], "action": "click"})
			_ = await call(session, "browser_wait", {"network_idle": True})
		else:
			find_res2 = await call(session, "browser_find", {"role": "link", "text": "contact", "limit": 200})
			res["steps"]["find_contact"] = find_res2
			fi2 = find_res2.get("items") if find_res2.get("status") == "ok" else []
			if isinstance(fi2, list) and fi2:
				res["steps"]["act_find2"] = await call(session, "browser_act", {"id": fi2[0]["id"], "action": "click"})
				_ = await call(session, "browser_wait", {"network_idle": True})
			else:
				find_res3 = await call(session, "browser_find", {"role": "link", "text": "help", "limit": 200})
				res["steps"]["find_help"] = find_res3

		# History
		res["steps"]["back"] = await call(session, "browser_back", {})
		res["steps"]["forward"] = await call(session, "browser_forward", {})
		res["steps"]["reload"] = await call(session, "browser_reload", {})

		# Focus navigation
		res["steps"]["focus_next"] = await call(session, "browser_focus_next", {"role": "link"})
		res["steps"]["focus_prev"] = await call(session, "browser_focus_prev", {"role": "link"})

		# Special cases
		if "herokuapp.com/download" in url:
			li2 = await call(session, "browser_list_interactives", {"limit": 200})
			it2 = li2.get("result", {}).get("items", [])
			dl = None
			for it in it2:
				name = (it.get("name") or "").lower()
				if it.get("role") == "link" and (name.endswith(".txt") or name.endswith(".png") or name.endswith(".jpg")):
					dl = it
					break
			if dl:
				res["steps"]["download"] = await call(session, "browser_click_and_wait_download", {"id": dl["id"], "timeout_ms": 20000})
		if "herokuapp.com/upload" in url:
			li3 = await call(session, "browser_list_interactives", {"limit": 200})
			it3 = li3.get("result", {}).get("items", [])
			file_input = find_first(it3, "textbox", "file") or (it3[0] if it3 else None)
			if file_input:
				import os
				tmp_path = os.path.join("/Users/sergiyzasorin/Desktop/untitled folder", "tmp_upload.txt")
				try:
					with open(tmp_path, "w", encoding="utf-8") as f:
						f.write("test upload")
				except Exception:
					pass
				res["steps"]["upload"] = await call(session, "browser_upload", {"id": file_input["id"], "files": [tmp_path]})

		res["status"] = "ok"
	except Exception as e:
		res["status"] = "error"
		res["error"] = str(e)
	return res

async def main() -> None:
	server = StdioServerParameters(command="python3", args=["mcp_server.py"])
	async with stdio_client(server) as (read, write):
		async with ClientSession(read, write) as session:
			await session.initialize()
			all_results: List[Dict[str, Any]] = []
			for url in SITES:
				print(f"\n=== Testing: {url} ===")
				r = await test_site(session, url)
				all_results.append(r)
				print(json.dumps(r, ensure_ascii=False, indent=2))
			summary = {
				"total": len(all_results),
				"ok": sum(1 for r in all_results if r.get("status") == "ok"),
				"error": sum(1 for r in all_results if r.get("status") != "ok"),
			}
			print("\n=== Summary ===")
			print(json.dumps(summary, ensure_ascii=False, indent=2))

if __name__ == "__main__":
	asyncio.run(main())
