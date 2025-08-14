## MBP‑0 — Основа и безопасность: план мини‑проекта

### Цели и рамки
- Единый сквозной поток: команда → план (dry‑run) → подтверждение → выполнение → итог.
- Безопасность: whitelist доменов/операций, двойные подтверждения для рискованных шагов, undo (где возможно).
- Приватность: локальная обработка по умолчанию, явные предупреждения при сетевых запросах.
- Инженерные основы: логи JSONL, таймауты и ретраи, понятные ошибки, конфиги.
- Вне рамок: голос, чтение экрана, 2FA/сложные формы, внешние мессенджеры (кроме заготовки контрактов).

### Статус на сейчас
- MCP SDK установлен; сервер `mcp_server.py` с инструментами: `browser_navigate`, `browser_close_banners`, `browser_extract`, `files_search`, `files_read_text`.
- Оркестратор `orchestrator_mbp0.py` переводён на MCP‑клиент (stdio), есть стадии plan → confirm → execute; логи в `agent_runs/<uuid>/`.
- Whitelist: парсинг host в `browser.navigate`, логирование решения (`security_evaluation`), блокировка при deny. Сейчас `allow: ["*"]`.
- Таймауты/ретраи с backoff добавлены для всех `browser.*`/`files.*` вызовов; fallback для будущих `click/type` (close_banners + повтор).
- Конфиги: `config/security.yml`, `config/timeouts.yml`.
- Демо‑скрипт обновлён: `scripts/run_demo_mbp0.sh` запускает два сквозных сценария через оркестратор.
- README добавлен с командами запуска MBP‑0.
- Сквозные прогоны прошли (browser summary, files read); артефакты логов на месте.

### Пользовательский поток и состояния
- Состояния: idle → parsed → planned → awaiting_confirm → executing → reported.
- Поток: ввод команды (CLI) → краткий план действий → запрос подтверждения → вызовы MCP → краткий итог + 2–3 следующих шага.

### Контракты MCP (используемые в MBP‑0)
- Браузер: `browser.navigate` → `browser_navigate`; `browser.close_banners` → `browser_close_banners`; `browser.extract(mode=summary)` → `browser_extract`.
- Файлы: `files.search` → `files_search`, `files.read_text` → `files_read_text`.
- Приложения (заготовка): `apps.launch`, `apps.activate` (не реализовано в MBP‑0).

### Архитектура
- Оркестратор (Python): parser → planner → confirmer → executor → reporter.
- MCP сервер: FastMCP поверх стабов в `tools/`.

### Безопасность: Whitelist и уровни подтверждения
- Whitelist доменов: host‑проверка при `browser.navigate`, логирование решения; текущая политика — `allow: ["*"]`.
- Уровни подтверждения: поддержка уровня плана сохранена (строгие правила перенесём на будущие рискованные операции).

### Логирование и трассировка
- Формат: JSONL `agent_runs/<uuid>/events.jsonl` + `meta.json`.
- События: command_received, plan_created, security_evaluation, confirmation_requested, tool_call, tool_result, retry/retry_fallback, error, summary.

### Таймауты и ретраи (актуально)
- Используются значения из `config/timeouts.yml`; backoff по схеме 0.5s → 1.0s → 1.5s.

### Обработка ошибок
- Классы ошибок зарезервированы; нормализация сообщений выполнена для таймаута/неизвестной ошибки. Расширение под `click/type` в MBP‑1.

### Тесты и демо
- Smoke A (браузер): navigate → close_banners → extract(summary).
- Smoke B (файлы): files.search → read_text на `MBP-0 план.md`.
- Скрипт: `scripts/run_demo_mbp0.sh`.

### Команды запуска (актуальные)
- MCP сервер:
```bash
source .venv/bin/activate
mcp run mcp_server.py
```
- Оркестратор:
```bash
python3 orchestrator_mbp0.py --command "browser: summary https://example.com" --auto-yes
python3 orchestrator_mbp0.py --command "files: MBP-0 план.md" --auto-yes
```

### DoD и метрики MBP‑0 (выполнено)
- Сквозной поток с подтверждениями реализован.
- Логи JSONL и метаданные корректны.
- Whitelist‑проверка и логирование решений включены; блокировка при deny поддерживается.
- Таймауты/ретраи применяются; smoke‑сценарии проходят стабильно.

### Риски и смягчения
- Разрешения macOS (Automation/Accessibility): не требуются на этом этапе (MCP + стабы).
- Ломкие селекторы: на MBP‑0 не используются; fallback зарезервирован.

### Итог
- MBP‑0 закрыт. Переходим к MBP‑1 (реальные действия браузера/файлов, iMessage/e‑mail, и нумерация элементов в браузере).
