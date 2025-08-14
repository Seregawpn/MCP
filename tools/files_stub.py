import glob
import os
import time
from typing import Dict, List


def search_files(query: str, timeout_s: int = 10) -> Dict:
	start = time.time()
	pattern = f"**/*{query}*"
	matches: List[str] = [p for p in glob.glob(pattern, recursive=True) if os.path.isfile(p)]
	elapsed_ms = int((time.time() - start) * 1000)
	return {"status": "ok", "query": query, "matches": matches[:20], "elapsed_ms": elapsed_ms}


def read_text_file(path: str, max_chars: int = 500, timeout_s: int = 8) -> Dict:
	if not os.path.exists(path):
		return {"status": "error", "error": "file_not_found", "path": path}
	try:
		with open(path, "r", encoding="utf-8", errors="ignore") as f:
			content = f.read(max_chars)
		return {"status": "ok", "path": path, "preview": content}
	except Exception as e:
		return {"status": "error", "error": str(e), "path": path}
