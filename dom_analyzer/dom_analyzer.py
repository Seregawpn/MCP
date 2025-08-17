"""
DOM Analyzer

Основной анализатор DOM, объединяющий CDP клиент, Accessibility Parser
и систему индексации для получения состояния страницы.
"""

import asyncio
import logging
import time
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass

from .cdp_client import CDPClient, CDPSession
from .accessibility_parser import AccessibilityParser
from .element_indexer import ElementIndexer
from .types import (
    AccessibilityNode, IndexedElement, ElementRole, ElementState,
    PageState, CDPResponse
)
from .config import DOMAnalyzerConfig


@dataclass
class PageAnalysisResult:
    """Результат анализа страницы"""
    target_id: str
    timestamp: float
    url: str
    title: str
    accessibility_nodes: List[AccessibilityNode]
    indexed_elements: List[IndexedElement]
    interactive_elements: List[IndexedElement]
    page_metrics: Optional[Dict[str, Any]]
    dom_hash: str
    analysis_time: float
    total_elements: int
    interactive_count: int


@dataclass
class ElementInteractionInfo:
    """Информация об элементе для взаимодействия"""
    index: int
    role: str
    text: str
    tag_name: str
    xpath: str
    is_interactive: bool
    states: List[str]
    attributes: Dict[str, str]
    bounding_box: Optional[Dict[str, int]]


class DOMAnalyzer:
    """Основной анализатор DOM"""
    
    def __init__(self, config: Optional[DOMAnalyzerConfig] = None):
        self.config = config or DOMAnalyzerConfig()
        self.logger = logging.getLogger("DOMAnalyzer")
        
        # Компоненты анализатора
        self.cdp_client = CDPClient(self.config.cdp)
        self.accessibility_parser = AccessibilityParser(self.config.accessibility)
        self.element_indexer = ElementIndexer(self.config)
        
        # Кэш результатов анализа
        self._analysis_cache: Dict[str, PageAnalysisResult] = {}
        self._last_analysis_time: Dict[str, float] = {}
        
        # Статистика
        self._analysis_stats = {
            'total_analyses': 0,
            'cache_hits': 0,
            'cache_misses': 0,
            'total_analysis_time': 0.0
        }
    
    async def analyze_page(self, target_id: str, force_refresh: bool = False) -> PageAnalysisResult:
        """Анализ страницы и получение состояния"""
        start_time = time.time()
        
        try:
            self.logger.info(f"Starting page analysis for target {target_id}")
            
            # Проверяем кэш
            if not force_refresh and self._should_use_cached_result(target_id):
                self._analysis_stats['cache_hits'] += 1
                cached_result = self._analysis_cache[target_id]
                self.logger.info(f"Using cached analysis result for target {target_id}")
                return cached_result
            
            self._analysis_stats['cache_misses'] += 1
            
            # Подключаемся к CDP если не подключены
            if not self.cdp_client.is_connected():
                await self._ensure_cdp_connection()
            
            # Получаем информацию о странице
            page_info = await self._get_page_info(target_id)
            
            # Получаем Accessibility Tree
            accessibility_tree = await self._get_accessibility_tree(target_id)
            
            # Парсим Accessibility Tree
            accessibility_nodes = self.accessibility_parser.parse_accessibility_tree(accessibility_tree)
            
            # Индексируем элементы
            indexed_elements = self.element_indexer.index_elements(accessibility_nodes)
            
            # Фильтруем интерактивные элементы
            interactive_elements = self.element_indexer.get_interactive_elements()
            
            # Получаем метрики страницы
            page_metrics = await self._get_page_metrics(target_id)
            
            # Вычисляем хеш DOM
            dom_hash = self._calculate_dom_hash(accessibility_nodes, indexed_elements)
            
            # Создаем результат анализа
            analysis_time = time.time() - start_time
            result = PageAnalysisResult(
                target_id=target_id,
                timestamp=start_time,
                url=page_info.get('url', ''),
                title=page_info.get('title', ''),
                accessibility_nodes=accessibility_nodes,
                indexed_elements=indexed_elements,
                interactive_elements=interactive_elements,
                page_metrics=page_metrics,
                dom_hash=dom_hash,
                analysis_time=analysis_time,
                total_elements=len(indexed_elements),
                interactive_count=len(interactive_elements)
            )
            
            # Сохраняем в кэш
            self._analysis_cache[target_id] = result
            self._last_analysis_time[target_id] = start_time
            
            # Обновляем статистику
            self._update_analysis_stats(analysis_time)
            
            self.logger.info(f"Page analysis completed for target {target_id} in {analysis_time:.3f}s. "
                           f"Found {len(indexed_elements)} elements, {len(interactive_elements)} interactive")
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error during page analysis for target {target_id}: {e}")
            raise
    
    async def get_page_state(self, target_id: str) -> PageState:
        """Получение состояния страницы в формате PageState"""
        try:
            # Анализируем страницу
            analysis_result = await self.analyze_page(target_id)
            
            # Конвертируем в PageState
            page_state = PageState(
                url=analysis_result.url,
                title=analysis_result.title,
                elements=analysis_result.indexed_elements,
                timestamp=analysis_result.timestamp,
                interactive_count=analysis_result.interactive_count,
                dom_hash=analysis_result.dom_hash
            )
            
            return page_state
            
        except Exception as e:
            self.logger.error(f"Error getting page state for target {target_id}: {e}")
            raise
    
    async def get_interactive_elements(self, target_id: str) -> List[ElementInteractionInfo]:
        """Получение интерактивных элементов для взаимодействия"""
        try:
            # Анализируем страницу
            analysis_result = await self.analyze_page(target_id)
            
            # Конвертируем в ElementInteractionInfo
            interaction_elements = []
            for element in analysis_result.interactive_elements:
                interaction_info = ElementInteractionInfo(
                    index=element.index,
                    role=element.role.value,
                    text=element.text,
                    tag_name=element.tag_name,
                    xpath=element.xpath,
                    is_interactive=element.is_interactive,
                    states=[state.value for state in element.states],
                    attributes=element.attributes,
                    bounding_box=element.bounding_box
                )
                interaction_elements.append(interaction_info)
            
            return interaction_elements
            
        except Exception as e:
            self.logger.error(f"Error getting interactive elements for target {target_id}: {e}")
            raise
    
    async def find_element_by_text(self, target_id: str, text: str, 
                                  role: Optional[ElementRole] = None) -> Optional[ElementInteractionInfo]:
        """Поиск элемента по тексту"""
        try:
            # Получаем интерактивные элементы
            interactive_elements = await self.get_interactive_elements(target_id)
            
            # Ищем элемент по тексту
            for element in interactive_elements:
                if text.lower() in element.text.lower():
                    if role is None or element.role == role.value:
                        return element
            
            return None
            
        except Exception as e:
            self.logger.error(f"Error finding element by text '{text}' for target {target_id}: {e}")
            return None
    
    async def find_element_by_role(self, target_id: str, role: ElementRole) -> List[ElementInteractionInfo]:
        """Поиск элементов по роли"""
        try:
            # Получаем интерактивные элементы
            interactive_elements = await self.get_interactive_elements(target_id)
            
            # Фильтруем по роли
            role_elements = [elem for elem in interactive_elements if elem.role == role.value]
            
            return role_elements
            
        except Exception as e:
            self.logger.error(f"Error finding elements by role '{role.value}' for target {target_id}: {e}")
            return []
    
    async def get_element_by_index(self, target_id: str, index: int) -> Optional[ElementInteractionInfo]:
        """Получение элемента по индексу"""
        try:
            # Получаем интерактивные элементы
            interactive_elements = await self.get_interactive_elements(target_id)
            
            # Ищем по индексу
            for element in interactive_elements:
                if element.index == index:
                    return element
            
            return None
            
        except Exception as e:
            self.logger.error(f"Error getting element by index {index} for target {target_id}: {e}")
            return None
    
    async def wait_for_element(self, target_id: str, text: str, timeout: int = 10000) -> Optional[ElementInteractionInfo]:
        """Ожидание появления элемента на странице"""
        start_time = time.time()
        
        try:
            while (time.time() - start_time) * 1000 < timeout:
                # Анализируем страницу
                analysis_result = await self.analyze_page(target_id, force_refresh=True)
                
                # Ищем элемент
                element = await self.find_element_by_text(target_id, text)
                if element:
                    return element
                
                # Ждем немного перед следующей попыткой
                await asyncio.sleep(0.5)
            
            self.logger.warning(f"Element with text '{text}' not found within {timeout}ms for target {target_id}")
            return None
            
        except Exception as e:
            self.logger.error(f"Error waiting for element '{text}' for target {target_id}: {e}")
            return None
    
    async def get_page_summary(self, target_id: str) -> Dict[str, Any]:
        """Получение краткого описания страницы"""
        try:
            # Анализируем страницу
            analysis_result = await self.analyze_page(target_id)
            
            # Создаем краткое описание
            summary = {
                'url': analysis_result.url,
                'title': analysis_result.title,
                'total_elements': analysis_result.total_elements,
                'interactive_elements': analysis_result.interactive_count,
                'dom_hash': analysis_result.dom_hash,
                'analysis_time': analysis_result.analysis_time,
                'timestamp': analysis_result.timestamp
            }
            
            # Добавляем статистику по ролям
            role_stats = {}
            for element in analysis_result.indexed_elements:
                role = element.role.value
                if role not in role_stats:
                    role_stats[role] = 0
                role_stats[role] += 1
            
            summary['role_distribution'] = role_stats
            
            return summary
            
        except Exception as e:
            self.logger.error(f"Error getting page summary for target {target_id}: {e}")
            raise
    
    async def _ensure_cdp_connection(self):
        """Обеспечение подключения к CDP"""
        try:
            if not self.cdp_client.is_connected():
                self.logger.info("Connecting to CDP...")
                response = await self.cdp_client.connect(self.config.cdp.default_port)
                
                if not response.success:
                    raise Exception(f"Failed to connect to CDP: {response.error}")
                
                self.logger.info("CDP connection established")
        except Exception as e:
            self.logger.error(f"Error ensuring CDP connection: {e}")
            raise
    
    async def _get_page_info(self, target_id: str) -> Dict[str, Any]:
        """Получение базовой информации о странице"""
        try:
            # Получаем информацию о вкладке
            targets_response = await self.cdp_client.get_targets()
            if not targets_response.success:
                raise Exception(f"Failed to get targets: {targets_response.error}")
            
            # Ищем нужную вкладку
            target_info = None
            for target in targets_response.data.get('targets', []):
                if target.get('id') == target_id:
                    target_info = target
                    break
            
            if not target_info:
                raise Exception(f"Target {target_id} not found")
            
            return {
                'url': target_info.get('url', ''),
                'title': target_info.get('title', ''),
                'type': target_info.get('type', '')
            }
            
        except Exception as e:
            self.logger.error(f"Error getting page info for target {target_id}: {e}")
            raise
    
    async def _get_accessibility_tree(self, target_id: str) -> Dict[str, Any]:
        """Получение Accessibility Tree"""
        try:
            response = await self.cdp_client.get_accessibility_tree(target_id)
            if not response.success:
                raise Exception(f"Failed to get accessibility tree: {response.error}")
            
            return response.data.get('accessibility_tree', {})
            
        except Exception as e:
            self.logger.error(f"Error getting accessibility tree for target {target_id}: {e}")
            raise
    
    async def _get_page_metrics(self, target_id: str) -> Optional[Dict[str, Any]]:
        """Получение метрик страницы"""
        try:
            response = await self.cdp_client.get_page_metrics(target_id)
            if response.success:
                return response.data.get('page_metrics')
            return None
            
        except Exception as e:
            self.logger.warning(f"Error getting page metrics for target {target_id}: {e}")
            return None
    
    def _calculate_dom_hash(self, accessibility_nodes: List[AccessibilityNode], 
                           indexed_elements: List[IndexedElement]) -> str:
        """Вычисление хеша DOM для кэширования"""
        import hashlib
        
        # Создаем строку для хеширования
        hash_string = ""
        
        # Добавляем информацию об Accessibility узлах
        for node in accessibility_nodes:
            node_info = f"{node.node_id}:{node.role}:{node.name}:{node.value}"
            hash_string += node_info + "|"
        
        # Добавляем информацию об индексированных элементах
        for element in indexed_elements:
            element_info = f"{element.index}:{element.role.value}:{element.text}"
            hash_string += element_info + "|"
        
        # Создаем MD5 хеш
        return hashlib.md5(hash_string.encode()).hexdigest()
    
    def _should_use_cached_result(self, target_id: str) -> bool:
        """Определение, нужно ли использовать кэшированный результат"""
        if target_id not in self._analysis_cache:
            return False
        
        if target_id not in self._last_analysis_time:
            return False
        
        # Проверяем время жизни кэша
        cache_age = time.time() - self._last_analysis_time[target_id]
        max_cache_age = self.config.indexing.cache_duration
        
        return cache_age < max_cache_age
    
    def _update_analysis_stats(self, analysis_time: float):
        """Обновление статистики анализа"""
        self._analysis_stats['total_analyses'] += 1
        self._analysis_stats['total_analysis_time'] += analysis_time
    
    def get_analysis_stats(self) -> Dict[str, Any]:
        """Получение статистики анализа"""
        stats = self._analysis_stats.copy()
        
        if stats['total_analyses'] > 0:
            stats['average_analysis_time'] = stats['total_analysis_time'] / stats['total_analyses']
            stats['cache_hit_rate'] = stats['cache_hits'] / (stats['cache_hits'] + stats['cache_misses'])
        else:
            stats['average_analysis_time'] = 0.0
            stats['cache_hit_rate'] = 0.0
        
        return stats
    
    def clear_cache(self, target_id: Optional[str] = None):
        """Очистка кэша анализа"""
        if target_id:
            if target_id in self._analysis_cache:
                del self._analysis_cache[target_id]
            if target_id in self._last_analysis_time:
                del self._last_analysis_time[target_id]
            self.logger.info(f"Cleared cache for target {target_id}")
        else:
            self._analysis_cache.clear()
            self._last_analysis_time.clear()
            self.logger.info("Cleared all analysis cache")
    
    async def close(self):
        """Закрытие анализатора"""
        try:
            await self.cdp_client.disconnect()
            self.logger.info("DOM Analyzer closed")
        except Exception as e:
            self.logger.error(f"Error closing DOM Analyzer: {e}")
    
    async def __aenter__(self):
        """Асинхронный контекстный менеджер - вход"""
        return self
    
    async def __aexit__(self, exc_type, exc_value, traceback):
        """Асинхронный контекстный менеджер - выход"""
        await self.close()
