# DOM Analyzer

Пакет для анализа DOM через Chrome DevTools Protocol (CDP) и Accessibility Tree. Реализует индексированный подход browser-use для взаимодействия с веб-страницами.

## 🎯 Назначение

DOM Analyzer предоставляет инструменты для:
- Подключения к Chrome через CDP
- Анализа Accessibility Tree
- Индексации элементов страницы
- Создания стабильных индексов для взаимодействия

## 🏗️ Архитектура

### Основные компоненты:

1. **CDPClient** - клиент для работы с Chrome DevTools Protocol
2. **AccessibilityParser** - парсер Accessibility Tree
3. **ElementIndexer** - система индексации элементов
4. **DOMAnalyzer** - основной класс для анализа страниц

### Типы данных:

- **IndexedElement** - индексированный элемент страницы
- **PageState** - состояние страницы с элементами
- **AccessibilityNode** - узел Accessibility Tree
- **ElementRole** - роли элементов (button, link, textbox, etc.)
- **ElementState** - состояния элементов (visible, disabled, etc.)

## 🚀 Установка

```bash
# Установка зависимостей
pip install -r requirements.txt

# Или установка через pip
pip install -e .
```

## 📖 Использование

### Базовый пример:

```python
from dom_analyzer import DOMAnalyzer

# Создание анализатора
analyzer = DOMAnalyzer()

# Анализ страницы
page_state = await analyzer.analyze_page()

# Получение индексированных элементов
for element in page_state.elements:
    print(f"[{element.index}] {element.role}: {element.text}")
```

### Интерактивные элементы:

```python
# Получение только интерактивных элементов
interactive_elements = [
    element for element in page_state.elements 
    if element.is_interactive
]

# Клик по элементу по индексу
await analyzer.click_element(interactive_elements[0].index)
```

## ⚙️ Конфигурация

### Переменные окружения:

```bash
# CDP настройки
export CDP_PORT=9222
export CDP_CONNECTION_TIMEOUT=10000
export CDP_COMMAND_TIMEOUT=30000

# Accessibility настройки
export MIN_TEXT_LENGTH=1
export MAX_TEXT_LENGTH=500

# Кэширование
export ENABLE_CACHING=true
export CACHE_DURATION=30

# Отладка
export DEBUG=true
export LOG_LEVEL=DEBUG
```

### Программная конфигурация:

```python
from dom_analyzer.config import DOMAnalyzerConfig, CDPConfig

config = DOMAnalyzerConfig()
config.cdp.connection_timeout = 15000
config.cdp.default_port = 9223

analyzer = DOMAnalyzer(config=config)
```

## 🔧 Разработка

### Структура проекта:

```
dom_analyzer/
├── __init__.py          # Основной пакет
├── types.py             # Типы данных
├── config.py            # Конфигурация
├── cdp_client.py        # CDP клиент
├── accessibility_parser.py  # Парсер Accessibility Tree
├── element_indexer.py   # Система индексации
├── dom_analyzer.py      # Основной класс
├── requirements.txt     # Зависимости
└── README.md           # Документация
```

### Запуск тестов:

```bash
# Установка тестовых зависимостей
pip install -r requirements.txt

# Запуск тестов
pytest tests/
```

## 📚 API Reference

### DOMAnalyzer

Основной класс для анализа страниц.

#### Методы:

- `analyze_page()` - анализ текущей страницы
- `get_element_by_index(index)` - получение элемента по индексу
- `click_element(index)` - клик по элементу
- `type_text(index, text)` - ввод текста в элемент
- `get_interactive_elements()` - получение интерактивных элементов

### CDPClient

Клиент для работы с Chrome DevTools Protocol.

#### Методы:

- `connect(port)` - подключение к Chrome
- `get_dom_tree()` - получение DOM дерева
- `get_accessibility_tree()` - получение Accessibility Tree
- `execute_script(script)` - выполнение JavaScript

## 🐛 Отладка

### Включение отладки:

```python
import logging
logging.basicConfig(level=logging.DEBUG)

# Или через переменную окружения
export DEBUG=true
```

### Логирование:

```python
from loguru import logger

logger.debug("Подключение к CDP...")
logger.info("Страница проанализирована")
logger.warning("Элемент не найден")
logger.error("Ошибка подключения к CDP")
```

## 🤝 Вклад в проект

1. Форкните репозиторий
2. Создайте ветку для новой функции
3. Внесите изменения
4. Добавьте тесты
5. Создайте Pull Request

## 📄 Лицензия

MIT License - см. файл LICENSE для деталей.

## 🆘 Поддержка

При возникновении проблем:
1. Проверьте документацию
2. Посмотрите issues на GitHub
3. Создайте новый issue с описанием проблемы
