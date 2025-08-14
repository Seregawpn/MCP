import time
from typing import Dict


def navigate(url: str, timeout_s: int = 20) -> Dict:
	start = time.time()
	time.sleep(min(0.2, timeout_s * 0.01))
	return {"status": "ok", "url": url, "elapsed_ms": int((time.time() - start) * 1000)}


def close_banners() -> Dict:
	time.sleep(0.05)
	return {"status": "ok", "closed": 1}


def extract_summary() -> Dict:
	# Static placeholder summary for MBP-0
	return {"status": "ok", "summary": "Краткая сводка страницы (стаб)."}
