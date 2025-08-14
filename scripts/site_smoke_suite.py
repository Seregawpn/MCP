import asyncio
import json
from typing import Any, Dict, List

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


SITES: List[str] = [
	"https://wikipedia.org",
	"https://www.bbc.com",
	"https://www.cnn.com",
	"https://www.nytimes.com",
	"https://github.com",
	"https://stack Overflow.com".replace(" ", ""),
	"https://medium.com",
	"https://news.ycombinator.com",
	"https://www.apple.com",
	"https://www.microsoft.com",
	"https://www.wikipedia.org",
	"https://www.w3schools.com",
	"https://the-internet.herokuapp.com",
	"https://example.com",
	"https://www.mozilla.org",
	"https://www.oracle.com",
	"https://www.adobe.com",
	"https://www.salesforce.com",
	"https://www.shopify.com",
	"https://www.cloudflare.com",
	"https://about.google",
	"https://www.reddit.com",
	"https://www.linkedin.com",
	"https://www.imdb.com",
	"https://www.wikipedia.org/wiki/Playwright".replace(" ", ""),
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


async def test_site(session: ClientSession, url: str) -> Dict[str, Any]:
	result: Dict[str, Any] = {"url": url}
	try:
		result["navigate"] = await call(session, "browser_navigate", {"url": url})
		await call(session, "browser_close_banners", {})
		await call(session, "browser_wait", {"network_idle": True})
		li = await call(session, "browser_list_interactives", {"limit": 50})
		result["list_interactives"] = li
		summary = await call(session, "browser_extract", {"mode": "summary"})
		result["extract"] = summary
		items = li.get("result", {}).get("items", [])
		first_link = None
		for it in items:
			if it.get("role") == "link":
				first_link = it
				break
		if first_link:
			click_res = await call(session, "browser_act", {"id": first_link["id"], "action": "click"})
			result["click_link"] = click_res
			await call(session, "browser_wait", {"network_idle": True})
			back_res = await call(session, "browser_back", {})
			result["back"] = back_res
			await call(session, "browser_wait", {"network_idle": True})
		result["status"] = "ok"
	except Exception as e:
		result["status"] = "error"
		result["error"] = str(e)
	return result


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
