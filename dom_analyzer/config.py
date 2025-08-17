"""
Конфигурация DOM Analyzer

Настройки для работы с CDP, таймауты, лимиты и другие параметры.
"""

import os
from typing import Dict, Any
from dataclasses import dataclass, field


@dataclass
class CDPConfig:
    """Конфигурация CDP клиента"""
    # Таймауты
    connection_timeout: int = 10000  # мс
    command_timeout: int = 30000     # мс
    
    # Параметры подключения
    default_port: int = 9222
    localhost_only: bool = True
    
    # Лимиты
    max_nodes_per_request: int = 1000
    max_depth: int = 10


@dataclass
class AccessibilityConfig:
    """Конфигурация Accessibility Tree"""
    # Фильтрация элементов
    min_text_length: int = 1
    max_text_length: int = 500
    
    # Роли для интерактивных элементов
    interactive_roles: set = field(default_factory=lambda: {
        'button', 'link', 'textbox', 'checkbox', 'radio',
        'combobox', 'listbox', 'menu', 'menuitem', 'tab',
        'dialog', 'alert', 'toolbar', 'grid', 'gridcell'
    })


@dataclass
class IndexingConfig:
    """Конфигурация индексации элементов"""
    # Стратегия индексации
    use_stable_indices: bool = True
    cache_duration: int = 30  # секунды
    
    # Лимиты
    max_elements: int = 1000
    max_interactive: int = 200


@dataclass
class DOMAnalyzerConfig:
    """Основная конфигурация DOM Analyzer"""
    cdp: CDPConfig = field(default_factory=CDPConfig)
    accessibility: AccessibilityConfig = field(default_factory=AccessibilityConfig)
    indexing: IndexingConfig = field(default_factory=IndexingConfig)
    
    # Общие настройки
    debug: bool = False
    log_level: str = "INFO"
    
    # Кэширование
    enable_caching: bool = True
    cache_size: int = 100


def load_config_from_env() -> DOMAnalyzerConfig:
    """Загрузка конфигурации из переменных окружения"""
    config = DOMAnalyzerConfig()
    
    # CDP настройки
    if os.getenv("CDP_CONNECTION_TIMEOUT"):
        config.cdp.connection_timeout = int(os.getenv("CDP_CONNECTION_TIMEOUT"))
    
    if os.getenv("CDP_COMMAND_TIMEOUT"):
        config.cdp.command_timeout = int(os.getenv("CDP_COMMAND_TIMEOUT"))
    
    if os.getenv("CDP_PORT"):
        config.cdp.default_port = int(os.getenv("CDP_PORT"))
    
    # Accessibility настройки
    if os.getenv("MIN_TEXT_LENGTH"):
        config.accessibility.min_text_length = int(os.getenv("MIN_TEXT_LENGTH"))
    
    if os.getenv("MAX_TEXT_LENGTH"):
        config.accessibility.max_text_length = int(os.getenv("MAX_TEXT_LENGTH"))
    
    # Индексация
    if os.getenv("ENABLE_CACHING"):
        config.enable_caching = os.getenv("ENABLE_CACHING").lower() == "true"
    
    if os.getenv("CACHE_DURATION"):
        config.indexing.cache_duration = int(os.getenv("CACHE_DURATION"))
    
    # Отладка
    if os.getenv("DEBUG"):
        config.debug = os.getenv("DEBUG").lower() == "true"
    
    if os.getenv("LOG_LEVEL"):
        config.log_level = os.getenv("LOG_LEVEL")
    
    return config


# Глобальная конфигурация по умолчанию
DEFAULT_CONFIG = DOMAnalyzerConfig()
