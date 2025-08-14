## MBP‑1: запуск и проверка (актуально)

### Требования
- Python 3.12+
- Виртуальное окружение (рекомендуется)

### Установка зависимостей
```bash
cd "/Users/sergiyzasorin/Desktop/untitled folder"
python3 -m venv .venv && source .venv/bin/activate
pip install "mcp[cli]"
```

### Запуск MCP сервера (в отдельном терминале)
```bash
source .venv/bin/activate
mcp run mcp_server.py
```

### Запуск оркестратора (сквозные сценарии)
- Браузерная цель (пример):
```bash
python3 orchestrator_mbp1.py --goal "Открой Википедию и дай сводку" --max-steps 10
```
- YouTube (пример):
```bash
python3 orchestrator_mbp1.py --goal "Найди хип-хоп и запусти видео" --max-steps 12
```

### Фича-флаги (опционально через .env)
```bash
NOT_FOUND_RETRIES=2
SEARCH_CLICK_BLOCK_WINDOW_MS=8000
FALLBACK_ON_NOT_FOUND=1
BLOCK_SEARCH_CLICK_AFTER_AUTOENTER=1
OVERLAY_REFRESH_AFTER_CLICK=1
```

### Где логи
- Все события и метаданные пишутся в каталог `agent_runs/<uuid>/`:
  - `events.jsonl` — поток событий (plan/confirm/tool_call/result/error/summary)
  - `meta.json` — метаданные запуска

## Distribution (MVP‑1)
- Канал: GitHub Releases (DMG/ZIP), подписано DevID и нотарифицировано.
- Первый запуск: приложение установит Playwright Chromium при необходимости.
- Обновления: Sparkle позже (beta/stable); пока — ручная переустановка из Releases.

## Privacy & Metrics
- По умолчанию — локальные JSONL‑логи без PII. Кнопки в UI: Open Logs, Export Logs.
- Опционально (выключено по умолчанию): агрегированные метрики успех/ошибки/время (opt‑in), отправка батчами по TLS.
- Периодичность (opt‑in): 1 раз в сутки с джиттером ±2 ч, окно 03:00–05:00; офлайн — отложенная отправка; ретраи с backoff (3 попытки).

### Конфигурация
- Безопасность (whitelist, уровни подтверждений): `config/security.yml`
- Таймауты и ретраи: `config/timeouts.yml`

### Примечания
- Whitelist сейчас разрешает все домены (`allow: ["*"]`), решения логируются.
- Оркестратор вызывает инструменты через MCP (stdio). Стабы из MBP‑0 оставлены как архив и в MBP‑1 не используются.

---

## MBP‑0 (архив)
- Старые команды и стабы сохранены для справки: `orchestrator_mbp0.py`, `scripts/run_demo_mbp0.sh`, `tools/browser_stub.py`, `tools/files_stub.py`.

### Браузерный тестовый набор (MVP)
- Комплексный прогон браузерных возможностей (navigate/wait/list/act/press/scroll/extract/overlay/history/tabs/upload):
```bash
source .venv/bin/activate
python3 scripts/test_browser_suite.py
```
Результаты печатаются в stdout; при необходимости можно повторить прогон.
