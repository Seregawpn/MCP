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

from tools.browser_stub import navigate as stub_navigate, close_banners as stub_close_banners, extract_summary as stub_extract_summary
from tools.files_stub import search_files as stub_search_files, read_text_file as stub_read_text

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


mcp = FastMCP(name="Blind Assistant Core")


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
_LAST_ITEMS: Optional[List[Dict[str, Any]]] = None

# Deterministic snapshot of interactives for stable numbering
_LAST_SNAPSHOT: Optional[Dict[str, Any]] = None  # { id: str, ts: int, items: List[Dict] }

# Close banners profiles (loaded from config on startup, optional)
_CLOSE_BANNERS_PROFILES: Dict[str, Any] = {"global": {"texts": [], "selectors": []}, "domains": {}}


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
                "selectors": list(global_section.get("selectors", []) or []),
            },
            "domains": {k: {"selectors": list((v or {}).get("selectors", []) or [])} for k, v in (domains_section or {}).items()},
        }
    except Exception:
        # best-effort
        pass


def _get_domain_from_url(page_url: str) -> str:
    try:
        parsed = urlparse(page_url)
        host = (parsed.hostname or "").lower()
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return ""


async def _get_overlay_state(frame: "Frame") -> Dict[str, Any]:
    try:
        return await frame.evaluate(
            """
            () => {
              const dialogs = Array.from(document.querySelectorAll('[role="dialog"], [role="alertdialog"], [aria-modal="true"]'))
                .filter(el => !!(el.offsetWidth||el.offsetHeight||el.getClientRects().length)).length;
              const html = document.documentElement;
              const body = document.body;
              const htmlOverflow = html ? (getComputedStyle(html).overflow || html.style.overflow || '') : '';
              const bodyOverflow = body ? (getComputedStyle(body).overflow || body.style.overflow || '') : '';
              return { dialogs, htmlOverflow, bodyOverflow };
            }
            """
        )
    except Exception:
        return {"dialogs": None, "htmlOverflow": None, "bodyOverflow": None}


def _telemetry_path() -> str:
    base = _project_root()
    data_dir = os.path.join(base, "data")
    _ensure_dir(data_dir)
    return os.path.join(data_dir, "close_banners_candidates.jsonl")


def _log_candidate_success(record: Dict[str, Any]) -> None:
    try:
        path = _telemetry_path()
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass



def _use_playwright() -> bool:
    try:
        return async_playwright is not None
    except Exception:
        return False


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
    return stub_navigate(url, timeout_s=20)


@mcp.tool()
async def browser_close_banners(
    time_budget_ms: int = 1200,
    max_passes: int = 3,
    strategy: str = "safe",
    languages: Optional[List[str]] = None,
    return_details: bool = True,
) -> Dict:
    """Close cookie/consent/modals overlays across frames/shadow roots with a time budget.

    Args:
      time_budget_ms: overall time budget for this call (default 1200 ms)
      max_passes: how many scan passes to perform (default 3)
      strategy: 'safe' (default) avoids Reject/Deny; 'aggressive' may include
      languages: language hints to include text variants, e.g., ['en','ru']
      return_details: whether to include detailed clicks in response
    """
    if not _use_playwright():
        return stub_close_banners()
    await _BrowserSession.ensure_started()
    page = _BrowserSession.page()
    if page is None:
        return {"status": "error", "error": "browser_not_started"}

    # Detect page locale to augment languages if not explicitly provided
    langs_param = [s.lower() for s in (languages or [])]
    try:
        page_lang = None
        try:
            page_lang = await page.evaluate("() => (document.documentElement && document.documentElement.lang) || ''")
        except Exception:
            page_lang = None
        host = None
        try:
            from urllib.parse import urlparse as _urlparse
            host = (_urlparse(page.url).hostname or '').lower()
        except Exception:
            host = None
        inferred: List[str] = []
        if host and (host.endswith('.de') or '.de/' in page.url):
            inferred.append('de')
        if host and (host.endswith('.fr') or '.fr/' in page.url):
            inferred.append('fr')
        if isinstance(page_lang, str) and page_lang:
            inferred.append(page_lang.split('-')[0].lower())
    except Exception:
        inferred = []
    langs = list(dict.fromkeys([*(langs_param or []), *inferred, 'en', 'ru']))
    # Text variants for common CTAs
    texts_en = ["Accept", "Accept all", "I agree", "Agree", "OK", "Got it", "Close"]
    texts_ru = ["Принять", "Принять все", "Согласен", "Ок", "Хорошо", "Закрыть"]
    text_pool: List[str] = []
    if "en" in langs:
        text_pool.extend(texts_en)
    if "ru" in langs:
        text_pool.extend(texts_ru)
    # German (Amazon.de and many EU cookie banners)
    texts_de = ["Alle akzeptieren", "Akzeptieren", "Zustimmen", "OK", "Schließen"]
    if "de" in langs:
        text_pool.extend(texts_de)
    # French (common in EU)
    texts_fr = ["Tout accepter", "Accepter", "D'accord", "Fermer"]
    if "fr" in langs:
        text_pool.extend(texts_fr)

    # Load domain/global profiles (if any)
    try:
        _load_close_banners_profiles()
    except Exception:
        pass
    domain = _get_domain_from_url(page.url)
    domain_selectors: List[str] = []
    try:
        domain_selectors = list(((_CLOSE_BANNERS_PROFILES.get("domains", {}) or {}).get(domain, {}) or {}).get("selectors", []) or [])
    except Exception:
        domain_selectors = []
    global_selectors: List[str] = []
    try:
        global_selectors = list(((_CLOSE_BANNERS_PROFILES.get("global", {}) or {}).get("selectors", []) or []))
    except Exception:
        global_selectors = []

    # Base selectors and profiles. Use css:light(...) to pierce shadow DOM.
    selector_profiles: List[str] = [
        "#onetrust-accept-btn-handler",
        "button#onetrust-accept-btn-handler",
        "#truste-consent-button",
        "[data-testid*='consent' i] button",
        "[id*='consent' i] button",
        "[id*='cookie' i] button",
        "[class*='cookie' i] button",
        "button[aria-label*='accept' i]",
        "input[aria-label*='accept' i]",
        "[role='dialog'] button[aria-label*='accept' i]",
        "[role='dialog'] input[aria-label*='accept' i]",
        ".modal [aria-label='Close']",
        ".modal .close",
        "button[aria-label*='close' i]",
        "a[aria-label*='close' i]",
        # generic close/dismiss patterns
        "[class*='close' i]",
        "[class*='dismiss' i]",
        "[id*='close' i]",
        "[title*='close' i]",
        "[data-test*='close' i]",
        "[data-testid*='close' i]",
        "[role='button'][aria-label*='close' i]",
        # textual cross
        "button:has-text('×')",
        "button:has-text('✕')",
        "a:has-text('×')",
        "a:has-text('✕')",
    ]
    # Amazon-specific safe selectors (cookies/location popover)
    selector_profiles.extend([
        "#sp-cc-accept",
        "input#sp-cc-accept",
        "button#sp-cc-accept",
        "input[name='accept']",
        "input[name='sp-cc-accept']",
        "input[type='submit'][value*='accept' i]",
        "input[name='glowDoneButton']",
        "button[name='glowDoneButton']",
        "[data-action='a-popover-close']",
    ])
    # Add :has-text selectors for provided languages
    # Compose text-based selectors: from profiles (global texts) and built-ins
    prof_texts: List[str] = []
    try:
        prof_texts = list(((_CLOSE_BANNERS_PROFILES.get("global", {}) or {}).get("texts", []) or []))
    except Exception:
        prof_texts = []
    text_candidates = list(dict.fromkeys([*text_pool, *prof_texts, "Not now", "Don't Change", "Stay on Amazon.com", "No thanks"]))
    for t in text_candidates:
        # bare and inside dialogs
        selector_profiles.append(f"button:has-text('{t}')")
        selector_profiles.append(f"[role='dialog'] button:has-text('{t}')")

    # Prepend domain/global selectors to increase priority
    prioritized_profiles = [*domain_selectors, *global_selectors, *selector_profiles]

    # In safe strategy, avoid Reject/Deny texts. (No explicit reject selectors are added.)
    start = time.time()
    elapsed_ms = 0
    closed = 0
    details: List[Dict[str, Any]] = []
    max_clicks = 5

    try:
        passes = 0
        while passes < max_passes and elapsed_ms < time_budget_ms and closed < max_clicks:
            pass_start = time.time()
            for frame in page.frames:
                if elapsed_ms >= time_budget_ms or closed >= max_clicks:
                    break
                for sel in prioritized_profiles:
                    if elapsed_ms >= time_budget_ms or closed >= max_clicks:
                        break
                    try:
                        loc = frame.locator(f"css:light({sel})")
                        if await loc.count() > 0:
                            # capture before state
                            before = await _get_overlay_state(frame)
                            # Click the first visible candidate
                            await loc.first.click(timeout=800)
                            closed += 1
                            if return_details:
                                try:
                                    fr_url = frame.url
                                except Exception:
                                    fr_url = None
                                det = {
                                    "selector": sel,
                                    "frameUrl": fr_url,
                                    "ts": int(time.time() * 1000),
                                }
                            # small pause to allow DOM to update
                            await page.wait_for_timeout(120)
                            after = await _get_overlay_state(frame)
                            # Log success candidate if overlay likely closed
                            try:
                                record = {
                                    "type": "CandidateSuccess",
                                    "domain": domain,
                                    "lang": (await frame.evaluate("() => (document.documentElement && document.documentElement.lang) || ''")) or None,
                                    "frameUrl": fr_url,
                                    "cta": {
                                        "selector": sel,
                                    },
                                    "before": before,
                                    "after": after,
                                    "ts": int(time.time() * 1000),
                                }
                                _log_candidate_success(record)
                            except Exception:
                                pass
                            details.append(det)
                    except Exception:
                        continue
            passes += 1
            elapsed_ms = int((time.time() - start) * 1000)
            # guards
            if (time.time() - pass_start) * 1000 < 50:
                # tiny yield to event loop
                await asyncio.sleep(0)
        result: Dict[str, Any] = {"status": "ok", "closed": closed, "passes": passes, "elapsed_ms": elapsed_ms}
        if return_details:
            result["clicks"] = details
        return result
    except Exception as e:
        return {"status": "error", "error": str(e)}


@mcp.tool()
async def browser_extract_universal(
    mode: str = "adaptive",
    max_text_length: int = 5000,
    timeout_ms: int = 10000
) -> Dict:
    """100% адаптивное извлечение данных с любой страницы - работает со всеми сайтами"""
    if not _use_playwright():
        return {"status": "error", "error": "playwright_not_available"}
    await _BrowserSession.ensure_started()
    page = _BrowserSession.page()
    if page is None:
        return {"status": "error", "error": "browser_not_started"}
    
    try:
        # Дожидаемся готовности DOM
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
        except Exception:
            pass  # Продолжаем даже если DOM не готов
        
        # УНИВЕРСАЛЬНЫЙ JavaScript для извлечения данных с любого сайта
        script = r"""
        (() => {
          const results = {
            title: document.title || '',
            strategies: {},
            summary: '',
            metadata: {
              url: window.location.href,
              timestamp: new Date().toISOString(),
              userAgent: navigator.userAgent
            }
          };
          
          // Функция для очистки и нормализации текста
          const cleanText = (text) => {
            if (!text) return '';
            return text
              .replace(/\s+/g, ' ')
              .replace(/\n+/g, '\n')
              .trim()
              .slice(0, 1000);  // Ограничиваем длину каждого блока
          };
          
          // Функция для расчета важности элемента
          const calculateImportance = (element) => {
            let score = 0;
            
            // Проверяем размер элемента
            const rect = element.getBoundingClientRect();
            if (rect.width > 100 && rect.height > 30) score += 2;
            if (rect.width > 200 && rect.height > 50) score += 3;
            
            // Проверяем позицию (верх страницы важнее)
            if (rect.top < window.innerHeight * 0.5) score += 2;
            
            // Проверяем семантику
            const tag = element.tagName.toLowerCase();
            if (['h1', 'h2', 'h3', 'main', 'article'].includes(tag)) score += 3;
            if (['h4', 'h5', 'h6', 'section', 'aside'].includes(tag)) score += 2;
            if (['p', 'div', 'span'].includes(tag)) score += 1;
            
            // Проверяем ARIA атрибуты
            if (element.hasAttribute('aria-label')) score += 2;
            if (element.hasAttribute('role')) score += 1;
            
            return score;
          };
          
          // СТРАТЕГИЯ 1: Семантический анализ (ARIA, роли, атрибуты)
          const semanticExtract = () => {
            const elements = Array.from(document.querySelectorAll('*'));
            const textData = [];
            
            for (const el of elements) {
              const sources = [
                el.getAttribute('aria-label'),
                el.getAttribute('aria-describedby'),
                el.getAttribute('title'),
                el.getAttribute('placeholder'),
                el.getAttribute('alt'),
                el.getAttribute('data-text'),
                el.getAttribute('data-content'),
                el.getAttribute('data-testid'),
                el.getAttribute('data-test'),
                el.innerText,
                el.textContent
              ].filter(Boolean);
              
              if (sources.length > 0) {
                const text = sources.join(' ');
                if (text.length > 3) {
                  textData.push({
                    text: cleanText(text),
                    element: el.tagName,
                    importance: calculateImportance(el),
                    attributes: {
                      role: el.getAttribute('role'),
                      'aria-label': el.getAttribute('aria-label'),
                      class: el.className
                    }
                  });
                }
              }
            }
            
            return textData.sort((a, b) => b.importance - a.importance);
          };
          
          // СТРАТЕГИЯ 2: Обход всех текстовых узлов
          const textWalkerExtract = () => {
            const textNodes = [];
            const walker = document.createTreeWalker(
              document.body,
              NodeFilter.SHOW_TEXT,
              {
                acceptNode: (node) => {
                  const text = node.textContent.trim();
                  return text.length > 3 ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
                }
              }
            );
            
            let node;
            while (node = walker.nextNode()) {
              const text = cleanText(node.textContent);
              if (text) {
                textNodes.push({
                  text: text,
                  element: node.parentElement?.tagName || 'text',
                  importance: 1
                });
              }
            }
            
            return textNodes;
          };
          
          // СТРАТЕГИЯ 3: Анализ интерактивных элементов
          const interactiveExtract = () => {
            const selectors = [
              'button', 'a', 'input', 'textarea', 'select',
              '[role="button"]', '[role="link"]', '[role="textbox"]',
              '[tabindex]', '[onclick]', '[onchange]',
              '.btn', '.button', '.link', '.nav-item'
            ];
            
            const elements = document.querySelectorAll(selectors.join(','));
            const textData = [];
            
            for (const el of elements) {
              const text = cleanText(el.innerText || el.textContent || el.getAttribute('aria-label') || '');
              if (text) {
                textData.push({
                  text: text,
                  element: el.tagName,
                  importance: calculateImportance(el) + 2,  // Интерактивные элементы важнее
                  interactive: true,
                  type: el.type || el.getAttribute('role') || 'unknown'
                });
              }
            }
            
            return textData;
          };
          
          // СТРАТЕГИЯ 4: Анализ видимого контента
          const visibleExtract = () => {
            const visibleElements = [];
            const allElements = document.querySelectorAll('*');
            
            for (const el of allElements) {
              const rect = el.getBoundingClientRect();
              const style = window.getComputedStyle(el);
              
              // Проверяем видимость
              if (rect.width > 0 && rect.height > 0 && 
                  style.visibility !== 'hidden' && 
                  style.display !== 'none' &&
                  rect.top < window.innerHeight * 2) {  // В пределах 2 экранов
                
                const text = cleanText(el.innerText || el.textContent);
                if (text && text.length > 5) {
                  visibleElements.push({
                    text: text,
                    element: el.tagName,
                    importance: calculateImportance(el),
                    visible: true,
                    area: rect.width * rect.height
                  });
                }
              }
            }
            
            return visibleElements.sort((a, b) => b.area - a.area);
          };
          
          // СТРАТЕГИЯ 5: Fallback - анализ структуры страницы
          const structureExtract = () => {
            const structure = {
              headings: [],
              paragraphs: [],
              lists: [],
              forms: [],
              navigation: []
            };
            
            // Заголовки
            document.querySelectorAll('h1, h2, h3, h4, h5, h6, [role="heading"]').forEach(h => {
              const text = cleanText(h.innerText);
              if (text) structure.headings.push({ text, level: h.tagName.slice(1) });
            });
            
            // Параграфы
            document.querySelectorAll('p, .text, .content, .description').forEach(p => {
              const text = cleanText(p.innerText);
              if (text) structure.paragraphs.push({ text });
            });
            
            // Списки
            document.querySelectorAll('ul, ol, .list, .menu').forEach(list => {
              const items = Array.from(list.querySelectorAll('li, .item')).map(li => cleanText(li.innerText)).filter(Boolean);
              if (items.length > 0) structure.lists.push({ items });
            });
            
            // Формы
            document.querySelectorAll('form, .form, .search').forEach(form => {
              const inputs = Array.from(form.querySelectorAll('input, textarea, select')).map(input => {
                return {
                  type: input.type || input.tagName.toLowerCase(),
                  placeholder: input.placeholder || '',
                  label: input.getAttribute('aria-label') || ''
                };
              });
              if (inputs.length > 0) structure.forms.push({ inputs });
            });
            
            // Навигация
            document.querySelectorAll('nav, .nav, .navigation, .menu, .breadcrumb').forEach(nav => {
              const links = Array.from(nav.querySelectorAll('a, .link')).map(link => cleanText(link.innerText)).filter(Boolean);
              if (links.length > 0) structure.navigation.push({ links });
            });
            
            return structure;
          };
          
          // ВЫПОЛНЯЕМ ВСЕ СТРАТЕГИИ
          try {
            results.strategies.semantic = semanticExtract();
            results.strategies.textWalker = textWalkerExtract();
            results.strategies.interactive = interactiveExtract();
            results.strategies.visible = visibleExtract();
            results.strategies.structure = structureExtract();
          } catch (e) {
            console.error('Error in extraction strategies:', e);
          }
          
          // СОБИРАЕМ ИТОГОВЫЙ ТЕКСТ
          const allText = [];
          
          // Добавляем заголовки
          if (results.strategies.structure.headings) {
            results.strategies.structure.headings.forEach(h => allText.push(h.text));
          }
          
          // Добавляем важные элементы из семантического анализа
          if (results.strategies.semantic) {
            results.strategies.semantic.slice(0, 10).forEach(item => allText.push(item.text));
          }
          
          // Добавляем интерактивные элементы
          if (results.strategies.interactive) {
            results.strategies.interactive.slice(0, 8).forEach(item => allText.push(item.text));
          }
          
          // Добавляем видимый контент
          if (results.strategies.visible) {
            results.strategies.visible.slice(0, 12).forEach(item => allText.push(item.text));
          }
          
          // Убираем дубликаты и создаем итоговый текст
          const uniqueText = [...new Set(allText)];
          results.summary = uniqueText.join('\n\n').slice(0, 5000);
          
          // Статистика
          results.stats = {
            total_elements: document.querySelectorAll('*').length,
            text_blocks: uniqueText.length,
            strategies_used: Object.keys(results.strategies).length,
            total_text_length: results.summary.length
          };
          
          return results;
        })();
        """
        
        # Выполняем JavaScript с таймаутом
        res = await asyncio.wait_for(page.evaluate(script), timeout=timeout_ms / 1000)
        
        if isinstance(res, dict):
            return {
                "status": "ok",
                "title": res.get("title", ""),
                "summary": res.get("summary", ""),
                "url": res.get("metadata", {}).get("url", ""),
                "stats": res.get("stats", {}),
                "strategies_used": list(res.get("strategies", {}).keys()),
                "extraction_mode": mode,
                "timestamp": res.get("metadata", {}).get("timestamp", "")
            }
        else:
            return {"status": "error", "error": "invalid_javascript_result"}
            
    except asyncio.TimeoutError:
        return {"status": "error", "error": f"extraction_timeout_{timeout_ms}ms"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def _collect_interactives_js() -> str:
    # JavaScript that tags interactives with data-blind-id and returns list
    return r"""
(() => {
  const isVisible = (el) => {
    const rect = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    if (!rect || rect.width === 0 || rect.height === 0) return false;
    if (style.visibility === 'hidden' || style.display === 'none') return false;
    return true;
  };
  const selector = [
    'button',
    'a[href]',
    'input',
    'textarea',
    'select',
    '[role="button"]',
    '[role="link"]',
    '[role="textbox"]',
    '[tabindex]',
    '[contenteditable="true"]'
  ].join(',');
  const collectInRoot = (root, push) => {
    const nodes = Array.from(root.querySelectorAll(selector));
    for (const el of nodes) push(el);
    // traverse shadow roots
    const treeWalker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT);
    let node = treeWalker.currentNode;
    while (node) {
      const elem = node;
      if (elem.shadowRoot) {
        const sub = Array.from(elem.shadowRoot.querySelectorAll(selector));
        for (const el of sub) push(el);
      }
      node = treeWalker.nextNode();
    }
  };
  const candidates = [];
  collectInRoot(document, (el) => candidates.push(el));
  let idx = 0;
  const ts = Date.now();
  const items = [];
  const active = document.activeElement;
  for (const el of candidates) {
    if (!isVisible(el) || el.hasAttribute('disabled') || el.getAttribute('aria-hidden') === 'true') continue;
    const tag = (el.tagName || '').toLowerCase();
    const role = el.getAttribute('role') || (
      tag === 'a' ? 'link' :
      tag === 'button' ? 'button' :
      (tag === 'input' || tag === 'textarea' || el.isContentEditable) ? 'textbox' :
      tag === 'select' ? 'combobox' : 'generic'
    );
    const name = (el.getAttribute('aria-label') || el.getAttribute('name') || el.getAttribute('placeholder') || (el.innerText||el.textContent) || '').trim().replace(/\s+/g, ' ').slice(0, 120);
    const rect = el.getBoundingClientRect();
    let id = el.getAttribute('data-blind-id');
    if (!id) {
      id = `ba-${ts}-${(++idx)}`;
      try { el.setAttribute('data-blind-id', id); } catch (e) {}
    } else {
      idx += 1;
    }
    try { el.setAttribute('data-blind-role', role); } catch (e) {}
    const focused = (el === active) || (el.shadowRoot && el.shadowRoot.activeElement === el);
    items.push({ id, index: idx, role, name, focused, bbox: { x: rect.x, y: rect.y, width: rect.width, height: rect.height } });
    if (idx >= 500) break; // hard cap
  }
  return { total: items.length, items };
})()
"""


async def _ensure_data_ids_all_frames(page: "Page") -> None:
    # Ensure data-blind-id attributes exist in all frames
    for frame in page.frames:
        try:
            await frame.evaluate(_collect_interactives_js())
        except Exception:
            continue


async def _gather_interactives_all_frames(page: "Page") -> List[Dict[str, Any]]:
    all_items: List[Dict[str, Any]] = []
    for frame in page.frames:
        try:
            result = await frame.evaluate(_collect_interactives_js())
            items: List[Dict[str, Any]] = result.get("items", []) if isinstance(result, dict) else []
            all_items.extend(items)
        except Exception:
            continue
    return all_items


def _role_rank(role: str) -> int:
    order = {"button": 1, "link": 2, "textbox": 3, "combobox": 4, "generic": 5}
    return order.get((role or "").lower(), 99)


def _sort_key_for_item(frame_index: int, it: Dict[str, Any]) -> Any:
    bbox = it.get("bbox", {}) or {}
    y = int(round(float(bbox.get("y", 0))))
    x = int(round(float(bbox.get("x", 0))))
    role = (it.get("role") or "").lower()
    name = (it.get("name") or "").strip().lower()
    return (frame_index, y, x, _role_rank(role), name)


@mcp.tool()
async def browser_list_interactives(scope: str = "viewport", limit: int = 30, offset: int = 0, refresh: bool = False) -> Dict:
    """List interactive elements with numbered labels. Returns items with id/index/role/name/bbox."""
    if not _use_playwright():
        return {"status": "error", "error": "playwright_not_available"}
    await _BrowserSession.ensure_started()
    page = _BrowserSession.page()
    if page is None:
        return {"status": "error", "error": "browser_not_started"}
    try:
        global _LAST_SNAPSHOT, _LAST_ITEMS
        reused = False
        if not refresh and _LAST_SNAPSHOT and isinstance(_LAST_SNAPSHOT.get("items"), list):
            # reuse existing snapshot
            items = _LAST_SNAPSHOT["items"]
            reused = True
        else:
            # build new snapshot
            await _ensure_data_ids_all_frames(page)
            raw_items = await _gather_interactives_all_frames(page)
            # sort deterministically by frame order and geometry/role/name
            frame_to_index = {fr: idx for idx, fr in enumerate(page.frames)}
            items_with_keys: List[Dict[str, Any]] = []
            for it in raw_items:
                # find the frame index for item by probing back via id (best-effort)
                # we can't map element->frame cheaply here; approximate by using 0 for all
                key = _sort_key_for_item(0, it)
                items_with_keys.append({"key": key, "item": it})
            items_with_keys.sort(key=lambda k: k["key"])  # type: ignore
            items = [x["item"] for x in items_with_keys]
            _LAST_SNAPSHOT = {"id": f"snap-{int(time.time()*1000)}", "ts": int(time.time()*1000), "items": items[:]} 
        _LAST_ITEMS = items[:]
        total = len(items)
        start = max(0, int(offset))
        end = start + max(1, int(limit))
        sliced = items[start:end]
        for i, it in enumerate(sliced, start=1):
            it["index"] = i
        return {"status": "ok", "total": total, "limit": limit, "offset": offset, "reused_snapshot": reused, "snapshot_id": _LAST_SNAPSHOT.get("id") if _LAST_SNAPSHOT else None, "items": sliced}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@mcp.tool()
async def browser_act(id: str, action: str = "click", text: str | None = None) -> Dict:
    """Perform action on an interactive element by its id (from browser_list_interactives) across frames."""
    if not _use_playwright():
        return {"status": "error", "error": "playwright_not_available"}
    await _BrowserSession.ensure_started()
    page = _BrowserSession.page()
    if page is None:
        return {"status": "error", "error": "browser_not_started"}
    selector_light = f'css:light([data-blind-id="{id}"])'
    selector_plain = f'[data-blind-id="{id}"]'
    try:
        # try all frames
        for frame in page.frames:
            loc = frame.locator(selector_light)
            try:
                if await loc.count() > 0:
                    # ensure in view
                    try:
                        await loc.first.evaluate("el => el.scrollIntoView({block:'center', inline:'nearest'})")
                    except Exception:
                        pass
                    if action == "click":
                        await loc.first.click(timeout=8000)
                        return {"status": "ok", "performed": "click", "id": id}
                    if action == "type":
                        val = text or ""
                        try:
                            tag = await loc.evaluate("el => el.tagName.toLowerCase()")
                        except Exception:
                            tag = None
                        if tag in ("input", "textarea"):
                            await loc.fill(val, timeout=8000)
                        else:
                            await loc.focus()
                            await frame.keyboard.type(val)
                        return {"status": "ok", "performed": "type", "id": id, "textLen": len(val)}
                    if action == "select":
                        val = text or ""
                        try:
                            await loc.select_option(label=val)
                        except Exception:
                            try:
                                await loc.select_option(value=val)
                            except Exception:
                                continue
                        return {"status": "ok", "performed": "select", "id": id}
            except Exception:
                pass
            # Fallback without :light
            try:
                loc2 = frame.locator(selector_plain)
                if await loc2.count() > 0:
                    try:
                        await loc2.first.evaluate("el => el.scrollIntoView({block:'center', inline:'nearest'})")
                    except Exception:
                        pass
                    if action == "click":
                        await loc2.first.click(timeout=8000)
                        return {"status": "ok", "performed": "click", "id": id}
                    if action == "type":
                        val = text or ""
                        try:
                            tag = await loc2.evaluate("el => el.tagName.toLowerCase()")
                        except Exception:
                            tag = None
                        if tag in ("input", "textarea"):
                            await loc2.fill(val, timeout=8000)
                        else:
                            await loc2.focus()
                            await frame.keyboard.type(val)
                        return {"status": "ok", "performed": "type", "id": id, "textLen": len(val)}
                    if action == "select":
                        val = text or ""
                        try:
                            await loc2.select_option(label=val)
                        except Exception:
                            try:
                                await loc2.select_option(value=val)
                            except Exception:
                                continue
                        return {"status": "ok", "performed": "select", "id": id}
            except Exception:
                continue
        return {"status": "error", "error": "element_not_found"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def _overlay_js_create() -> str:
    return r"""
(() => {
  const prev = document.getElementById('ba-overlay');
  if (prev) prev.remove();
  const root = document.createElement('div');
  root.id = 'ba-overlay';
  root.setAttribute('aria-hidden', 'true');
  Object.assign(root.style, {
    position: 'absolute',
    left: '0px',
    top: '0px',
    width: `${Math.max(document.documentElement.scrollWidth, document.body.scrollWidth)}px`,
    height: `${Math.max(document.documentElement.scrollHeight, document.body.scrollHeight)}px`,
    pointerEvents: 'none',
    zIndex: '2147483647'
  });
  const style = document.getElementById('ba-overlay-style') || document.createElement('style');
  style.id = 'ba-overlay-style';
  style.textContent = `
    .ba-badge{position:absolute;display:inline-flex;align-items:center;justify-content:center;
      min-width:18px;height:18px;border-radius:9px;font:700 10px/1 -apple-system,system-ui,Segoe UI,Arial;
      background:#0a84ff;color:#fff;box-shadow:0 1px 3px rgba(0,0,0,.4);padding:1px 4px;text-shadow:0 1px 1px rgba(0,0,0,.4)}
    .ba-badge.hc{background:#000;color:#fff;border:2px solid #fff}
    .ba-box{position:absolute;border:2px solid transparent;border-radius:6px;pointer-events:none}
    /* role-colored scheme */
    .role-button{border-color:#0a84ff;background:rgba(10,132,255,.12)}
    .role-link{border-color:#8e44ad;background:rgba(142,68,173,.12)}
    .role-textbox{border-color:#2ecc71;background:rgba(46,204,113,.12)}
    .role-combobox{border-color:#16a085;background:rgba(22,160,133,.12)}
    .role-generic{border-color:#7f8c8d;background:rgba(127,140,141,.12)}
    /* high-contrast override */
    .hc-box{border-color:#fff;background:rgba(0,0,0,.35)}
  `;
  document.documentElement.appendChild(style);
  document.documentElement.appendChild(root);
  let count = 0;
  // track placed badge rectangles to avoid overlaps
  const placed = [];
  const vw = window.innerWidth + window.scrollX;
  const vh = window.innerHeight + window.scrollY;
  const els = document.querySelectorAll('[data-blind-id]');
  for (const el of els){
    const rect = el.getBoundingClientRect();
    if (rect.width===0 || rect.height===0) continue;
    const id = el.getAttribute('data-blind-id');
    if (!id) continue;
    const role = (el.getAttribute('data-blind-role')||'generic').toLowerCase();
    // highlight box
    const box = document.createElement('div');
    box.className = 'ba-box role-' + role;
    const x = Math.round(rect.left + window.scrollX);
    const y = Math.round(rect.top + window.scrollY);
    box.style.left = (x - 2) + 'px';
    box.style.top = (y - 2) + 'px';
    box.style.width = (Math.round(rect.width) + 4) + 'px';
    box.style.height = (Math.round(rect.height) + 4) + 'px';
    root.appendChild(box);
    const idx = (id.split('-').pop()) || '';
    const badge = document.createElement('div');
    badge.className = 'ba-badge';
    badge.textContent = idx;
    // compute candidate positions around element corners
    const right = Math.round(rect.right + window.scrollX);
    const bottom = Math.round(rect.bottom + window.scrollY);
    const candidates = [
      {x: Math.max(0, x - 8), y: Math.max(0, y - 10)},               // TL
      {x: Math.max(0, right - 18), y: Math.max(0, y - 10)},           // TR
      {x: Math.max(0, x - 8), y: Math.max(0, bottom - 18)},           // BL
      {x: Math.max(0, right - 18), y: Math.max(0, bottom - 18)},      // BR
    ];
    const bw = Math.max(18, 12 + Math.max(0, (idx.length - 1)) * 6);
    const bh = 18;
    const intersects = (ax, ay, aw, ah, b) => !(ax + aw <= b.x || b.x + b.w <= ax || ay + ah <= b.y || b.y + b.h <= ay);
    let pos = null;
    for (const c of candidates){
      const inView = (c.x >= 0 && c.y >= 0 && c.x + bw <= vw && c.y + bh <= vh);
      if (!inView) continue;
      if (placed.every(p => !intersects(c.x, c.y, bw, bh, p))){ pos = c; break; }
    }
    if (!pos){
      // simple vertical nudge to avoid pileups
      let base = candidates[0];
      for (let k=0; k<8; k++){
        const test = {x: base.x, y: Math.min(vh - bh, base.y + k*14)};
        if (placed.every(p => !intersects(test.x, test.y, bw, bh, p))){ pos = test; break; }
      }
    }
    if (!pos){ pos = candidates[0]; }
    badge.style.left = pos.x + 'px';
    badge.style.top = pos.y + 'px';
    root.appendChild(badge);
    placed.push({x: pos.x, y: pos.y, w: bw, h: bh});
    count++;
    if (count>=500) break;
  }
  return {created: count};
})()
"""


def _overlay_js_remove() -> str:
    return r"""
(() => {
  const root = document.getElementById('ba-overlay');
  if (root) { root.remove(); return {removed:true}; }
  return {removed:false};
})()
"""


async def _overlay_all_frames(page: "Page", scheme: str = "default") -> None:
    for frame in page.frames:
        try:
            await frame.evaluate(_overlay_js_create())
            if scheme == "high-contrast":
                await frame.evaluate(
                    """
                    (()=>{ const root=document.getElementById('ba-overlay'); if(!root) return; for(const n of root.children){ if(n.classList.contains('ba-badge')){ n.classList.add('hc'); } if(n.classList.contains('ba-box')){ n.classList.add('hc-box'); } } })()
                    """
                )
        except Exception:
            continue


@mcp.tool()
async def browser_overlay_show(scheme: str = "default") -> Dict:
    """Show visual numeric badges over interactive elements (for low-vision users)."""
    if not _use_playwright():
        return {"status": "error", "error": "playwright_not_available"}
    await _BrowserSession.ensure_started()
    page = _BrowserSession.page()
    if page is None:
        return {"status": "error", "error": "browser_not_started"}
    try:
        await _ensure_data_ids_all_frames(page)
        await _overlay_all_frames(page, scheme=scheme)
        return {"status": "ok", "created": None}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@mcp.tool()
async def browser_overlay_act(index: int, action: str = "click", text: str | None = None, limit: int = 50, offset: int = 0) -> Dict:
    """Perform action by visible numeric index (stable between overlay_show and nav)."""
    if not _use_playwright():
        return {"status": "error", "error": "playwright_not_available"}
    if index <= 0:
        return {"status": "error", "error": "invalid_index"}
    await _BrowserSession.ensure_started()
    page = _BrowserSession.page()
    if page is None:
        return {"status": "error", "error": "browser_not_started"}
    try:
        # Use last snapshot to keep numbering stable within the same view
        global _LAST_ITEMS, _LAST_SNAPSHOT
        items = _LAST_ITEMS
        if not items:
            # try reuse snapshot first
            if _LAST_SNAPSHOT and isinstance(_LAST_SNAPSHOT.get("items"), list):
                items = _LAST_SNAPSHOT["items"]
            else:
                await _ensure_data_ids_all_frames(page)
                items = await _gather_interactives_all_frames(page)
                _LAST_SNAPSHOT = {"id": f"snap-{int(time.time()*1000)}", "ts": int(time.time()*1000), "items": items[:]} 
        start = max(0, int(offset))
        end = start + max(1, int(limit))
        sliced = items[start:end]
        if index > len(sliced):
            return {"status": "error", "error": "index_out_of_range"}
        target = sliced[index - 1]
        target_id = target.get("id")
        if not target_id:
            return {"status": "error", "error": "no_id_for_element"}
        res = await browser_act(id=target_id, action=action, text=text)
        # if action likely changed DOM (click), we may invalidate snapshot
        try:
            if action == "click" and res.get("status") == "ok":
                _LAST_SNAPSHOT = None
        except Exception:
            pass
        return res
    except Exception as e:
        return {"status": "error", "error": str(e)}
@mcp.tool()
async def browser_overlay_hide() -> Dict:
    """Hide visual numeric badges if shown."""
    if not _use_playwright():
        return {"status": "error", "error": "playwright_not_available"}
    await _BrowserSession.ensure_started()
    page = _BrowserSession.page()
    if page is None:
        return {"status": "error", "error": "browser_not_started"}
    try:
        removed_any = False
        for frame in page.frames:
            try:
                res = await frame.evaluate(_overlay_js_remove())
                removed_any = removed_any or (res.get("removed", False) if isinstance(res, dict) else False)
            except Exception:
                continue
        return {"status": "ok", "removed": removed_any}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@mcp.tool()
async def browser_scroll(to: Optional[str] = None, by_x: int = 0, by_y: int = 0, element_id: Optional[str] = None, behavior: str = "auto") -> Dict:
    """Scroll page: to=top|bottom|elementId, or by deltas."""
    if not _use_playwright():
        return {"status": "error", "error": "playwright_not_available"}
    await _BrowserSession.ensure_started()
    page = _BrowserSession.page()
    if page is None:
        return {"status": "error", "error": "browser_not_started"}
    try:
        if to == "top":
            await page.evaluate("(b)=>window.scrollTo({top:0, behavior:b});", behavior)
        elif to == "bottom":
            await page.evaluate("(b)=>window.scrollTo({top:document.body.scrollHeight, behavior:b});", behavior)
        elif to == "elementId" and element_id:
            loc = page.locator(f'[data-blind-id="{element_id}"]').first
            handle = await loc.element_handle()
            if handle is None:
                return {"status": "error", "error": "element_not_found"}
            await page.evaluate("(el,b)=>el.scrollIntoView({behavior:b||'auto', block:'center'})", handle, behavior)
        elif by_x or by_y:
            await page.evaluate("(v)=>window.scrollBy(v.dx, v.dy);", {"dx": by_x, "dy": by_y})
        else:
            return {"status": "error", "error": "no_scroll_params"}
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@mcp.tool()
async def browser_wait(selector: Optional[str] = None, state: str = "visible", network_idle: bool = False, ms: int = 0) -> Dict:
    """Wait for selector/state, network idle, or timeout in ms."""
    if not _use_playwright():
        return {"status": "error", "error": "playwright_not_available"}
    await _BrowserSession.ensure_started()
    page = _BrowserSession.page()
    if page is None:
        return {"status": "error", "error": "browser_not_started"}
    try:
        waited = False
        if selector:
            s_state = {
                "visible": "visible",
                "attached": "attached",
                "hidden": "hidden",
                "detached": "detached",
            }.get(state, "visible")
            # try top frame, then all frames; shadow handled via :light selector engine
            try:
                await page.wait_for_selector(selector, state=s_state, timeout=8000)
                waited = True
            except Exception:
                for frame in page.frames:
                    try:
                        await frame.wait_for_selector(selector, state=s_state, timeout=4000)
                        waited = True
                        break
                    except Exception:
                        continue
        if network_idle:
            await page.wait_for_load_state("networkidle")
            waited = True
        if ms and ms > 0:
            await page.wait_for_timeout(ms)
            waited = True
        return {"status": "ok", "waited": waited}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@mcp.tool()
async def browser_back() -> Dict:
    if not _use_playwright():
        return {"status": "error", "error": "playwright_not_available"}
    await _BrowserSession.ensure_started()
    page = _BrowserSession.page()
    if page is None:
        return {"status": "error", "error": "browser_not_started"}
    try:
        await page.go_back()
        # invalidate snapshot
        global _LAST_SNAPSHOT
        _LAST_SNAPSHOT = None
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@mcp.tool()
async def browser_forward() -> Dict:
    if not _use_playwright():
        return {"status": "error", "error": "playwright_not_available"}
    await _BrowserSession.ensure_started()
    page = _BrowserSession.page()
    if page is None:
        return {"status": "error", "error": "browser_not_started"}
    try:
        await page.go_forward()
        global _LAST_SNAPSHOT
        _LAST_SNAPSHOT = None
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@mcp.tool()
async def browser_reload() -> Dict:
    if not _use_playwright():
        return {"status": "error", "error": "playwright_not_available"}
    await _BrowserSession.ensure_started()
    page = _BrowserSession.page()
    if page is None:
        return {"status": "error", "error": "browser_not_started"}
    try:
        await page.reload()
        global _LAST_SNAPSHOT
        _LAST_SNAPSHOT = None
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@mcp.tool()
async def browser_press(id: Optional[str] = None, key: str = "Enter") -> Dict:
    if not _use_playwright():
        return {"status": "error", "error": "playwright_not_available"}
    await _BrowserSession.ensure_started()
    page = _BrowserSession.page()
    if page is None:
        return {"status": "error", "error": "browser_not_started"}
    try:
        if id:
            loc = page.locator(f'[data-blind-id="{id}"]').first
            await loc.focus()
            await loc.press(key)
        else:
            await page.keyboard.press(key)
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@mcp.tool()
async def browser_open_in_new_tab(id: str) -> Dict:
    if not _use_playwright():
        return {"status": "error", "error": "playwright_not_available"}
    await _BrowserSession.ensure_started()
    page = _BrowserSession.page()
    if page is None:
        return {"status": "error", "error": "browser_not_started"}
    try:
        sel = f'[data-blind-id="{id}"]'
        loc = page.locator(sel).first
        handle = await loc.element_handle()
        href = None
        if handle is not None:
            try:
                href = await handle.get_attribute('href')
            except Exception:
                href = None
        if href:
            newp = await page.context.new_page()
            resp = await newp.goto(href)
            idx = len(page.context.pages) - 1
            return {"status": "ok", "tabIndex": idx, "title": await newp.title(), "httpStatus": (resp.status if resp else None)}
        # fallback: попытаться кликнуть с Cmd/Meta (macOS) для открытия в новой вкладке
        try:
            await loc.click(modifiers=["Meta"])  # Cmd-клик
            pages = page.context.pages
            target = pages[-1] if pages else None
            if target and target != page:
                await target.wait_for_load_state("domcontentloaded")
                return {"status": "ok", "tabIndex": len(pages)-1, "title": await target.title()}
        except Exception:
            pass
        return {"status": "error", "error": "no_href_and_fallback_failed"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@mcp.tool()
async def browser_switch_tab(index: Optional[int] = None, title_contains: Optional[str] = None) -> Dict:
    if not _use_playwright():
        return {"status": "error", "error": "playwright_not_available"}
    await _BrowserSession.ensure_started()
    page = _BrowserSession.page()
    if page is None:
        return {"status": "error", "error": "browser_not_started"}
    try:
        pages = page.context.pages
        target = None
        if index is not None and 0 <= index < len(pages):
            target = pages[index]
        elif title_contains:
            for p in pages:
                if title_contains.lower() in (await p.title()).lower():
                    target = p
                    break
        if not target:
            return {"status": "error", "error": "tab_not_found"}
        await target.bring_to_front()
        return {"status": "ok", "title": await target.title()}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@mcp.tool()
async def browser_upload(id: str, files: List[str]) -> Dict:
    if not _use_playwright():
        return {"status": "error", "error": "playwright_not_available"}
    await _BrowserSession.ensure_started()
    page = _BrowserSession.page()
    if page is None:
        return {"status": "error", "error": "browser_not_started"}
    try:
        loc = page.locator(f'[data-blind-id="{id}"]').first
        await loc.set_input_files(files)
        return {"status": "ok", "uploaded": len(files)}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@mcp.tool()
async def browser_find(role: Optional[str] = None, text: Optional[str] = None, limit: int = 50, offset: int = 0) -> Dict:
    if not _use_playwright():
        return {"status": "error", "error": "playwright_not_available"}
    await _BrowserSession.ensure_started()
    page = _BrowserSession.page()
    if page is None:
        return {"status": "error", "error": "browser_not_started"}
    try:
        items = await _gather_interactives_all_frames(page)
        start = max(0, int(offset))
        end = start + max(1, int(limit))
        sliced = items[start:end]
        text_l = (text or "").lower()
        role_l = (role or "").lower()
        results: List[Dict[str, Any]] = []
        for it in sliced:
            if role and (it.get("role") or "").lower() != role_l:
                continue
            name = (it.get("name") or "").lower()
            if text and text_l not in name:
                continue
            results.append({"id": it.get("id"), "index": it.get("index"), "role": it.get("role"), "name": it.get("name")})
        return {"status": "ok", "total": len(results), "items": results}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@mcp.tool()
async def browser_focus_next(role: Optional[str] = None) -> Dict:
    if not _use_playwright():
        return {"status": "error", "error": "playwright_not_available"}
    await _BrowserSession.ensure_started()
    page = _BrowserSession.page()
    if page is None:
        return {"status": "error", "error": "browser_not_started"}
    try:
        await page.keyboard.press("Tab")
        if role:
            # naive filter: loop small times to match role by inspecting interactives near focus
            for _ in range(20):
                items = await _gather_interactives_all_frames(page)
                focused = [it for it in items if it.get("focused")]
                if any((it.get("role") or "").lower() == role.lower() for it in focused):
                    break
                await page.keyboard.press("Tab")
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@mcp.tool()
async def browser_focus_prev(role: Optional[str] = None) -> Dict:
    if not _use_playwright():
        return {"status": "error", "error": "playwright_not_available"}
    await _BrowserSession.ensure_started()
    page = _BrowserSession.page()
    if page is None:
        return {"status": "error", "error": "browser_not_started"}
    try:
        await page.keyboard.down("Shift")
        await page.keyboard.press("Tab")
        await page.keyboard.up("Shift")
        if role:
            for _ in range(20):
                items = await _gather_interactives_all_frames(page)
                focused = [it for it in items if it.get("focused")]
                if any((it.get("role") or "").lower() == role.lower() for it in focused):
                    break
                await page.keyboard.down("Shift")
                await page.keyboard.press("Tab")
                await page.keyboard.up("Shift")
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@mcp.tool()
async def browser_download_wait(timeout_ms: int = 30000) -> Dict:
    if not _use_playwright():
        return {"status": "error", "error": "playwright_not_available"}
    await _BrowserSession.ensure_started()
    page = _BrowserSession.page()
    if page is None:
        return {"status": "error", "error": "browser_not_started"}
    try:
        # Playwright download event
        async with page.expect_download(timeout=timeout_ms) as info:
            download = await info.value
        path = await download.path()
        suggested = download.suggested_filename
        out_path = path or os.path.join(tempfile.gettempdir(), suggested)
        if path is None:
            await download.save_as(out_path)
        return {"status": "ok", "path": str(out_path), "filename": suggested}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@mcp.tool()
async def browser_screenshot(full_page: bool = False) -> Dict:
    """Take a screenshot and return local file path."""
    if not _use_playwright():
        return {"status": "error", "error": "playwright_not_available"}
    await _BrowserSession.ensure_started()
    page = _BrowserSession.page()
    if page is None:
        return {"status": "error", "error": "browser_not_started"}
    try:
        out_dir = os.path.join(tempfile.gettempdir(), "ba-shots")
        os.makedirs(out_dir, exist_ok=True)
        filename = f"shot-{int(time.time()*1000)}.png"
        path = os.path.join(out_dir, filename)
        await page.screenshot(path=path, full_page=bool(full_page))
        return {"status": "ok", "path": path}
    except Exception as e:
        return {"status": "error", "error": str(e)}
@mcp.tool()
async def browser_click_and_wait_download(id: str, timeout_ms: int = 30000) -> Dict:
    if not _use_playwright():
        return {"status": "error", "error": "playwright_not_available"}
    await _BrowserSession.ensure_started()
    page = _BrowserSession.page()
    if page is None:
        return {"status": "error", "error": "browser_not_started"}
    try:
        await _ensure_data_ids_all_frames(page)
        selector = f'css:light([data-blind-id="{id}"])'
        # Try to read href for fallback
        loc_tmp = page.locator(selector).first
        href_abs: Optional[str] = None
        try:
            href = await loc_tmp.get_attribute("href")
            if href:
                from urllib.parse import urljoin
                href_abs = urljoin(page.url, href)
        except Exception:
            href_abs = None
        async with page.expect_download(timeout=timeout_ms) as info:
            loc = page.locator(selector).first
            try:
                await loc.evaluate("el => el.scrollIntoView({block:'center', inline:'nearest'})")
            except Exception:
                pass
            await loc.click(timeout=8000)
        download = await info.value
        path = await download.path()
        suggested = download.suggested_filename
        out_path = path or os.path.join(tempfile.gettempdir(), suggested)
        if path is None:
            await download.save_as(out_path)
        return {"status": "ok", "path": str(out_path), "filename": suggested}
    except Exception as e:
        # Fallback: if we have href, try direct HTTP download
        try:
            if 'href_abs' in locals() and href_abs:
                import requests
                import os as _os
                import tempfile as _tmp
                suggested = _os.path.basename(href_abs.split('?')[0]) or f"download-{int(time.time()*1000)}"
                out_path = _os.path.join(_tmp.gettempdir(), suggested)
                resp = requests.get(href_abs, timeout=max(5, int(timeout_ms/1000)), stream=True)
                resp.raise_for_status()
                with open(out_path, 'wb') as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                return {"status": "ok", "path": str(out_path), "filename": suggested, "fallback": True}
        except Exception as ef:
            return {"status": "error", "error": f"{str(e)}; fallback_failed: {str(ef)}"}
        return {"status": "error", "error": str(e)}
@mcp.tool()
async def browser_act_by_index(index: int, action: str = "click", text: str | None = None, limit: int = 50, offset: int = 0) -> Dict:
    """Perform action on the N-th interactive element (1-based index within the current slice)."""
    if not _use_playwright():
        return {"status": "error", "error": "playwright_not_available"}
    if index <= 0:
        return {"status": "error", "error": "invalid_index"}
    await _BrowserSession.ensure_started()
    page = _BrowserSession.page()
    if page is None:
        return {"status": "error", "error": "browser_not_started"}
    try:
        items = await _gather_interactives_all_frames(page)
        start = max(0, int(offset))
        end = start + max(1, int(limit))
        sliced = items[start:end]
        if index > len(sliced):
            return {"status": "error", "error": "index_out_of_range"}
        target = sliced[index - 1]
        target_id = target.get("id")
        if not target_id:
            return {"status": "error", "error": "no_id_for_element"}
        # delegate to act by id
        return await browser_act(id=target_id, action=action, text=text)
    except Exception as e:
        return {"status": "error", "error": str(e)}


@mcp.tool()
def files_search(query: str) -> Dict:
    """Search local files by name fragment (stub)."""
    return stub_search_files(query, timeout_s=10)


@mcp.tool()
def files_read_text(path: str, max_chars: int = 500) -> Dict:
    """Read first N chars of a text file (stub)."""
    return stub_read_text(path, max_chars=max_chars, timeout_s=8)


@mcp.tool()
async def browser_wait_for_element(selector: str, timeout_ms: int = 10000) -> Dict:
    """Ждать появления элемента по селектору."""
    if not _use_playwright():
        return {"status": "error", "error": "playwright_not_available"}
    await _BrowserSession.ensure_started()
    page = _BrowserSession.page()
    if page is None:
        return {"status": "error", "error": "browser_not_started"}
    try:
        await page.wait_for_selector(selector, timeout=timeout_ms)
        return {"status": "ok", "element_found": True, "selector": selector}
    except Exception as e:
        return {"status": "error", "error": str(e), "selector": selector}


@mcp.tool()
async def browser_click_text(text: str) -> Dict:
    """Кликнуть по элементу с указанным текстом."""
    if not _use_playwright():
        return {"status": "error", "error": "playwright_not_available"}
    await _BrowserSession.ensure_started()
    page = _BrowserSession.page()
    if page is None:
        return {"status": "error", "error": "browser_not_started"}
    try:
        # Стратегия 1: Ищем элемент по точному тексту
        try:
            locator = page.get_by_text(text)
            element = locator.first
            if element and await element.is_visible():
                await element.click(timeout=5000)
                return {"status": "ok", "action": "clicked", "text": text, "method": "exact_text"}
        except Exception as e:
            print(f"DEBUG: Ошибка точного поиска: {e}")
        
        # Стратегия 2: Ищем по частичному совпадению
        try:
            locator = page.get_by_text(text, exact=False)
            element = locator.first
            if element and await element.is_visible():
                await element.click(timeout=5000)
                return {"status": "ok", "action": "clicked", "text": text, "method": "partial_text"}
        except Exception as e:
            print(f"DEBUG: Ошибка частичного поиска: {e}")
        
        # Стратегия 3: Ищем по aria-label
        try:
            locator = page.get_by_role("button").filter(has_text=text)
            element = locator.first
            if element and await element.is_visible():
                await element.click(timeout=5000)
                return {"status": "ok", "action": "clicked", "text": text, "method": "aria_button"}
        except Exception as e:
            print(f"DEBUG: Ошибка aria поиска: {e}")
        
        # Стратегия 4: Ищем по любому кликабельному элементу
        try:
            # Ищем все элементы с текстом
            elements = page.locator(f'*:has-text("{text}")').all()
            for element in elements[:5]:  # Проверяем первые 5
                try:
                    if await element.is_visible() and await element.is_enabled():
                        # Проверяем что элемент кликабельный
                        tag = await element.evaluate("el => el.tagName.toLowerCase()")
                        if tag in ['button', 'a', 'input', 'div', 'span']:
                            await element.click(timeout=5000)
                            return {"status": "ok", "action": "clicked", "text": text, "method": "generic_search"}
                except Exception as e:
                    continue
        except Exception as e:
            print(f"DEBUG: Ошибка generic поиска: {e}")
        
        # Стратегия 5: JavaScript клик (последний рубеж)
        try:
            result = await page.evaluate(f"""
                () => {{
                    const elements = Array.from(document.querySelectorAll('*'));
                    for (const el of elements) {{
                        if (el.textContent && el.textContent.includes('{text}') && 
                            (el.tagName === 'BUTTON' || el.tagName === 'A' || 
                             el.tagName === 'INPUT' || el.tagName === 'DIV' || 
                             el.tagName === 'SPAN')) {{
                            if (el.offsetWidth > 0 && el.offsetHeight > 0) {{
                                el.click();
                                return true;
                            }}
                        }}
                    }}
                    return false;
                }}
            """)
            if result:
                return {"status": "ok", "action": "clicked", "text": text, "method": "javascript_click"}
        except Exception as e:
            print(f"DEBUG: Ошибка JavaScript клика: {e}")
        
        return {"status": "error", "error": "element_not_found", "text": text, "tried_methods": ["exact", "partial", "aria", "generic", "javascript"]}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@mcp.tool()
async def browser_type_text(field: str, text: str) -> Dict:
    """Ввести текст в поле по описанию."""
    if not _use_playwright():
        return {"status": "error", "error": "playwright_not_available"}
    await _BrowserSession.ensure_started()
    page = _BrowserSession.page()
    if page is None:
        return {"status": "error", "error": "browser_not_started"}
    try:
        # Ищем поле по описанию (placeholder, label, aria-label)
        element = None
        
        # 1. Ищем по placeholder
        locator = page.get_by_placeholder(field)
        element = locator.first
        
        # 2. Если не найдено - ищем по aria-label
        if not element:
            locator = page.get_by_role("textbox").filter(has_text=field)
            element = locator.first
        
        # 3. Если не найдено - ищем по label
        if not element:
            locator = page.get_by_label(field)
            element = locator.first
        
        # 4. Если не найдено - ищем по тексту рядом
        if not element:
            locator = page.get_by_text(field)
            element = locator.first
        
        # 5. Если не найдено - ищем по name атрибуту
        if not element:
            locator = page.locator(f'input[name*="{field}"]')
            element = locator.first
        
        # 6. Если не найдено - ищем по id атрибуту
        if not element:
            locator = page.locator(f'input[id*="{field}"]')
            element = locator.first
        
        if element:
            await element.fill(text, timeout=5000)
            return {"status": "ok", "action": "typed", "field": field, "text": text}
        
        return {"status": "error", "error": "field_not_found", "field": field}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@mcp.tool()
async def browser_click_selector(selector: str) -> Dict:
    """Кликнуть по элементу по CSS селектору."""
    if not _use_playwright():
        return {"status": "error", "error": "playwright_not_available"}
    await _BrowserSession.ensure_started()
    page = _BrowserSession.page()
    if page is None:
        return {"status": "error", "error": "browser_not_started"}
    try:
        # Стратегия 1: Ждем элемент с таймаутом
        try:
            await page.wait_for_selector(selector, timeout=10000)
        except:
            pass  # Продолжаем без ожидания
        
        # Стратегия 2: Ищем элемент
        locator = page.locator(selector)
        element = locator.first
        
        # Стратегия 3: Если не найден - пробуем альтернативные селекторы
        if not element:
            # Попробуем найти по частичному совпадению
            alt_selectors = [
                selector.replace('input[', 'input[type="text"]['),
                selector.replace('input[', 'input[type="submit"]['),
                selector.replace('input[', 'input[type="button"]['),
                selector.replace('input[', 'button['),
                selector.replace('input[', 'a[')
            ]
            
            for alt_selector in alt_selectors:
                try:
                    alt_locator = page.locator(alt_selector)
                    element = alt_locator.first
                    if element:
                        break
                except:
                    continue
        
        if element and await element.is_visible() and await element.is_enabled():
            await element.click(timeout=5000)
            return {"status": "ok", "action": "clicked", "selector": selector, "method": "selector_click"}
        else:
            # Стратегия 4: JavaScript клик (последний рубеж)
            try:
                result = await page.evaluate(f"""
                    () => {{
                        const element = document.querySelector('{selector}');
                        if (element && element.offsetWidth > 0 && element.offsetHeight > 0) {{
                            element.click();
                            return true;
                        }}
                        return false;
                    }}
                """)
                if result:
                    return {"status": "ok", "action": "clicked", "selector": selector, "method": "javascript_click"}
            except Exception as e:
                print(f"DEBUG: Ошибка JavaScript клика: {e}")
            
            return {"status": "error", "error": "element_not_found_or_not_clickable", "selector": selector}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@mcp.tool()
async def browser_type_selector(selector: str, text: str) -> Dict:
    """Ввести текст в элемент по CSS селектору."""
    if not _use_playwright():
        return {"status": "error", "error": "playwright_not_available"}
    await _BrowserSession.ensure_started()
    page = _BrowserSession.page()
    if page is None:
        return {"status": "error", "error": "browser_not_started"}
    try:
        # Стратегия 1: Ждем элемент с таймаутом
        try:
            await page.wait_for_selector(selector, timeout=10000)
        except:
            pass  # Продолжаем без ожидания
        
        # Стратегия 2: Ищем элемент
        locator = page.locator(selector)
        element = locator.first
        
        # Стратегия 3: Если не найден - пробуем альтернативные селекторы
        if not element:
            # Попробуем найти по частичному совпадению
            alt_selectors = [
                selector.replace('input[', 'input[type="text"]['),
                selector.replace('input[', 'textarea['),
                selector.replace('input[', 'div[contenteditable="true"]['),
                selector.replace('input[', 'span[contenteditable="true"][')
            ]
            
            for alt_selector in alt_selectors:
                try:
                    alt_locator = page.locator(alt_selector)
                    element = alt_locator.first
                    if element:
                        break
                except:
                    continue
        
        if element:
            await element.fill(text, timeout=5000)
            return {"status": "ok", "action": "typed", "selector": selector, "text": text}
        else:
            return {"status": "error", "error": "element_not_found", "selector": selector}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@mcp.tool()
async def browser_extract(mode: str = "summary") -> Dict:
    """Алиас для browser_extract_universal - обратная совместимость"""
    return await browser_extract_universal(mode="adaptive", max_text_length=3000, timeout_ms=8000)


@mcp.tool()
async def browser_check_page_state() -> Dict:
    """Проверить состояние страницы для диагностики проблем с кликами."""
    if not _use_playwright():
        return {"status": "error", "error": "playwright_not_available"}
    await _BrowserSession.ensure_started()
    page = _BrowserSession.page()
    if page is None:
        return {"status": "error", "error": "browser_not_started"}
    try:
        # Получаем информацию о странице
        url = page.url
        title = await page.title()
        
        # Проверяем состояние DOM
        dom_state = await page.evaluate("""
            () => {
                return {
                    readyState: document.readyState,
                    hasBody: !!document.body,
                    bodyChildren: document.body ? document.body.children.length : 0,
                    scripts: document.scripts.length,
                    stylesheets: document.styleSheets.length,
                    hasErrors: !!document.querySelector('.error, .error-message, [data-error]'),
                    isLoaded: document.readyState === 'complete'
                }
            }
        """)
        
        # Проверяем видимые элементы
        visible_elements = await page.evaluate("""
            () => {
                const elements = Array.from(document.querySelectorAll('*'));
                const visible = elements.filter(el => {
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return rect.width > 0 && rect.height > 0 && 
                           style.visibility !== 'hidden' && 
                           style.display !== 'none';
                });
                
                return {
                    total: elements.length,
                    visible: visible.length,
                    buttons: visible.filter(el => el.tagName === 'BUTTON').length,
                    links: visible.filter(el => el.tagName === 'A').length,
                    inputs: visible.filter(el => el.tagName === 'INPUT').length,
                    clickable: visible.filter(el => {
                        const tag = el.tagName.toLowerCase();
                        return tag === 'button' || tag === 'a' || 
                               tag === 'input' || el.onclick || 
                               el.getAttribute('role') === 'button';
                    }).length
                }
            }
        """)
        
        # Проверяем JavaScript ошибки
        js_errors = await page.evaluate("""
            () => {
                if (window.jsErrors) {
                    return window.jsErrors;
                }
                return [];
            }
        """)
        
        return {
            "status": "ok",
            "url": url,
            "title": title,
            "dom_state": dom_state,
            "visible_elements": visible_elements,
            "js_errors": js_errors,
            "timestamp": time.time()
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


if __name__ == "__main__":
    # Direct execution mode; for development you can also run: `mcp dev mcp_server.py`
    mcp.run()
