"""
Интегрированный MCP сервер с DOM анализатором

Объединяет существующие инструменты с новыми DOM анализатор инструментами
в стиле browser-use для индексированного взаимодействия с веб-страницами.
"""

from typing import Dict, List, Any, Optional, TYPE_CHECKING
import os
import tempfile
import asyncio
import time
import json
from urllib.parse import urlparse

from mcp.server.fastmcp import FastMCP
try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None  # type: ignore

# Импортируем существующие инструменты (заглушки)
# from tools.browser_stub import navigate as stub_navigate, close_banners as stub_close_banners, extract_summary as stub_extract_summary
# from tools.files_stub import search_files as stub_search_files, read_text_file as stub_read_text

# Создаем заглушки для существующих инструментов
async def stub_navigate(url: str) -> Dict[str, Any]:
    """Заглушка для navigate"""
    return {"status": "stub", "message": f"Navigate to {url} (stub)", "url": url}

async def stub_close_banners() -> Dict[str, Any]:
    """Заглушка для close_banners"""
    return {"status": "stub", "message": "Close banners (stub)"}

async def stub_extract_summary() -> Dict[str, Any]:
    """Заглушка для extract_summary"""
    return {"status": "stub", "message": "Extract summary (stub)"}

async def stub_search_files(query: str) -> Dict[str, Any]:
    """Заглушка для search_files"""
    return {"status": "stub", "message": f"Search files: {query} (stub)"}

async def stub_read_text(path: str) -> Dict[str, Any]:
    """Заглушка для read_text"""
    return {"status": "stub", "message": f"Read text: {path} (stub)", "content": ""}

# Импортируем наши DOM анализатор инструменты
from dom_analyzer.mcp_tools import MCPDOMTools

# Автоматический запуск Chrome с CDP
import subprocess
import platform
import signal
import atexit

def _start_chrome_with_cdp():
    """Автоматически запускает Chrome с CDP портом 9222"""
    try:
        # Проверяем, не запущен ли уже Chrome с CDP
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex(('localhost', 9222))
        sock.close()
        
        if result == 0:
            print("✅ Chrome уже запущен с CDP на порту 9222")
            return None
        
        # Определяем команду запуска Chrome в зависимости от ОС
        if platform.system() == "Darwin":  # macOS
            chrome_cmd = [
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                "--remote-debugging-port=9222",
                "--user-data-dir=/tmp/chrome-debug",
                "--no-first-run",
                "--no-default-browser-check"
            ]
        elif platform.system() == "Linux":
            chrome_cmd = [
                "google-chrome",
                "--remote-debugging-port=9222",
                "--user-data-dir=/tmp/chrome-debug",
                "--no-first-run",
                "--no-default-browser-check"
            ]
        elif platform.system() == "Windows":
            chrome_cmd = [
                "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
                "--remote-debugging-port=9222",
                "--user-data-dir=C:\\temp\\chrome-debug",
                "--no-first-run",
                "--no-default-browser-check"
            ]
        else:
            print("❌ Неподдерживаемая ОС для автоматического запуска Chrome")
            return None
        
        print("🚀 Запускаю Chrome с CDP на порту 9222...")
        chrome_process = subprocess.Popen(
            chrome_cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )
        
        # Ждем немного для запуска Chrome
        time.sleep(3)
        
        # Проверяем, что порт открылся
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex(('localhost', 9222))
        sock.close()
        
        if result == 0:
            print("✅ Chrome успешно запущен с CDP на порту 9222")
            
            # Регистрируем функцию очистки при выходе
            def cleanup_chrome():
                try:
                    chrome_process.terminate()
                    chrome_process.wait(timeout=5)
                    print("🔌 Chrome с CDP остановлен")
                except:
                    chrome_process.kill()
            
            atexit.register(cleanup_chrome)
            
            return chrome_process
        else:
            print("❌ Не удалось запустить Chrome с CDP")
            chrome_process.terminate()
            return None
            
    except Exception as e:
        print(f"❌ Ошибка запуска Chrome с CDP: {e}")
        return None

# Автоматически запускаем Chrome при импорте модуля
_chrome_process = _start_chrome_with_cdp()

# Создаем MCP сервер
mcp = FastMCP(name="Blind Assistant Core with DOM Analyzer")

def _check_chrome_cdp_status():
    """Проверяет статус Chrome с CDP"""
    try:
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex(('localhost', 9222))
        sock.close()
        
        if result == 0:
            return {
                "status": "running",
                "port": 9222,
                "message": "Chrome запущен с CDP на порту 9222"
            }
        else:
            return {
                "status": "not_running",
                "port": 9222,
                "message": "Chrome не запущен с CDP"
            }
    except Exception as e:
        return {
            "status": "error",
            "port": 9222,
            "message": f"Ошибка проверки: {e}"
        }

@mcp.tool()
async def chrome_cdp_status() -> Dict[str, Any]:
    """Проверяет статус Chrome с CDP подключением."""
    return _check_chrome_cdp_status()

# Playwright (async API)
try:
    from playwright.async_api import async_playwright
except Exception:  # pragma: no cover
    async_playwright = None  # type: ignore

if TYPE_CHECKING:  # precise types for type checkers only
    from playwright.async_api import Playwright as PW, Browser, Page, Frame
else:  # at runtime, avoid hard dependency in annotations
    PW = Any  # type: ignore
    Browser = Any  # type: ignore
    Page = Any  # type: ignore
    Frame = Any  # type: ignore


class _BrowserSession:
    _pw: Optional["PW"] = None
    _browser: Optional["Browser"] = None
    _page: Optional["Page"] = None

    @classmethod
    async def ensure_started(cls) -> None:
        if async_playwright is None:
            return
        if cls._pw is None:
            cls._pw = await async_playwright().start()
        if cls._browser is None:
            cls._browser = await cls._pw.chromium.launch(headless=False)
        if cls._page is None:
            # set a fixed downloads path for deterministic browser_download_wait
            context = await cls._browser.new_context(accept_downloads=True)
            cls._page = await context.new_page()

    @classmethod
    def page(cls) -> Optional["Page"]:
        return cls._page


# Глобальные переменные для существующих инструментов
_LAST_ITEMS: Optional[List[Dict[str, Any]]] = None
_LAST_SNAPSHOT: Optional[Dict[str, Any]] = None  # { id: str, ts: int, items: List[Dict] }
_CLOSE_BANNERS_PROFILES: Dict[str, Any] = {"global": {"texts": [], "selectors": []}, "domains": {}}

# Глобальный экземпляр DOM анализатор инструментов
_dom_tools: Optional[MCPDOMTools] = None


def _project_root() -> str:
    try:
        return os.path.dirname(os.path.abspath(__file__))
    except Exception:
        return os.getcwd()


def _profiles_config_path() -> str:
    # config/close_banners_profiles.yml near this file
    base = _project_root()
    return os.path.join(base, "config", "close_banners_profiles.yml")


def _ensure_dir(path: str) -> None:
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        pass


def _load_close_banners_profiles() -> None:
    global _CLOSE_BANNERS_PROFILES
    cfg_path = _profiles_config_path()
    try:
        if yaml is None or not os.path.exists(cfg_path):
            return
        with open(cfg_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            return
        global_section = data.get("global", {}) or {}
        domains_section = data.get("domains", {}) or {}
        _CLOSE_BANNERS_PROFILES = {
            "global": {
                "texts": list(global_section.get("texts", []) or []),
                "selectors": list(global_section.get("selectors", []) or [])
            },
            "domains": domains_section
        }
    except Exception:
        pass


def _get_domain_from_url(url: str) -> str:
    try:
        parsed = urlparse(url)
        return parsed.hostname or ""
    except Exception:
        return ""


def _use_playwright() -> bool:
    return async_playwright is not None


async def _ensure_dom_tools() -> MCPDOMTools:
    """Обеспечивает инициализацию DOM анализатор инструментов"""
    global _dom_tools
    
    if _dom_tools is None:
        _dom_tools = MCPDOMTools()
        init_result = await _dom_tools.initialize()
        
        if not init_result.get('success'):
            raise Exception(f"Failed to initialize DOM tools: {init_result.get('error')}")
    
    return _dom_tools


# ============================================================================
# НОВЫЕ DOM АНАЛИЗАТОР ИНСТРУМЕНТЫ (в стиле browser-use)
# ============================================================================

@mcp.tool()
async def browser_get_state(include_screenshot: bool = False, target_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Get the current page state including all interactive elements with their indices. 
    Essential for interaction with web pages using DOM analyzer.
    
    Args:
        include_screenshot: Whether to include a screenshot of the page
        target_id: Target ID to get state for. If not provided, uses current target
    
    Returns:
        Dict containing page state with indexed interactive elements
    """
    try:
        dom_tools = await _ensure_dom_tools()
        result = await dom_tools.browser_get_state(
            include_screenshot=include_screenshot,
            target_id=target_id
        )
        return result
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
async def browser_click(index: int, target_id: Optional[str] = None, open_in_new_tab: bool = False) -> Dict[str, Any]:
    """
    Click on an element by its index from browser_get_state. 
    Supports opening links in new tabs.
    
    Args:
        index: Index of the element to click
        target_id: Target ID to click on. If not provided, uses current target
        open_in_new_tab: Whether to open link in new tab (for link elements)
    
    Returns:
        Dict containing click result information
    """
    try:
        dom_tools = await _ensure_dom_tools()
        result = await dom_tools.browser_click(
            index=index,
            target_id=target_id,
            open_in_new_tab=open_in_new_tab
        )
        return result
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
async def browser_type(index: int, text: str, target_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Type text into an input field identified by its index. 
    Use after browser_get_state to find inputs.
    
    Args:
        index: Index of the input element
        text: Text to type into the input field
        target_id: Target ID to type on. If not provided, uses current target
    
    Returns:
        Dict containing type result information
    """
    try:
        dom_tools = await _ensure_dom_tools()
        result = await dom_tools.browser_type(
            index=index,
            text=text,
            target_id=target_id
        )
        return result
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
async def browser_navigate_dom(url: str, target_id: Optional[str] = None, new_tab: bool = False) -> Dict[str, Any]:
    """
    Navigate to a URL in the current tab or open a new tab using DOM analyzer.
    Example: Navigate to https://example.com
    
    Args:
        url: URL to navigate to
        target_id: Target ID to navigate on. If not provided, uses current target
        new_tab: Whether to open in new tab
    
    Returns:
        Dict containing navigation result information
    """
    try:
        dom_tools = await _ensure_dom_tools()
        result = await dom_tools.browser_navigate(
            url=url,
            target_id=target_id,
            new_tab=new_tab
        )
        return result
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
async def browser_extract_content(extraction_prompt: str, target_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Extract structured content from the page using AI and DOM analyzer. 
    Perfect for scraping specific information.
    
    Args:
        extraction_prompt: AI prompt describing what content to extract
        target_id: Target ID to extract from. If not provided, uses current target
    
    Returns:
        Dict containing extracted content information
    """
    try:
        dom_tools = await _ensure_dom_tools()
        result = await dom_tools.browser_extract_content(
            extraction_prompt=extraction_prompt,
            target_id=target_id
        )
        return result
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
async def browser_scroll(direction: str = "down", target_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Scroll the page up or down by one viewport height using DOM analyzer.
    
    Args:
        direction: Direction to scroll ("up" or "down")
        target_id: Target ID to scroll. If not provided, uses current target
    
    Returns:
        Dict containing scroll result information
    """
    try:
        dom_tools = await _ensure_dom_tools()
        result = await dom_tools.browser_scroll(
            direction=direction,
            target_id=target_id
        )
        return result
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
async def browser_go_back(target_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Navigate back to the previous page in browser history using DOM analyzer.
    
    Args:
        target_id: Target ID to go back on. If not provided, uses current target
    
    Returns:
        Dict containing go back result information
    """
    try:
        dom_tools = await _ensure_dom_tools()
        result = await dom_tools.browser_go_back(target_id=target_id)
        return result
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
async def browser_list_tabs() -> Dict[str, Any]:
    """
    List all open browser tabs with their URLs and titles using DOM analyzer.
    
    Returns:
        Dict containing list of tabs information
    """
    try:
        dom_tools = await _ensure_dom_tools()
        result = await dom_tools.browser_list_tabs()
        return result
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
async def dom_analyzer_status() -> Dict[str, Any]:
    """
    Get status and statistics of DOM analyzer tools.
    
    Returns:
        Dict containing DOM analyzer status and usage statistics
    """
    try:
        dom_tools = await _ensure_dom_tools()
        stats = dom_tools.get_usage_stats()
        
        return {
            "success": True,
            "status": "active",
            "statistics": stats,
            "capabilities": [
                "browser_get_state",
                "browser_click", 
                "browser_type",
                "browser_navigate_dom",
                "browser_extract_content",
                "browser_scroll",
                "browser_go_back",
                "browser_list_tabs"
            ]
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


# ============================================================================
# СУЩЕСТВУЮЩИЕ ИНСТРУМЕНТЫ (сохранены для совместимости)
# ============================================================================

@mcp.tool()
async def browser_navigate(url: str, show_overlay: bool = False) -> Dict:
    """Open a URL in the browser (Playwright if available, otherwise stub). Optionally show numeric overlay."""
    if _use_playwright():
        await _BrowserSession.ensure_started()
        page = _BrowserSession.page()
        if page is None:
            return {"status": "error", "error": "browser_not_started"}
        try:
            resp = await page.goto(url, wait_until="load", timeout=20000)
            status = resp.status if resp else None
            if show_overlay:
                # prepare ids and overlay
                await _ensure_data_ids_all_frames(page)
                await _overlay_all_frames(page, scheme="high-contrast")
            # invalidate snapshot on navigation
            global _LAST_SNAPSHOT
            _LAST_SNAPSHOT = None
            return {"status": "ok", "url": url, "httpStatus": status}
        except Exception as e:  # fallback
            return {"status": "error", "error": str(e)}
    return stub_navigate(url)


@mcp.tool()
async def browser_close_banners(
    time_budget_ms: int = 1200,
    max_passes: int = 3,
    strategy: str = "safe",
    languages: Optional[List[str]] = None,
    return_details: bool = True,
) -> Dict:
    """Close cookie/consent/modals overlays across frames/shadow roots with a time budget."""
    # TODO: Реализовать полную логику существующего инструмента
    return {"status": "not_implemented", "message": "Legacy tool - use DOM analyzer tools instead"}


@mcp.tool()
async def browser_extract_summary() -> Dict:
    """Extract a summary of the current page content."""
    # TODO: Реализовать полную логику существующего инструмента
    return {"status": "not_implemented", "message": "Legacy tool - use browser_extract_content instead"}


@mcp.tool()
async def browser_download_wait() -> Dict:
    """Wait for browser downloads to complete."""
    # TODO: Реализовать полную логику существующего инструмента
    return {"status": "not_implemented", "message": "Legacy tool - use DOM analyzer tools instead"}


@mcp.tool()
async def browser_list_interactives() -> Dict:
    """List interactive elements on the current page with numeric IDs."""
    # TODO: Реализовать полную логику существующего инструмента
    return {"status": "not_implemented", "message": "Legacy tool - use browser_get_state instead"}


@mcp.tool()
async def browser_overlay_show(scheme: str = "high-contrast") -> Dict:
    """Show numeric overlay on interactive elements."""
    # TODO: Реализовать полную логику существующего инструмента
    return {"status": "not_implemented", "message": "Legacy tool - use DOM analyzer tools instead"}


@mcp.tool()
async def browser_overlay_act(id: int, action: str = "click") -> Dict:
    """Act on an element by its numeric ID from overlay."""
    # TODO: Реализовать полную логику существующего инструмента
    return {"status": "not_implemented", "message": "Legacy tool - use browser_click instead"}


@mcp.tool()
async def browser_click_selector(selector: str) -> Dict:
    """Click on an element using CSS selector."""
    # TODO: Реализовать полную логику существующего инструмента
    return {"status": "not_implemented", "message": "Legacy tool - use browser_click with index instead"}


@mcp.tool()
async def browser_type_selector(selector: str, text: str) -> Dict:
    """Type text into an element using CSS selector."""
    # TODO: Реализовать полную логику существующего инструмента
    return {"status": "not_implemented", "message": "Legacy tool - use browser_type with index instead"}


@mcp.tool()
async def browser_click_text(text: str) -> Dict:
    """Click on an element containing specific text."""
    # TODO: Реализовать полную логику существующего инструмента
    return {"status": "not_implemented", "message": "Legacy tool - use browser_click with index instead"}


@mcp.tool()
async def browser_type_text(text: str, input_text: str) -> Dict:
    """Type text into an input field containing specific text."""
    # TODO: Реализовать полную логику существующего инструмента
    return {"status": "not_implemented", "message": "Legacy tool - use browser_type with index instead"}


@mcp.tool()
async def browser_act_by_text(text: str, action: str = "click") -> Dict:
    """Perform an action on an element containing specific text."""
    # TODO: Реализовать полную логику существующего инструмента
    return {"status": "not_implemented", "message": "Legacy tool - use browser_click with index instead"}


@mcp.tool()
async def browser_click_by_text(text: str) -> Dict:
    """Click on an element containing specific text."""
    # TODO: Реализовать полную логику существующего инструмента
    return {"status": "not_implemented", "message": "Legacy tool - use browser_click with index instead"}


@mcp.tool()
async def browser_type_by_text(text: str, input_text: str) -> Dict:
    """Type text into an input field containing specific text."""
    # TODO: Реализовать полную логику существующего инструмента
    return {"status": "not_implemented", "message": "Legacy tool - use browser_type with index instead"}


@mcp.tool()
async def files_search(query: str, timeout_s: int = 10) -> Dict:
    """Search for files by name or content."""
    return stub_search_files(query)


@mcp.tool()
async def files_read_text(path: str, max_chars: int = 500, timeout_s: int = 8) -> Dict:
    """Read text file content."""
    return stub_read_text(path)


# ============================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ (заглушки для совместимости)
# ============================================================================

async def _ensure_data_ids_all_frames(page: Any) -> None:
    """Ensure data IDs are set for all frames (stub for compatibility)."""
    pass


async def _overlay_all_frames(page: Any, scheme: str) -> None:
    """Show overlay on all frames (stub for compatibility)."""
    pass


# ============================================================================
# ОСНОВНАЯ ФУНКЦИЯ
# ============================================================================

async def main():
    """Основная функция для запуска интегрированного MCP сервера"""
    print("🚀 Запуск интегрированного MCP сервера с DOM анализатором...")
    print("🔧 Доступные инструменты:")
    print("   📱 DOM Analyzer инструменты (новые):")
    print("     - browser_get_state: получение состояния страницы")
    print("     - browser_click: клик по элементам по индексу")
    print("     - browser_type: ввод текста в поля")
    print("     - browser_navigate_dom: навигация по URL")
    print("     - browser_extract_content: извлечение контента")
    print("     - browser_scroll: прокрутка страницы")
    print("     - browser_go_back: переход назад")
    print("     - browser_list_tabs: список вкладок")
    print("     - dom_analyzer_status: статус DOM анализатора")
    print("   🔄 Legacy инструменты (для совместимости):")
    print("     - browser_navigate: навигация (Playwright)")
    print("     - files_search: поиск файлов")
    print("     - files_read_text: чтение файлов")
    
    # Инициализируем DOM инструменты
    try:
        await _ensure_dom_tools()
        print("✅ DOM анализатор инструменты инициализированы")
    except Exception as e:
        print(f"⚠️  DOM анализатор инструменты не инициализированы: {e}")
        print("   Legacy инструменты будут работать, но DOM инструменты недоступны")
    
    print("\n🎯 MCP сервер готов к работе!")
    print("💡 Используйте DOM анализатор инструменты для современного взаимодействия с веб-страницами")


if __name__ == "__main__":
    # Запускаем MCP сервер в режиме stdio
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--stdio":
        # Режим stdio для MCP
        print("🚀 MCP сервер запущен в режиме stdio", file=sys.stderr)
        # Запускаем MCP сервер в stdio режиме
        import asyncio
        asyncio.run(mcp.run_stdio_async())
    else:
        # Информационный режим
        asyncio.run(main())
