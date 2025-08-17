"""
Обновленный оркестратор с интеграцией DOM анализатора

Интегрирует DOM анализатор инструменты в стиле browser-use
для индексированного взаимодействия с веб-страницами.
"""

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
  
  # Обновленный формат с поддержкой DOM анализатора
  parts.append(
    "OUTPUT INSTRUCTIONS:\n"
    "Отвечай ТОЛЬКО в формате JSON БЕЗ markdown разметки:\n"
    "{\n"
    '  "mode": "act",\n'
    '  "tool": "browser_get_state",\n'
    '  "args": {},\n'
    '  "rationale": "Получаю состояние страницы для анализа"\n'
    "}\n"
    "\n"
    "Доступные инструменты:\n"
    "📱 DOM Analyzer (рекомендуемые):\n"
    "  - browser_get_state: получение состояния страницы с индексами\n"
    "  - browser_click: клик по элементу по индексу\n"
    "  - browser_type: ввод текста в поле по индексу\n"
    "  - browser_navigate_dom: навигация по URL\n"
    "  - browser_extract_content: извлечение контента\n"
    "  - browser_scroll: прокрутка страницы\n"
    "  - browser_go_back: переход назад\n"
    "  - browser_list_tabs: список вкладок\n"
    "\n"
    "🔄 Legacy (для совместимости):\n"
    "  - browser_navigate: навигация через Playwright\n"
    "  - files_search: поиск файлов\n"
    "  - files_read_text: чтение файлов\n"
    "\n"
    "💡 Рекомендуемый рабочий процесс:\n"
    "1. browser_get_state - получить состояние страницы\n"
    "2. Анализировать элементы по индексам\n"
    "3. browser_click/browser_type с нужными индексами\n"
    "4. Повторять при изменении страницы\n"
  )
  
  return "\n\n".join(parts)


def summarize_steps_for_llm(history: List[Dict[str, Any]]) -> str:
  """Создает краткое резюме последних шагов для LLM"""
  if not history:
    return ""
  
  # Берем последние 5 шагов
  recent_steps = history[-5:]
  
  summary_parts = []
  for step in recent_steps:
    if step.get("type") == "tool_call":
      tool_name = step.get("tool_name", "unknown")
      success = step.get("success", False)
      if success:
        summary_parts.append(f"✅ {tool_name}: успешно")
      else:
        error = step.get("error", "неизвестная ошибка")
        summary_parts.append(f"❌ {tool_name}: {error}")
    elif step.get("type") == "page_state":
      elements_count = step.get("interactive_elements", 0)
      summary_parts.append(f"📄 Страница: {elements_count} интерактивных элементов")
  
  return "\n".join(summary_parts)


def parse_llm_output(text: str) -> Tuple[str, Dict[str, Any]]:
  """Парсит вывод LLM в формат инструмента"""
  try:
    # Ищем JSON в тексте - более точный поиск
    json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text, re.DOTALL)
    if not json_match:
      raise ValueError("JSON не найден в ответе")
    
    json_str = json_match.group(0)
    data = json.loads(json_str)
    
    mode = data.get("mode", "act")
    tool = data.get("tool", "") or data.get("name", "")  # Поддержка обоих полей
    args = data.get("args", {}) or {}
    rationale = data.get("rationale", "")
    
    if not tool:
      raise ValueError("Не указан инструмент")
    
    return rationale, {"name": tool, "arguments": args}
    
  except Exception as e:
    raise ValueError(f"Ошибка парсинга LLM: {e}")


def normalize_tool_name(name: str) -> str:
  """Нормализует имена инструментов с поддержкой DOM анализатора"""
  # Map dotted names to server snake_case
  mapping = {
    # DOM Analyzer инструменты (основные - рекомендуемые)
    "browser.get_state": "browser_get_state",
    "browser.click": "browser_click",
    "browser.type": "browser_type",
    "browser.navigate_dom": "browser_navigate_dom",
    "browser.extract_content": "browser_extract_content",
    "browser.scroll": "browser_scroll",
    "browser.go_back": "browser_go_back",
    "browser.list_tabs": "browser_list_tabs",
    "dom_analyzer.status": "dom_analyzer_status",
    
    # Legacy инструменты (для совместимости)
    "browser.navigate": "browser_navigate",
    "browser.click_by_text": "browser_click_by_text",
    "browser.type_by_text": "browser_type_by_text",
    "browser.click_selector": "browser_click_selector",
    "browser.type_selector": "browser_type_selector",
    "browser.back": "browser_back",
    "browser.forward": "browser_forward",
    "browser.reload": "browser_reload",
    "browser.open_in_new_tab": "browser_open_in_new_tab",
    "browser.switch_tab": "browser_switch_tab",
    "browser.find": "browser_find",
    "browser.press": "browser_press",
    "browser.extract": "browser_extract_universal",
    "browser.screenshot": "browser_screenshot",
    "browser.click_and_wait_download": "browser_click_and_wait_download",
    "browser.download_wait": "browser_download_wait",
    "browser.upload": "browser_upload",
    "browser.close_banners": "browser_close_banners",
    
    # Ассистент
    "assistant_done": "assistant_done",
    "assistant_ask": "assistant_ask",
    
    # Диагностика
    "browser.check_page_state": "browser_check_page_state",
    "browser.human_click_text": "browser_human_click_text",
    "browser.smart_click_text": "browser_smart_click_text",
    "browser.detect_anti_bot": "browser_detect_anti_bot",
    "browser.click_text_with_diagnostics": "browser_click_text_with_diagnostics",
    "browser.click_coordinates": "browser_click_coordinates",
    "browser.get_element_coordinates": "browser_get_element_coordinates",
    
    # Файловые операции
    "files.search": "files_search",
    "files.read_text": "files_read_text",
  }
  return mapping.get(name, name)


def is_post_hook_trigger(logical_name: str) -> bool:
  """Определяет, нужно ли выполнить post-hook после инструмента"""
  return logical_name in (
    "browser_navigate",
    "browser_navigate_dom",  # Добавлен DOM анализатор
    "browser_reload", 
    "browser_open_in_new_tab",
    "browser_switch_tab",
    "browser_overlay_act",
  )


def is_new_page_trigger(name: str) -> bool:
  """Определяет, нужно ли показать overlay после изменения страницы"""
  # Fire numeric overlay auto-show after navigation/tab changes
  triggers = {
    "browser_navigate",
    "browser_navigate_dom",  # Добавлен DOM анализатор
    "browser_reload",
    "browser_open_in_new_tab",
    "browser_switch_tab",
    "browser_back",
    "browser_forward",
  }
  result = name in triggers
  print(f"🔍 DEBUG: is_new_page_trigger({name}) = {result}, триггеры: {triggers}")
  return result


def is_dom_analyzer_tool(tool_name: str) -> bool:
  """Определяет, является ли инструмент DOM анализатором"""
  dom_tools = {
    "browser_get_state",
    "browser_click",
    "browser_type",
    "browser_navigate_dom",
    "browser_extract_content",
    "browser_scroll",
    "browser_go_back",
    "browser_list_tabs",
    "dom_analyzer_status"
  }
  return tool_name in dom_tools


async def run_c6_loop(goal: str, max_steps: int, model_name: str, run_dir: str) -> None:
  """Основной цикл оркестратора с поддержкой DOM анализатора"""
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

  # Используем интегрированный MCP сервер с DOM анализатором
  # Запускаем MCP сервер
  server_params = StdioServerParameters(
      command="python3", 
      args=["mcp_server_dom_analyzer.py", "--stdio"]
  )
  print(f"🔍 DEBUG: MCP сервер параметры: {server_params}")
  print("🚀 Используется интегрированный MCP сервер с DOM анализатором")
  
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
      
      # Состояние DOM анализатора
      current_page_state: Optional[Dict[str, Any]] = None
      last_state_update: float = 0.0

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

        # Throttle LLM calls to avoid 429 - оптимизировано для ускорения
        try:
          delta = time.monotonic() - last_llm_ts
          if delta < 2.0:  # Уменьшено с 7.0 до 2.0 секунд
            wait_s = round(2.0 - delta, 2)
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

        # Авто-подмена обычного клика на умный клик с anti-bot обходом
        if mapped == "browser_click_text":
          try:
            # Попробуем получить рекомендации из последнего анализа страницы, если есть
            recommended_tool = "browser_smart_click_text"
            mapped = recommended_tool or "browser_smart_click_text"
          except Exception:
            mapped = "browser_smart_click_text"

        # Выполняем инструмент
        print(f"🔧 Выполняю инструмент: {mapped} с аргументами: {args}")
        
        try:
          # Проверяем, нужно ли обновить состояние страницы для DOM анализатора
          if is_dom_analyzer_tool(mapped) and (current_page_state is None or time.monotonic() - last_state_update > 30.0):
            print("🔄 Обновляю состояние страницы для DOM анализатора...")
            try:
              state_result = await asyncio.wait_for(
                session.call_tool("browser_get_state", arguments={}),
                timeout=10.0
              )
              if state_result and state_result.get("success"):
                current_page_state = state_result
                last_state_update = time.monotonic()
                print(f"✅ Состояние страницы обновлено: {state_result.get('interactive_elements', 0)} интерактивных элементов")
                
                # Сохраняем в историю
                history.append({
                  "type": "page_state",
                  "timestamp": last_state_update,
                  "interactive_elements": state_result.get('interactive_elements', 0),
                  "total_elements": state_result.get('total_elements', 0),
                  "url": state_result.get('url', ''),
                  "title": state_result.get('title', '')
                })
              else:
                print(f"⚠️ Не удалось обновить состояние страницы: {state_result}")
            except Exception as e:
              print(f"⚠️ Ошибка при обновлении состояния страницы: {e}")

          # Выполняем основной инструмент
          result = await asyncio.wait_for(
            session.call_tool(mapped, arguments=args),
            timeout=15.0
          )
          
          # Преобразуем CallToolResult в словарь для совместимости
          if hasattr(result, 'content'):
            # Новый формат MCP
            result_dict = result.content[0].text if result.content else {}
            try:
                # Пытаемся распарсить JSON из текста
                import json
                result_dict = json.loads(result_dict) if isinstance(result_dict, str) else result_dict
            except:
                result_dict = {"success": True, "message": str(result_dict)}
          else:
            # Старый формат
            result_dict = result if isinstance(result, dict) else {"success": True, "message": str(result)}
          
          success = result_dict.get("success", True)
          error_msg = result_dict.get("error", "") if not success else ""
          
          # Логируем результат
          write_event(run_dir, {
            "ts": _now_iso(),
            "type": "tool_call",
            "step": step_idx,
            "tool_name": mapped,
            "arguments": args,
            "success": success,
            "error": error_msg,
            "result": result_dict
          })
          
          if success:
            print(f"✅ {mapped} выполнен успешно")
            
            # Если это DOM анализатор инструмент, обновляем состояние
            if is_dom_analyzer_tool(mapped) and mapped != "browser_get_state":
              print("🔄 Обновляю состояние страницы после выполнения DOM инструмента...")
              try:
                state_result = await asyncio.wait_for(
                  session.call_tool("browser_get_state", arguments={}),
                  timeout=10.0
                )
                if state_result and state_result.get("success"):
                  current_page_state = state_result
                  last_state_update = time.monotonic()
                  print(f"✅ Состояние страницы обновлено: {state_result.get('interactive_elements', 0)} интерактивных элементов")
              except Exception as e:
                print(f"⚠️ Ошибка при обновлении состояния страницы: {e}")
          else:
            print(f"❌ {mapped} завершился с ошибкой: {error_msg}")
            
            # Увеличиваем счетчик ошибок
            error_counters[mapped] = error_counters.get(mapped, 0) + 1
            
            # Если много ошибок с одним инструментом, предлагаем альтернативу
            if error_counters[mapped] >= 3:
              print(f"⚠️ Много ошибок с {mapped}, предлагаю альтернативу...")
              if mapped == "browser_click" and current_page_state:
                print("💡 Попробуйте browser_get_state для получения актуального состояния страницы")
              elif mapped == "browser_type" and current_page_state:
                print("💡 Попробуйте browser_get_state для получения актуального состояния страницы")
          
          # Добавляем в историю
          history.append({
            "type": "tool_call",
            "tool_name": mapped,
            "arguments": args,
            "success": success,
            "error": error_msg,
            "timestamp": time.monotonic()
          })
          
        except asyncio.TimeoutError:
          error_msg = "Timeout при выполнении инструмента"
          print(f"⏰ {mapped} превысил таймаут")
          
          write_event(run_dir, {
            "ts": _now_iso(),
            "type": "tool_timeout",
            "step": step_idx,
            "tool_name": mapped,
            "arguments": args,
            "error": error_msg
          })
          
          # Добавляем в историю
          history.append({
            "type": "tool_timeout",
            "tool_name": mapped,
            "arguments": args,
            "error": error_msg,
            "timestamp": time.monotonic()
          })
          
        except Exception as e:
          error_msg = str(e)
          print(f"❌ Ошибка при выполнении {mapped}: {error_msg}")
          
          write_event(run_dir, {
            "ts": _now_iso(),
            "type": "tool_error",
            "step": step_idx,
            "tool_name": mapped,
            "arguments": args,
            "error": error_msg
          })
          
          # Добавляем в историю
          history.append({
            "type": "tool_error",
            "tool_name": mapped,
            "arguments": args,
            "error": error_msg,
            "timestamp": time.monotonic()
          })

        # Post-hook для навигации
        if is_post_hook_trigger(mapped):
          print(f"🔄 Выполняю post-hook для {mapped}...")
          
          # Ждем загрузки страницы
          await asyncio.sleep(2.0)
          
          # Закрываем баннеры если нужно
          try:
            cb_args = {"time_budget_ms": 2000, "max_passes": 2, "strategy": "safe"}
            _ = await asyncio.wait_for(session.call_tool("browser_close_banners", arguments=cb_args), timeout=6.0)
            print("✅ Баннеры закрыты")
          except Exception as e:
            print(f"⚠️ Не удалось закрыть баннеры: {e}")
          
          # Ждем стабилизации страницы
          try:
            _ = await asyncio.wait_for(session.call_tool("browser_wait", arguments={"ms": 1000}), timeout=8.0)
          except Exception:
            pass

        # Пауза между шагами
        await asyncio.sleep(1.0)

      print(f"🎯 Цикл завершен после {step_idx} шагов")


def main():
  """Основная функция"""
  parser = argparse.ArgumentParser(description="Orchestrator MBP1 с DOM анализатором")
  parser.add_argument("goal", help="Цель для выполнения")
  parser.add_argument("--max-steps", type=int, default=50, help="Максимальное количество шагов")
  parser.add_argument("--model", default="gemini-2.5-flash-lite", help="Модель Gemini для использования")
  parser.add_argument("--run-dir", help="Директория для сохранения результатов")
  
  args = parser.parse_args()
  
  # Создаем директорию для запуска
  if not args.run_dir:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    args.run_dir = os.path.join(RUNS_DIR, f"run_{timestamp}")
  
  print(f"🚀 Запуск оркестратора с DOM анализатором")
  print(f"🎯 Цель: {args.goal}")
  print(f"🔧 Модель: {args.model}")
  print(f"📁 Директория: {args.run_dir}")
  print(f"📱 DOM анализатор: интегрирован")
  print(f"🔄 Legacy инструменты: поддерживаются")
  
  # Запускаем основной цикл
  asyncio.run(run_c6_loop(args.goal, args.max_steps, args.model, args.run_dir))


if __name__ == "__main__":
  main()
