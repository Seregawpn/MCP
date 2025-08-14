## MBP‑1 — Браузерный ассистент (numeric‑first), TTS и PTT beta

### Цель и результат
- Пользователь даёт натуральную команду → ассистент выполняет последовательность шагов В БРАУЗЕРЕ, по одному инструменту за итерацию, до статуса `done`.
- Основной способ взаимодействия — по НОМЕРАМ элементов (numeric‑first) с чёткими фоллбеками.
- Допускаются уточняющие вопросы (`assistant_ask`) при нехватке данных.
- Объём MVP‑1: Браузер + TTS (обязательно) + PTT (beta). MCP для Файлов/Приложений/Почты/iMessage — исключены из MVP‑1 и перенесены в последующие релизы.

### Объём функциональности (браузер + TTS/PTT beta)
- Оркестратор: observe → plan → act → validate → ask/done; 1 итерация = 1 function_call + пауза ~4с. После действий — 4s стабилизация и обязательное обновление цифр + скриншот до следующего решения.
- MCP (браузер): navigate, wait, list_interactives, overlay_show/hide, overlay_act, find, press, scroll, close_banners (post‑hook), extract, вкладки (open_in_new_tab/switch_tab), screenshot.
- MCP (озвучка): tts_speak(text, voice, rate), tts_stop().
- PTT beta: удержание клавиши → запись → ASR (Apple Speech/Whisper) → текст цели/ответа.
- SYSTEM PROMPT: строгий формат ответа (mode=act|ask|done), numeric‑first, фоллбеки, ask/done.

---

### Поэтапная реализация (микро‑проекты, только MVP‑1)
- МП‑1: Браузер (MCP) + TTS
  - Функции: navigate, close_banners, list_interactives/overlay_show/overlay_act, find, press, scroll, extract, вкладки, screenshot, wait.
  - TTS: озвучка прогресса/ask/done; barge‑in (tts_stop).
  - DoD: «сводка сайта» и «клик/ввод по номеру» стабильны; >90% действий — по номерам; логи и подтверждения работают.
- МП‑2: LLM‑планировщик + цикл ask/done
  - Функция: planner_llm с жёсткой схемой; интеграция в оркестратор; 1 шаг = 1 tool‑call; пауза 4с; numeric‑first; фоллбеки; LLM‑summary.
  - DoD: 3 сценария от натуральной команды; ≤2 уточнения; done=true только при верификации результата; логи planner_prompt/response. В LLM‑summary включены title/snippet и топ интерактивов с номерами.
- МП‑3: PTT beta (опционально в MVP‑1)
  - Удержание клавиши → запись 16 kHz WAV → ASR → текст цели/ответа; логи ptt_start/stop/asr_result.
  - DoD: стабильный старт/стоп; корректный ввод текста; озвучка подтверждает распознанное.
- МП‑4: Совместимость с VoiceOver и клавиатура
  - Хоткеи: Tab/Shift+Tab, 1–9, Enter, Esc, Space, R, H, C, L, S, O, I, Cmd+.
  - DoD: чек‑лист VO проходит; паник‑стоп работает; хоткеи переназначаемые.

### LLM‑планировщик (planner_llm.py)
- Сигнатура: `plan(natural_command: str, tools_catalog: list[ToolSpec]) -> Plan`.
- Формат `Plan`:
```json
{
  "steps": [ { "tool": "string", "args": {} } ],
  "rationale": "string",
  "riskLevel": 0,
  "ask": null,
  "done": false
}
```
- Промпт (system): цель, безопасность, перечень доступных инструментов, строгая схема ответа, правила ask/done.
- Источник инструментов: `list_tools()` из MCP; фильтр по белому списку.
- Логи: `planner_prompt`, `planner_response` с маскированием PII.

### Интеграция LLM в оркестратор
- Флаг: `--use-llm-planner`.
- Валидация плана по JSON‑схеме; при невалидности — одна перегенерация.
- Если `ask` есть: озвучить вопрос (tts_speak) → принять ответ (клава/PTT) → пересчитать план с учётом ответа.
- После каждого шага: валидация результата (ok/error), ретраи/альтернативы, при необходимости — репланирование.

### Цикл исполнения (loop)
- Состояния: `observe` → `plan` → `confirm` → `act` → `validate` → `done | ask | observe`.
- Правила: максимум 2 раунда `ask` на запрос; `done=true` — только при верификации результата; level2 действия — с двойным подтверждением.
- Логи событий: `loop_iteration`, `ask_prompt`, `user_answer`, `planner_prompt/response`, `replan`.

### MCP сервер: расширения для MVP‑1
- TTS: `tts_speak(text, voice='default', rate=1.0)`, `tts_stop()` на основе macOS `say`.
- Нумерация: `browser_list_interactives/overlay_show/overlay_hide/overlay_act` с пагинацией; фоллбеки через `browser_find`.

### Безопасность и подтверждения
- Whitelist: проверка хоста при `browser.navigate`.
- Уровни подтверждения (для MVP‑1):
  - level0 — navigate, extract, list_interactives, overlay_show/hide, screenshot.
  - level1 — click/type/select/press/scroll/open_in_new_tab/switch_tab.
  - level2 — upload/download (по подтверждению), переход на внешние домены вне whitelist.

### Логирование и приватность
- `events.jsonl`: `planner_prompt`, `planner_response`, `ask_prompt`, `user_answer`, `loop_iteration`, `tool_call`, `tool_result`, `error`, `auto_enter`, `auto_enter_fallback`.
- Метаданные: версии, длительности, ретраи, уровень подтверждений. По умолчанию — локально, PII маскированы.
- Opt‑in метрики (агрегаты успех/ошибки/время), отправка раз в сутки с джиттером; офлайн‑кэш; бэкоф.

### Тесты/Демо (браузер + TTS/PTT)
- A: «Открой сайт и дай сводку» → navigate/close_banners/extract → done.
- B: «Найди на YouTube хип‑хоп и запусти видео» → enumerate/overlay_act(type)/press Enter/overlay_act(click) → done.
- C: «Добавь товар в корзину» → поиск/клик по номеру/подтверждение → done.
- Озвучка: прогресс/ask/done слышны; barge‑in работает. PTT: ввод цели/ответа голосом.

### DoD и метрики MBP‑1
- DoD: 3 сценария работают от натуральной команды; ≤2 уточнения; план соответствует схеме; whitelist и подтверждения соблюдены; логи полные.
- Метрики: успех ≥85%; среднее время <3–5 мин/сценарий; ≤1 перезапрос/команда.

### План работ (ориентир 1 неделя)
- День 1: Харденинг MCP (браузер) — close_banners (фреймы+shadow, 2–3 прохода, бюджет), детерминированная нумерация/пере‑нумерация, ответы/тайм‑ауты/ретраи/health‑check, SPA fallback wait(ms≈4000).
- День 2: Оркестратор (SYSTEM PROMPT, 1 шаг = 1 вызов, пауза 4с, фоллбеки, ask/done), LLM‑summary.
- День 3: TTS (tts_speak/tts_stop, озвучка прогресса/ask/done, barge‑in).
- День 4: PTT beta (запись, ASR, ввод цели/ответа), e2e на 10+ сайтах.
- День 5: Негативные кейсы, полировка, финальные прогоны.

### Браузерные доработки (MVP‑1)
- `browser_find(role?, text?, limit?, offset?)`, `browser_download_wait(timeout_ms?)`.
- `browser_focus_next/prev(role?)` (по возможности), усиление `close_banners` (shadow DOM, повторные проходы), детерминированная нумерация.

### Онбординг и доступность
- Первый запуск: авто‑проверка/установка Chromium (progress bar), краткие хоткеи, политика приватности.
- Хоткеи: 1–9 (act_by_index), Enter/Esc, Tab/Shift+Tab. Подсказка в UI.

### Команды и переменные окружения
- MCP сервер: `source .venv/bin/activate && mcp run mcp_server.py`
- Оркестратор (пример):
```bash
export MODEL=gpt-4o-mini
export API_KEY=...
python3 orchestrator_mbp0.py --use-llm-planner --command "Открой пример и дай сводку" --auto-yes
```

### Поставка MVP‑1 (конечный результат)
- Что отдаём: .app (DevID + notarization), окно со статусом/логом и списком элементов страницы с номерами; горячие клавиши (1–9, Enter, Esc, Tab/Shift+Tab); первый запуск устанавливает Playwright Chromium при необходимости.
- Внутри: встроенный MCP‑сервер (Python), `mcp_server.py`, локальные логи в `~/Library/Application Support/<App>/agent_runs/`.
- Разрешения: Network Client, Microphone (PTT), Speech Recognition (если Apple Speech), Accessibility, при необходимости Screen Recording. Hardened Runtime включён.
- Сборка: Xcode/SwiftUI оболочка, запуск MCP‑сервера как подпроцесса, проверка движка на старте (`playwright install chromium`).

### Критерии приёмки MVP‑1 (.app)
- Установка: двойной клик → первый запуск без терминала; онбординг; авто‑установка движка проходит.
- Доступность: VoiceOver корректно читает UI; клавиатура управляет действиями по номерам.
- Сценарии: «сводка сайта», «поиск и запуск видео на YouTube», «добавление товара в корзину» выполняются из UI.
- Логи: события записываются локально; ошибки понятны пользователю.

### Поставка и обновления
- Канал: GitHub Releases (DMG/ZIP), страница загрузки (GitHub Pages). Sparkle auto‑update (EdDSA), notarization.

### Уточнённые MCP‑эндпоинты (только MVP‑1)
```json
{
  "browser.navigate": { "url": "string" },
  "browser.wait": { "network_idle": true, "ms": 4000 },
  "browser.list_interactives": { "scope": "viewport|section", "limit": 30 },
  "browser.overlay_show": { "items": [{ "id": "string", "index": 1 }], "scheme": "default|high-contrast" },
  "browser.overlay_hide": {},
  "browser.overlay_act": { "index": 1, "action": "click|type|select", "text": "string" },
  "browser.find": { "role": "string", "text": "string", "limit": 10, "offset": 0 },
  "browser.act": { "id": "string", "action": "click|type|select", "text": "string" },
  "browser.press": { "key": "Enter|Tab|Escape|ArrowDown|..." },
  "browser.scroll": { "direction": "top|bottom", "deltaX": 0, "deltaY": 0 },
  "browser.extract": { "mode": "summary|raw" },
  "browser.open_in_new_tab": { "id": "string" },
  "browser.switch_tab": { "index": 0 },
  "browser.screenshot": { "full_page": false },
  "browser.download_wait": { "timeout_ms": 30000 },

  "tts.speak": { "text": "string", "voice": "string", "rate": 1.0 },
  "tts.stop": {}
}
```

### Поставка браузерного движка (Chromium/Playwright)
- Встроить Chromium в сборку ИЛИ авто‑устанавливать при первом запуске (`playwright install chromium`) в `~/Library/Caches/ms-playwright`.
- Опционально: при наличии системного Google Chrome — подключаться через CDP; fallback — Playwright Chromium.
- MAS (Store) отложить: Sandbox ограничивает Playwright/Apple Events.

### Что уже сделано (браузер MCP)
- Реализовано: navigate/show_overlay, wait(selector/networkidle/timeout), list_interactives (в т.ч. во фреймах), act_by_index (click/type/select), press, scroll(top/bottom/Δ), extract(summary с ретраями), overlay_show/overlay_hide, history (back/forward/reload), вкладки (open_in_new_tab + switch_tab), upload (set_input_files). Фиксы гонок навигации и прокрутки по дельте.
- Тесты: `scripts/test_browser_suite.py` покрывает ввод/выбор/вкладки/загрузку. CLI: `scripts/mcp_call.py`.

### Что планируем (ближайшие 3–5 дней)
- Браузер: `browser_find`, `browser_download_wait`, усиление `close_banners`/shadow DOM; стабилизация SPA‑ожиданий; детерминированная нумерация.
- Оркестратор: strict SYSTEM PROMPT, 1 шаг = 1 вызов, пауза 4с, numeric‑first, фоллбеки, ask/done, LLM‑summary.
- Тесты: e2e на 10+ сайтах (YouTube, Wikipedia, e‑commerce), негативные кейсы.

### Чек‑лист запуска работ
- [ ] `browser_find` готов, покрыт тестами
- [ ] `browser_download_wait` готов, покрыт тестами
- [ ] `close_banners` усилен, работает пост‑hook с бюджетами
- [ ] Нумерация детерминирована, повторяется после изменений DOM
- [ ] Ожидания SPA корректны (fallback ms)
- [ ] Ответы инструментов унифицированы (`status/error/data`)
- [ ] Тайм‑ауты/ретраи/health‑check включены
- [ ] E2E на 10+ сайтах зелёные

### Политики (policies.yml)
- Домены: allow/deny для `browser.navigate`.
- Подтверждения: level0/1/2 — см. раздел «Безопасность и подтверждения».
- Dry‑run: озвучивать план перед потенциально нежелательными действиями.

### Экстренный стоп
- Горячие клавиши: Esc и Cmd+. — мгновенная отмена текущих действий и озвучки.
