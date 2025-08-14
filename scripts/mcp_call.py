import asyncio
import json
import sys
from typing import Any, Dict, List

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import TextContent


async def run_call(session: ClientSession, tool: str, args: Dict[str, Any]) -> Any:
	result = await session.call_tool(tool, arguments=args)
	structured = getattr(result, "structuredContent", None)
	if structured is not None:
		print(json.dumps(structured, ensure_ascii=False, indent=2))
		return structured
	# fallback to textual content
	texts = []
	for c in getattr(result, "content", []) or []:
		if isinstance(c, TextContent):
			texts.append(c.text)
	print("\n".join(texts))
	return None


async def main() -> None:
	if len(sys.argv) < 2:
		usage = (
			"Usage:\n"
			"  python3 scripts/mcp_call.py <tool_name> [json_args]\n"
			"  python3 scripts/mcp_call.py batch '<JSON_ARRAY_OF_CALLS>'\n"
			"    where JSON_ARRAY_OF_CALLS = [{\"tool\":\"name\",\"args\":{}}]"
		)
		print(usage, file=sys.stderr)
		sys.exit(2)

	tool = sys.argv[1]
	args: Dict[str, Any] = {}
	if len(sys.argv) >= 3:
		args = json.loads(sys.argv[2])

	server_params = StdioServerParameters(command="python3", args=["mcp_server.py"])

	async with stdio_client(server_params) as (read, write):
		async with ClientSession(read, write) as session:
			await session.initialize()
			if tool == "batch":
				calls: List[Dict[str, Any]] = args if isinstance(args, list) else []
				for call in calls:
					await run_call(session, call.get("tool", ""), call.get("args", {}))
				return
			await run_call(session, tool, args)


if __name__ == "__main__":
	asyncio.run(main())
