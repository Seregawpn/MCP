import argparse
import asyncio
import base64
import json
import os
import re
import sys
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

# MCP client
from mcp import ClientSession, StdioServerParameters  # type: ignore
from mcp.client.stdio import stdio_client  # type: ignore


RUNS_DIR = os.path.join(os.path.dirname(__file__), "agent_runs")
DOCS_DIR = os.path.join(os.path.dirname(__file__), "docs")

# Константы для нумерации элементов
ITEMS_LIMIT = 120  # Единый лимит для всех вызовов нумерации


def _now_iso() -> str:
  # timezone-aware would be better, but keep consistent with mbp0
  return datetime.utcnow().isoformat() + "Z"


def _ensure_dir(path: str) -> None:
  os.makedirs(path, exist_ok=True)


def write_event(run_dir: str, event: Dict[str, Any]) -> None:
  _ensure_dir(run_dir)
  events_path = os.path.join(run_dir, "steps.jsonl")
  with open(events_path, "a", encoding="utf-8") as f:
    f.write(json.dumps(event, ensure_ascii=False) + "\n")


def write_meta(run_dir: str, meta: Dict[str, Any]) -> None:
  _ensure_dir(run_dir)
  meta_path = os.path.join(run_dir, "meta.json")
  with open(meta_path, "w", encoding="utf-8") as f:
    json.dump(meta, f, ensure_ascii=False, indent=2)


def write_text(run_dir: str, filename: str, content: str) -> str:
  _ensure_dir(run_dir)
  path = os.path.join(run_dir, filename)
  with open(path, "w", encoding="utf-8") as f:
    f.write(content)
  return path


def load_system_prompt() -> str:
  path = os.path.join(DOCS_DIR, "SYSTEM_PROMPT_Браузерный ассистент.md")
  if not os.path.exists(path):
    return ""
  with open(path, "r", encoding="utf-8") as f:
    return f.read()


def try_import_gemini():
  try:
    from google import genai  # type: ignore
    return genai
  except Exception:
    return None


def build_llm_input(goal: str, step_summary: str, system_prompt: str) -> str:
  # Keep it simple: concatenate with clear delimiters
  parts = [
    "SYSTEM:\n" + system_prompt.strip(),
    "GOAL:\n" + goal.strip(),
  ]
  
  # Структурированный контекст для LLM
  if step_summary:
    parts.append("CONTEXT (last steps/results):\n" + step_summary.strip())
  
  # Добавляем инструкции по анализу
  parts.append(
    "ANALYSIS INSTRUCTIONS:\n"
    "1. Анализируй текущую страницу - что доступно?\n"
    "2. Оценивай прогресс - что уже сделано?\n"
    "3. Планируй следующий шаг - что нужно сделать?\n"
    "4. Избегай повторений - не делай одно и то же!\n"
  )
  
  # Упрощенный формат требования - только простые действия
  parts.append(
    "OUTPUT INSTRUCTIONS:\n"
    "Отвечай ТОЛЬКО в формате JSON БЕЗ markdown разметки:\n"
    "{\n"
    '  "mode": "act",\n'
    '  "tool": "browser_navigate",\n'
    '  "args": {"url": "https://amazon.com"},\n'
    '  "rationale": "Открываю Amazon для поиска кроссовок"\n'
    "}\n"
    "⚠️ ВАЖНО: НЕ используй ```json или ``` блоки! Только чистый JSON!\n"
    "Доступные инструменты:\n"
    "- browser_navigate(url) - перейти по ссылке\n"
    "- browser_click_text(text) - кликнуть по тексту (например: 'Continue shopping')\n"
    "- browser_type_text(field, text) - ввести текст в поле (например: 'search', 'Adidas sneakers')\n"
    "- browser_click_selector(selector) - кликнуть по CSS селектору (например: 'button[name=\"Continue\"]')\n"
    "- browser_type_selector(selector, text) - ввести текст по CSS селектору\n"
    "Режимы: act (действие), ask (вопрос), done (завершено)\n"
    "ПРАВИЛО: Используй простые инструменты, избегай сложных стратегий!\n"
    "СТРАТЕГИЯ: 1) Анализируй цель → 2) Выбирай инструмент → 3) Действуй!"
  )
  return "\n\n".join(parts)


def summarize_steps_for_llm(history: List[Dict[str, Any]], max_events: int = 8) -> str:
  # Build a compact textual summary of last N events
  tail = history[-max_events:]
  lines: List[str] = []
  
  # Добавляем заголовок контекста
  lines.append("=== ПОСЛЕДНИЕ СОБЫТИЯ ===")
  
  # Получаем текущий URL из последних событий
  current_url = None
  for ev in reversed(tail):
    if ev.get("tool") == "browser_navigate":
      args = ev.get("args") or ev.get("call", {}).get("args")
      if args and "url" in args:
        current_url = args["url"]
        break
  
  if current_url:
    lines.append(f"🌐 Текущий URL: {current_url}")
  
  for ev in tail:
    tool = ev.get("tool") or ev.get("type")
    status = ev.get("status") or ev.get("result", {}).get("status")
    progress = ev.get("progress")
    
    # Включаем анализ страницы для LLM
    if ev.get("type") == "page_analysis":
      lines.append(f"📄 СТРАНИЦА: {progress}")
      page_text = ev.get("page_text", "")
      if page_text:
        lines.append(f"📝 Текст: {page_text[:300]}...")
    
    elif ev.get("type") == "page_update":
      lines.append(f"🔄 ОБНОВЛЕНИЕ: {progress}")
      page_text = ev.get("page_text", "")
      if page_text:
        lines.append(f"📝 Новый текст: {page_text[:300]}...")
    
    elif progress:
      lines.append(f"📋 Прогресс: {progress}")
    
    if tool:
      args = ev.get("args") or ev.get("call", {}).get("args")
      if args is None:
        args = ev.get("function_call", {}).get("arguments")
      lines.append(f"🔧 Инструмент: {tool} | Аргументы: {json.dumps(args, ensure_ascii=False)} | Статус: {status}")
    
    # Include useful page context if available
    try:
      res = ev.get("result") or {}
      title = (res.get("result", {}) or {}).get("title") or res.get("title")
      summary = (res.get("result", {}) or {}).get("summary") or res.get("summary")
      if title:
        lines.append(f"📌 Заголовок: {str(title)[:160]}")
      if summary:
        # include only first 200 chars to keep prompt compact
        lines.append(f"📄 Содержание: {str(summary)[:200]}")
    except Exception:
      pass
    
    # Добавляем разделитель между событиями
    lines.append("---")
  
  # Добавляем итоговую информацию
  lines.append("=== ТЕКУЩЕЕ СОСТОЯНИЕ ===")
  lines.append(f"📊 Всего событий: {len(tail)}")
  
  # Определяем текущий этап
  if any(ev.get("type") == "page_analysis" for ev in tail):
    lines.append("📍 Этап: Страница загружена, анализируем содержимое")
  elif any(ev.get("type") == "page_update" for ev in tail):
    lines.append("📍 Этап: Страница обновлена, планируем следующий шаг")
  else:
    lines.append("📍 Этап: Выполняем действия")
  
  return "\n".join(lines)


async def maybe_capture_screenshot(session: ClientSession, run_dir: str, step_idx: int, force: bool = False) -> Optional[str]:
  """Capture one screenshot per new page state (throttled)."""
  try:
    res = await asyncio.wait_for(session.call_tool("browser_screenshot", arguments={"full_page": False}), timeout=8.0)
    try:
      structured = getattr(res, "structuredContent", None)
    except Exception:
      structured = None
    if isinstance(structured, dict):
      path = structured.get("result", {}).get("path") or structured.get("path")
    else:
      path = None
    if path:
      write_event(run_dir, {"ts": _now_iso(), "type": "screenshot", "step": step_idx, "path": path})
      return path
  except Exception as e:
    write_event(run_dir, {"ts": _now_iso(), "type": "screenshot_error", "step": step_idx, "error": str(e)})
  return None


def clean_llm_response(text: str) -> str:
  """Clean LLM response from markdown formatting and extract pure JSON."""
  if not text:
    return text
  
  # Remove markdown code blocks
  text = text.strip()
  
  # Remove ```json and ``` markers
  if text.startswith("```json"):
    text = text[7:]  # Remove ```json
  elif text.startswith("```"):
    text = text[3:]   # Remove ```
  
  if text.endswith("```"):
    text = text[:-3]  # Remove trailing ```
  
  return text.strip()


def parse_llm_output(text: str) -> Tuple[str, Dict[str, Any]]:
  """Parse LLM output in single mode schema format.
  
  Expected format:
  {
    "mode": "act|ask|done",
    "tool": "tool_name",  # only for mode="act"
    "args": {...},        # only for mode="act" 
    "question": "...",    # only for mode="ask"
    "result": "...",      # only for mode="done"
    "rationale": "explanation"
  }
  """
  print(f"🔍 DEBUG: Парсинг LLM ответа: {repr(text)}")
  print(f"🔍 DEBUG: Длина ответа: {len(text)} символов")
  
  # Clean the response from markdown formatting
  cleaned_text = clean_llm_response(text)
  print(f"🔍 DEBUG: Очищенный текст: {repr(cleaned_text)}")
  
  try:
    obj = json.loads(cleaned_text)
    print(f"🔍 DEBUG: JSON успешно распарсен: {type(obj)}")
    print(f"🔍 DEBUG: Ключи объекта: {list(obj.keys()) if isinstance(obj, dict) else 'не словарь'}")
    
    if not isinstance(obj, dict):
      raise ValueError("Response must be a JSON object")
    
    mode = obj.get("mode")
    print(f"🔍 DEBUG: Режим: {mode}")
    
    rationale = str(obj.get("rationale", "")).strip()
    print(f"🔍 DEBUG: Обоснование: {rationale}")
    
    if mode == "act":
      tool = str(obj.get("tool", "")).strip()
      args = obj.get("args", {}) or {}
      print(f"🔍 DEBUG: Инструмент: {tool}")
      print(f"🔍 DEBUG: Аргументы: {args}")
      
      if not tool:
        raise ValueError("mode='act' requires 'tool' field")
      return rationale, {"name": tool, "arguments": args}
    
    elif mode == "ask":
      question = str(obj.get("question", "")).strip()
      print(f"🔍 DEBUG: Вопрос: {question}")
      
      if not question:
        raise ValueError("mode='ask' requires 'question' field")
      return rationale, {"name": "assistant_ask", "arguments": {"question": question}}
    
    elif mode == "done":
      result = str(obj.get("result", "")).strip()
      print(f"🔍 DEBUG: Результат: {result}")
      
      if not result:
        raise ValueError("mode='done' requires 'result' field")
      evidence = obj.get("evidence", {}) or {}
      return rationale, {"name": "assistant_done", "arguments": {"reason": result, "evidence": evidence}}
    
    else:
      raise ValueError(f"Invalid mode: {mode}. Must be 'act', 'ask', or 'done'")
    
  except Exception as e:
    print(f"🔍 DEBUG: Ошибка парсинга: {e}")
    print(f"🔍 DEBUG: Тип ошибки: {type(e)}")
    raise ValueError(f"Failed to parse LLM response: {e}. Expected JSON with 'mode' field.")


def normalize_tool_name(name: str) -> str:
  # Map dotted names to server snake_case
  mapping = {
    "browser.navigate": "browser_navigate",
    "browser.wait": "browser_wait",
    "browser.list_interactives": "browser_list_interactives",
    "browser.overlay_show": "browser_overlay_show",
    "browser.overlay_hide": "browser_overlay_hide",
    "browser.overlay_act": "browser_overlay_act",
    "browser.find": "browser_find",
    "browser.press": "browser_press",
    "browser.scroll": "browser_scroll",
    "browser.extract": "browser_extract_universal",  # Обновлено на универсальный
    "browser.open_in_new_tab": "browser_open_in_new_tab",
    "browser.switch_tab": "browser_switch_tab",
    "browser.screenshot": "browser_screenshot",
    "browser.click_and_wait_download": "browser_click_and_wait_download",
    "browser.download_wait": "browser_download_wait",
    "browser.upload": "browser_upload",
    "browser.close_banners": "browser_close_banners",
    "assistant_done": "assistant_done",
    "assistant_ask": "assistant_ask",
    "browser.check_page_state": "browser_check_page_state",  # Новый инструмент диагностики
  }
  return mapping.get(name, name)


def is_post_hook_trigger(logical_name: str) -> bool:
  return logical_name in (
    "browser_navigate",
    "browser_reload", 
    "browser_open_in_new_tab",
    "browser_switch_tab",
    "browser_overlay_act",
  )


def is_new_page_trigger(name: str) -> bool:
  # Fire numeric overlay auto-show after navigation/tab changes
  return name in {
    "browser_navigate",
    "browser_reload",
    "browser_open_in_new_tab",
    "browser_switch_tab",
    "browser_back",
    "browser_forward",
  }


async def run_c6_loop(goal: str, max_steps: int, model_name: str, run_dir: str) -> None:
  system_prompt = load_system_prompt()
  genai = try_import_gemini()
  if genai is None:
    print("google-genai не установлен. Установите: pip install google-genai", file=sys.stderr)
    return

  api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
  if not api_key:
    print("Не найден GEMINI_API_KEY/GOOGLE_API_KEY в окружении.", file=sys.stderr)
    return

  # DEBUG: Проверяем API ключ
  print(f"🔍 DEBUG: API ключ найден, длина: {len(api_key)} символов")
  print(f"🔍 DEBUG: Первые 10 символов: {api_key[:10]}...")
  print(f"🔍 DEBUG: Последние 10 символов: ...{api_key[-10:]}")
  
  # Проверяем формат ключа
  if not api_key.startswith("AIza"):
    print("⚠️ ВНИМАНИЕ: API ключ не начинается с 'AIza' - возможно неверный формат")

  client = genai.Client(api_key=api_key)
  print(f"🔍 DEBUG: Gemini клиент создан: {type(client)}")

  server_params = StdioServerParameters(command="python3", args=["mcp_server.py"])
  print(f"🔍 DEBUG: MCP сервер параметры: {server_params}")
  
  async with stdio_client(server_params) as (read, write):
    print("🔍 DEBUG: MCP клиент создан")
    async with ClientSession(read, write) as session:
      print("🔍 DEBUG: MCP сессия создана")
      await session.initialize()
      print("🔍 DEBUG: MCP сессия инициализирована")

      last_close_ts = 0.0
      last_llm_ts = 0.0
      last_screenshot_path: Optional[str] = None
      history: List[Dict[str, Any]] = []

      # Feature flags and thresholds (simplified)
      not_found_retries = int(os.environ.get("NOT_FOUND_RETRIES", "2") or "2")
      fallback_on_not_found = os.environ.get("FALLBACK_ON_NOT_FOUND", "1") not in {"0", "false", "False"}

      error_counters: Dict[str, int] = {}

      for step_idx in range(1, max_steps + 1):
        # Build prompt (simplified - no items analysis)
        step_summary = summarize_steps_for_llm(history)
        llm_input = build_llm_input(goal, step_summary, system_prompt)

        write_event(run_dir, {"ts": _now_iso(), "type": "llm_request", "step": step_idx, "input_len": len(llm_input)})
        try:
          pth = write_text(run_dir, f"llm_input_step_{step_idx}.txt", llm_input)
          write_event(run_dir, {"ts": _now_iso(), "type": "llm_input_saved", "step": step_idx, "path": pth})
        except Exception:
          pass

        # Throttle LLM calls to avoid 429
        try:
          delta = time.monotonic() - last_llm_ts
          if delta < 7.0:
            wait_s = round(7.0 - delta, 2)
            write_event(run_dir, {"ts": _now_iso(), "type": "llm_throttle_wait", "step": step_idx, "seconds": wait_s})
            time.sleep(wait_s)
        except Exception:
          pass

        # Call Gemini with retry/backoff on 429
        out_text = ""
        llm_error: Optional[str] = None
        
        # DEBUG: Log the prompt being sent to LLM
        print(f"\n🔍 DEBUG: Отправляю LLM промпт длиной {len(llm_input)} символов")
        print(f"🔍 DEBUG: Первые 200 символов промпта: {llm_input[:200]}...")
        
        for attempt in range(0, 3):
          try:
            parts: List[Dict[str, Any]] = [{"text": llm_input}]
            try:
              if last_screenshot_path and os.path.exists(last_screenshot_path):
                with open(last_screenshot_path, "rb") as img_f:
                  img_b64 = base64.b64encode(img_f.read()).decode("ascii")
                parts.append({"inline_data": {"mime_type": "image/png", "data": img_b64}})
            except Exception as _:
              pass
            
            print(f"🔍 DEBUG: Попытка {attempt + 1}/3 - вызываю Gemini API...")
            resp = client.models.generate_content(model=model_name, contents=[{"role": "user", "parts": parts}])
            
            # DEBUG: Log raw response
            print(f"🔍 DEBUG: Получен ответ от Gemini, тип: {type(resp)}")
            print(f"🔍 DEBUG: Атрибуты ответа: {dir(resp)}")
            
            out_text = getattr(resp, "text", None) or ""
            print(f"🔍 DEBUG: resp.text = {repr(out_text)}")
            
            if not out_text:
              try:
                candidates = getattr(resp, "candidates", [])
                print(f"🔍 DEBUG: Кандидаты: {len(candidates)}")
                for i, c in enumerate(candidates):
                  print(f"🔍 DEBUG: Кандидат {i}: {dir(c)}")
                  candidate_text = getattr(c, "text", None)
                  print(f"🔍 DEBUG: Кандидат {i} текст: {repr(candidate_text)}")
                out_text = "\n".join([c.text for c in candidates if getattr(c, "text", None)])
                print(f"🔍 DEBUG: Объединенный текст: {repr(out_text)}")
              except Exception as e:
                print(f"🔍 DEBUG: Ошибка при обработке кандидатов: {e}")
                out_text = ""
            
            print(f"🔍 DEBUG: Финальный out_text: {repr(out_text)}")
            
            llm_error = None
            last_llm_ts = time.monotonic()
            break
          except Exception as e:
            err_str = str(e)
            llm_error = err_str
            print(f"🔍 DEBUG: Ошибка Gemini API (попытка {attempt + 1}): {err_str}")
            # Detect quota/429
            if "RESOURCE_EXHAUSTED" in err_str or "429" in err_str:
              # Try to parse retryDelay like "retryDelay': '57s'"
              m = re.search(r"retryDelay[^\d]*(\d+)s", err_str)
              if m:
                wait_s = max(5, int(m.group(1)))
              else:
                wait_s = 8 + 4 * attempt
              write_event(run_dir, {"ts": _now_iso(), "type": "llm_retry", "step": step_idx, "attempt": attempt + 1, "wait_s": wait_s, "error": err_str})
              print(f"🔍 DEBUG: Ожидание {wait_s} секунд перед повтором...")
              time.sleep(wait_s)
              continue
            else:
              write_event(run_dir, {"ts": _now_iso(), "type": "llm_error", "step": step_idx, "error": err_str})
              break
        if llm_error and not out_text:
          # Give up this run on persistent LLM error
          print(f"🔍 DEBUG: Все попытки исчерпаны, ошибка: {llm_error}")
          break

        write_event(run_dir, {"ts": _now_iso(), "type": "llm_response", "step": step_idx, "text": out_text})
        
        # DEBUG: Log what we got from LLM
        print(f"🔍 DEBUG: LLM ответил: {repr(out_text)}")
        if not out_text or out_text.strip() == "":
          print("🚨 КРИТИЧЕСКАЯ ОШИБКА: LLM вернул пустой ответ!")
          print("🚨 Возможные причины:")
          print("🚨 1. Проблема с Gemini API ключом")
          print("🚨 2. Проблема с промптом (слишком длинный/сложный)")
          print("🚨 3. Проблема с моделью Gemini")
          print("🚨 4. Сетевые проблемы")
          
          # FALLBACK: Простые команды без LLM
          print("🔄 Активирую fallback режим...")
          if "amazon" in goal.lower():
            fallback_tool = "browser_navigate"
            fallback_args = {"url": "https://amazon.com"}
            fallback_rationale = "Открываю Amazon (fallback режим)"
            print(f"🔄 Fallback: {fallback_tool} с аргументами {fallback_args}")
            return fallback_rationale, {"name": fallback_tool, "arguments": fallback_args}
          elif "google" in goal.lower():
            fallback_tool = "browser_navigate"
            fallback_args = {"url": "https://google.com"}
            fallback_rationale = "Открываю Google (fallback режим)"
            print(f"🔄 Fallback: {fallback_tool} с аргументами {fallback_args}")
            return fallback_rationale, {"name": fallback_tool, "arguments": fallback_args}
          else:
            print("🔄 Fallback: Не могу определить сайт, завершаю работу")
            break

        # Parse
        try:
          progress, fcall = parse_llm_output(out_text or "")
        except Exception as e:
          excerpt = (out_text or "")[:500]
          write_event(run_dir, {"ts": _now_iso(), "type": "parse_error", "step": step_idx, "error": str(e), "response_excerpt": excerpt})
          
          # Simple fallback: ask LLM to retry with correct format
          print(f"Ошибка парсинга LLM: {e}")
          print("LLM должен ответить в формате JSON с полем 'mode'")
          print("Повторяю запрос...")
          
          # Wait before retry
          time.sleep(2.0)
          continue

        logical_name = fcall.get("name", "")
        args = fcall.get("arguments", {}) or {}

        write_event(run_dir, {"ts": _now_iso(), "type": "tool_mapping", "logical": logical_name, "mapped": normalize_tool_name(logical_name)})

        # Handle assistant_ask/done locally
        if logical_name == "assistant_done":
          write_event(run_dir, {"ts": _now_iso(), "type": "assistant_done", "reason": args.get("reason", ""), "step": step_idx, "progress": progress})
          break
        if logical_name == "assistant_ask":
          question = str(args.get("question", ""))
          write_event(run_dir, {"ts": _now_iso(), "type": "assistant_ask", "question": question, "step": step_idx, "progress": progress})
          print("Вопрос ассистента:", question)
          print("Введите ответ и нажмите Enter:", flush=True)
          user_answer = sys.stdin.readline().strip()
          # Feed answer back into history context
          history.append({"type": "user_answer", "text": user_answer})
          # Pause between iterations
          time.sleep(4.0)
          continue

        mapped = normalize_tool_name(logical_name)

        # Execute tool call (simplified - no complex validation)
        write_event(run_dir, {"ts": _now_iso(), "type": "tool_call", "step": step_idx, "progress": progress, "tool": mapped, "args": args})
        print(f"🔍 DEBUG: ВЫПОЛНЯЮ инструмент: {mapped} с аргументами: {args}")
        
        t0 = time.monotonic()
        try:
          # per-call timeout to prevent hanging tools
          print(f"🔍 DEBUG: Вызываю session.call_tool({mapped}, {args})...")
          call_res = await asyncio.wait_for(session.call_tool(mapped, arguments=args), timeout=20.0)
          print(f"🔍 DEBUG: Инструмент выполнен успешно: {type(call_res)}")
          
          try:
            structured = getattr(call_res, "structuredContent", None)
          except Exception:
            structured = None
          result_obj: Dict[str, Any]
          if structured is None:
            # Fallback: collect any text content
            text_blocks = []
            for c in getattr(call_res, "content", []) or []:
              try:
                text = getattr(c, "text", None)
                if text:
                  text_blocks.append(text)
              except Exception:
                pass
            result_obj = {"status": "ok", "text": "\n".join(text_blocks)}
          else:
            result_obj = structured
          dur_ms = int((time.monotonic() - t0) * 1000)
          print(f"🔍 DEBUG: Результат выполнения: {result_obj}")
          write_event(run_dir, {"ts": _now_iso(), "type": "tool_result", "step": step_idx, "tool": mapped, "result": result_obj, "duration_ms": dur_ms})

          # Auto post-hook: close banners (throttled)
          try:
            now_ts = time.monotonic()
            if is_post_hook_trigger(logical_name) and (now_ts - last_close_ts) >= 2.0:
              cb_args = {
                "time_budget_ms": 2500,
                "max_passes": 3,
                "strategy": "safe",
                "languages": ["en", "ru"],
                "return_details": False,
              }
              write_event(run_dir, {"ts": _now_iso(), "type": "post_hook_call", "hook": "browser_close_banners", "args": cb_args})
              _ = await asyncio.wait_for(session.call_tool("browser_close_banners", arguments=cb_args), timeout=6.0)
              write_event(run_dir, {"ts": _now_iso(), "type": "post_hook_result", "hook": "browser_close_banners", "result": {}})
              last_close_ts = now_ts
          except Exception:
            pass

          # Auto post-hook: wait and screenshot after navigation
          try:
            if is_new_page_trigger(logical_name):
              write_event(run_dir, {"ts": _now_iso(), "type": "post_hook_call", "hook": "auto_wait", "args": {"ms": 2000}})
              _ = await asyncio.wait_for(session.call_tool("browser_wait", arguments={"ms": 2000}), timeout=8.0)
              write_event(run_dir, {"ts": _now_iso(), "type": "post_hook_result", "hook": "auto_wait", "result": {}})

              # Capture screenshot for LLM context
              last_screenshot_path = await maybe_capture_screenshot(session, run_dir, step_idx)

              # АНАЛИЗ СТРАНИЦЫ: Получаем текстовую информацию для LLM
              try:
                write_event(run_dir, {"ts": _now_iso(), "type": "post_hook_call", "hook": "auto_extract_text", "args": {"mode": "adaptive"}})
                extract_result = await asyncio.wait_for(session.call_tool("browser_extract_universal", arguments={"mode": "adaptive", "max_text_length": 5000, "timeout_ms": 12000}), timeout=15.0)
                write_event(run_dir, {"ts": _now_iso(), "type": "post_hook_result", "hook": "auto_extract_text", "result": {}})
                
                # Добавляем текстовую информацию о странице в историю для LLM
                try:
                  extract_structured = getattr(extract_result, "structuredContent", None)
                  if isinstance(extract_structured, dict):
                    text_content = extract_structured.get("result", {}).get("text", "")
                    if text_content:
                      # Создаем краткое описание страницы
                      page_summary = text_content[:500]  # Первые 500 символов
                      history.append({
                        "type": "page_analysis",
                        "progress": f"Страница загружена, получен текстовый контент",
                        "page_text": page_summary,
                        "result": {"title": None, "summary": None},
                      })
                except Exception as e:
                  write_event(run_dir, {"ts": _now_iso(), "type": "page_analysis_error", "error": str(e), "step": step_idx})
              except Exception as e:
                write_event(run_dir, {"ts": _now_iso(), "type": "auto_extract_text_error", "error": str(e), "step": step_idx})
          except Exception:
            pass

          # Append to history
          history.append({
            "progress": progress,
            "tool": logical_name,
            "call": {"name": mapped, "args": args},
            "result": result_obj,
            "status": result_obj.get("status") if isinstance(result_obj, dict) else None,
            "timestamp": _now_iso(),
            "step": step_idx,
          })

          # АНАЛИЗ РЕЗУЛЬТАТА ДЕЙСТВИЯ: Создаем детальную информацию для LLM
          try:
            # Анализируем что произошло после действия
            action_result = {
              "action": logical_name,
              "status": "completed",
              "timestamp": _now_iso(),
              "step": step_idx,
            }
            
            # Добавляем детали результата
            if isinstance(result_obj, dict):
              # ИСПРАВЛЕНО: Правильно обрабатываем структуру result_obj
              actual_result = result_obj.get("result", result_obj)  # Получаем вложенный result или сам объект
              
              if actual_result.get("status") == "ok":
                action_result["success"] = True
                action_result["details"] = actual_result
                
                # Анализируем что именно получилось
                if "action" in actual_result:
                  action_result["what_happened"] = actual_result["action"]
                if "text" in actual_result:
                  action_result["text_result"] = actual_result["text"][:200]
                if "url" in actual_result:
                  action_result["current_url"] = actual_result["url"]
              else:
                action_result["success"] = False
                action_result["error"] = actual_result.get("error", "Unknown error")
            else:
              action_result["success"] = True
              action_result["details"] = str(result_obj)
            
            # Добавляем результат действия в историю
            history.append({
              "type": "action_result",
              "progress": f"Действие '{logical_name}' выполнено",
              "result": action_result,
            })
            
            print(f"🔍 DEBUG: Результат действия добавлен в историю: {action_result}")
            
          except Exception as e:
            print(f"🔍 DEBUG: Ошибка анализа результата действия: {e}")

          # АНАЛИЗ СТРАНИЦЫ ПОСЛЕ ДЕЙСТВИЯ: Получаем обновленную информацию для LLM
          try:
            # Ждем немного чтобы страница обновилась
            await asyncio.sleep(1.0)
            
            # Принудительный анализ для критических действий
            force_analysis = logical_name in ["browser_type_text", "browser_click_selector", "browser_click_text"]
            if force_analysis:
              print(f"🔍 DEBUG: Принудительный анализ для {logical_name}")
              
              # Создаем скриншот для LLM чтобы он видел визуальные изменения
              try:
                screenshot_path = await maybe_capture_screenshot(session, run_dir, step_idx)
                if screenshot_path:
                  last_screenshot_path = screenshot_path
                  print(f"🔍 DEBUG: Создан скриншот после действия {logical_name}: {screenshot_path}")
              except Exception as e:
                print(f"🔍 DEBUG: Ошибка создания скриншота: {e}")
            
            write_event(run_dir, {"ts": _now_iso(), "type": "post_action_call", "hook": "auto_extract_text", "args": {"mode": "adaptive"}})
            extract_result = await asyncio.wait_for(session.call_tool("browser_extract_universal", arguments={"mode": "adaptive", "max_text_length": 5000, "timeout_ms": 12000}), timeout=15.0)
            write_event(run_dir, {"ts": _now_iso(), "type": "post_action_result", "hook": "auto_extract_text", "result": {}})
            
            # Добавляем обновленную информацию о странице в историю для LLM
            try:
              extract_structured = getattr(extract_result, "structuredContent", None)
              print(f"🔍 DEBUG: extract_result тип: {type(extract_result)}")
              print(f"🔍 DEBUG: extract_structured: {extract_structured}")
              
              if isinstance(extract_structured, dict):
                text_content = extract_structured.get("result", {}).get("text", "")
                print(f"🔍 DEBUG: text_content длина: {len(text_content) if text_content else 0}")
                print(f"🔍 DEBUG: text_content первые 200 символов: {repr(text_content[:200]) if text_content else 'None'}")
                
                if text_content:
                  # Создаем краткое описание обновленной страницы
                  page_summary = text_content[:500]  # Первые 500 символов
                  
                  # Проверяем есть ли изменения на странице
                  if "search" in logical_name.lower() or "click" in logical_name.lower():
                    # Анализируем что изменилось
                    if "results" in text_content.lower() or "video" in text_content.lower():
                      progress_msg = f"Поиск выполнен! Найдены результаты: {text_content[:100]}..."
                    elif "playing" in text_content.lower() or "duration" in text_content.lower():
                      progress_msg = f"Видео запущено! Музыка воспроизводится"
                    else:
                      progress_msg = f"Страница обновлена, но изменения незначительны"
                  else:
                    progress_msg = f"После действия '{logical_name}' страница обновлена"
                  
                  history.append({
                    "type": "page_update",
                    "progress": progress_msg,
                    "page_text": page_summary,
                    "result": {"action": logical_name, "status": "completed"},
                  })
                  
                  # DEBUG: Показываем что LLM получит
                  print(f"🔍 DEBUG: LLM получит обновление страницы: {page_summary[:100]}...")
                else:
                  print(f"🔍 DEBUG: Текст страницы пустой после действия {logical_name}")
                  print(f"🔍 DEBUG: extract_structured ключи: {list(extract_structured.keys()) if isinstance(extract_structured, dict) else 'не словарь'}")
                  if isinstance(extract_structured, dict):
                    print(f"🔍 DEBUG: extract_structured['result']: {extract_structured.get('result')}")
            except Exception as e:
              write_event(run_dir, {"ts": _now_iso(), "type": "post_action_analysis_error", "error": str(e), "step": step_idx})
              print(f"🔍 DEBUG: Ошибка анализа страницы: {e}")
          except Exception as e:
            write_event(run_dir, {"ts": _now_iso(), "type": "post_action_extract_error", "error": str(e), "step": step_idx})
            print(f"🔍 DEBUG: Ошибка извлечения текста: {e}")

        except Exception as e:
          write_event(run_dir, {"ts": _now_iso(), "type": "tool_error", "step": step_idx, "tool": mapped, "args": args, "error": str(e)})
          history.append({"progress": progress, "tool": logical_name, "error": str(e)})

        # Simple pause between steps
        time.sleep(2.0)


def main() -> None:
  parser = argparse.ArgumentParser()
  parser.add_argument("--goal", required=False, default="", help="Естественная цель, например: 'YouTube: найди и запусти хип-хоп'")
  parser.add_argument("--max-steps", type=int, default=20)
  parser.add_argument("--model", default="gemini-2.5-flash")
  args = parser.parse_args()

  # Interactive goal input if not provided via flag
  goal = args.goal.strip()
  if not goal:
    print("Введите цель ассистента и нажмите Enter:", flush=True)
    goal = sys.stdin.readline().strip()
    if not goal:
      print("Пустая цель. Завершение.")
      return

  run_id = str(uuid.uuid4())
  run_dir = os.path.join(RUNS_DIR, run_id)
  _ensure_dir(run_dir)

  write_meta(run_dir, {"run_id": run_id, "started_at": _now_iso(), "goal": goal, "model": args.model, "c6": True})

  try:
    asyncio.run(run_c6_loop(goal=goal, max_steps=args.max_steps, model_name=args.model, run_dir=run_dir))
  except KeyboardInterrupt:
    print("Остановлено пользователем.")

  print("Готово. Логи шага: ", run_dir)


if __name__ == "__main__":
  main()


