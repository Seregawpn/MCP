"""
Element Indexer

Система индексации элементов для создания стабильных индексов
для взаимодействия с веб-страницами.
"""

import hashlib
import logging
import time
from typing import Dict, List, Any, Optional, Set, Tuple
from dataclasses import dataclass, field
from collections import defaultdict

from .types import AccessibilityNode, IndexedElement, ElementRole, ElementState
from .config import DOMAnalyzerConfig


@dataclass
class IndexedNode:
    """Индексированный узел с дополнительной информацией"""
    node: AccessibilityNode
    index: int
    parent_index: Optional[int]
    children_indices: List[int] = field(default_factory=list)
    depth: int = 0
    is_new: bool = False
    bounding_box: Optional[Dict[str, int]] = None
    xpath: str = ""
    tag_name: str = ""
    attributes: Dict[str, str] = field(default_factory=dict)
    is_interactive: bool = False
    interactive_type: str = ""


@dataclass
class IndexingContext:
    """Контекст индексации для отслеживания состояния"""
    timestamp: float
    dom_hash: str
    total_elements: int
    interactive_elements: int
    new_elements: int
    removed_elements: int


class ElementIndexer:
    """Система индексации элементов"""
    
    def __init__(self, config: Optional[DOMAnalyzerConfig] = None):
        self.config = config or DOMAnalyzerConfig()
        self.logger = logging.getLogger("ElementIndexer")
        
        # Счетчики индексов
        self._element_counter = 0
        
        # Карты индексов
        self._index_to_node: Dict[int, IndexedNode] = {}
        self._node_id_to_index: Dict[int, int] = {}
        self._xpath_to_index: Dict[str, int] = {}
        
        # Кэш для стабильности
        self._previous_indices: Dict[int, int] = {}
        self._previous_xpaths: Dict[str, int] = {}
        
        # Контекст индексации
        self._indexing_context: Optional[IndexingContext] = None
        
        # Статистика
        self._indexing_stats = {
            'total_indexed': 0,
            'interactive_indexed': 0,
            'cached_hits': 0,
            'cache_misses': 0
        }
    
    def index_elements(self, accessibility_nodes: List[AccessibilityNode], 
                      dom_data: Optional[Dict[str, Any]] = None) -> List[IndexedElement]:
        """Индексация элементов из Accessibility Tree"""
        start_time = time.time()
        
        try:
            self.logger.info(f"Starting indexing of {len(accessibility_nodes)} accessibility nodes")
            
            # Создаем контекст индексации
            dom_hash = self._calculate_dom_hash(accessibility_nodes, dom_data)
            self._indexing_context = IndexingContext(
                timestamp=start_time,
                dom_hash=dom_hash,
                total_elements=len(accessibility_nodes),
                interactive_elements=0,
                new_elements=0,
                removed_elements=0
            )
            
            # Сбрасываем счетчики
            self._element_counter = 0
            
            # Очищаем текущие карты
            self._index_to_node.clear()
            self._node_id_to_index.clear()
            self._xpath_to_index.clear()
            
            # Индексируем элементы
            indexed_elements = []
            
            for node in accessibility_nodes:
                indexed_element = self._index_single_node(node, dom_data)
                if indexed_element:
                    indexed_elements.append(indexed_element)
            
            # Обновляем статистику
            self._update_indexing_stats(len(indexed_elements))
            
            # Сохраняем текущие индексы для следующего сравнения
            self._save_current_indices()
            
            elapsed_time = time.time() - start_time
            self.logger.info(f"Indexing completed in {elapsed_time:.3f}s. "
                           f"Indexed {len(indexed_elements)} elements")
            
            return indexed_elements
            
        except Exception as e:
            self.logger.error(f"Error during indexing: {e}")
            return []
    
    def _index_single_node(self, node: AccessibilityNode, 
                          dom_data: Optional[Dict[str, Any]] = None) -> Optional[IndexedElement]:
        """Индексация отдельного узла"""
        try:
            # Проверяем, нужно ли индексировать этот узел
            if not self._should_index_node(node):
                return None
            
            # Определяем тип индекса
            index_type = self._determine_index_type(node)
            
            # Получаем или создаем индекс
            if index_type == "interactive":
                index = self._get_or_create_interactive_index(node)
            else:
                index = self._get_or_create_element_index(node)
            
            # Создаем IndexedNode
            indexed_node = IndexedNode(
                node=node,
                index=index,
                parent_index=self._get_parent_index(node),
                children_indices=self._get_children_indices(node),
                depth=self._calculate_depth(node),
                is_new=self._is_node_new(node),
                bounding_box=self._extract_bounding_box(node, dom_data),
                xpath=self._generate_xpath(node),
                tag_name=self._extract_tag_name(node, dom_data),
                attributes=self._extract_attributes(node, dom_data),
                is_interactive=index_type == "interactive",
                interactive_type=index_type if index_type == "interactive" else ""
            )
            
            # Сохраняем в карты
            self._index_to_node[index] = indexed_node
            self._node_id_to_index[node.node_id] = index
            self._xpath_to_index[indexed_node.xpath] = index
            
            # Конвертируем в IndexedElement
            indexed_element = self._convert_to_indexed_element(indexed_node)
            
            return indexed_element
            
        except Exception as e:
            self.logger.error(f"Error indexing node {node.node_id}: {e}")
            return None
    
    def _should_index_node(self, node: AccessibilityNode) -> bool:
        """Определение, нужно ли индексировать узел"""
        # Игнорируем скрытые узлы
        if node.state.get('hidden', False):
            return False
        
        # Игнорируем узлы без имени и с generic ролью
        if not node.name and node.role == 'generic':
            return False
        
        # Игнорируем узлы с очень длинным текстом
        if node.name and len(node.name) > self.config.accessibility.max_text_length:
            return False
        
        return True
    
    def _determine_index_type(self, node: AccessibilityNode) -> str:
        """Определение типа индекса для узла"""
        # Интерактивные роли
        interactive_roles = {
            'button', 'link', 'textbox', 'checkbox', 'radio',
            'combobox', 'listbox', 'menu', 'menuitem', 'tab',
            'dialog', 'alert', 'toolbar', 'grid', 'gridcell'
        }
        
        if node.role in interactive_roles:
            self.logger.debug(f"Node {node.node_id} ({node.role}) is interactive by role")
            return "interactive"
        
        # Проверяем состояния на интерактивность
        interactive_states = {'clickable', 'pressable', 'selectable', 'focusable'}
        if any(state in node.state for state in interactive_states):
            self.logger.debug(f"Node {node.node_id} ({node.role}) is interactive by state")
            return "interactive"
        
        self.logger.debug(f"Node {node.node_id} ({node.role}) is not interactive")
        return "element"
    
    def _get_or_create_interactive_index(self, node: AccessibilityNode) -> int:
        """Получение или создание интерактивного индекса"""
        # Проверяем кэш по node_id
        if node.node_id in self._node_id_to_index:
            cached_index = self._node_id_to_index[node.node_id]
            if cached_index in self._index_to_node:
                cached_node = self._index_to_node[cached_index]
                if cached_node.is_interactive:
                    self._indexing_stats['cached_hits'] += 1
                    return cached_index
        
        # Создаем новый интерактивный индекс
        new_index = self._element_counter
        self._element_counter += 1
        self._indexing_stats['cache_misses'] += 1
        
        return new_index
    
    def _get_or_create_element_index(self, node: AccessibilityNode) -> int:
        """Получение или создание обычного индекса элемента"""
        # Проверяем кэш по node_id
        if node.node_id in self._node_id_to_index:
            cached_index = self._node_id_to_index[node.node_id]
            if cached_index in self._index_to_node:
                self._indexing_stats['cached_hits'] += 1
                return cached_index
        
        # Создаем новый индекс элемента
        new_index = self._element_counter
        self._element_counter += 1
        self._indexing_stats['cache_misses'] += 1
        
        return new_index
    
    def _get_parent_index(self, node: AccessibilityNode) -> Optional[int]:
        """Получение индекса родительского узла"""
        if node.parent_id is None:
            return None
        
        return self._node_id_to_index.get(node.parent_id)
    
    def _get_children_indices(self, node: AccessibilityNode) -> List[int]:
        """Получение индексов дочерних узлов"""
        children_indices = []
        for child_id in node.children:
            child_index = self._node_id_to_index.get(child_id)
            if child_index is not None:
                children_indices.append(child_index)
        
        return children_indices
    
    def _calculate_depth(self, node: AccessibilityNode) -> int:
        """Вычисление глубины узла в дереве"""
        depth = 0
        current_parent_id = node.parent_id
        
        while current_parent_id is not None:
            depth += 1
            # Находим родительский узел
            parent_index = self._node_id_to_index.get(current_parent_id)
            if parent_index is None:
                break
            
            parent_node = self._index_to_node.get(parent_index)
            if parent_node is None:
                break
            
            current_parent_id = parent_node.node.parent_id
        
        return depth
    
    def _is_node_new(self, node: AccessibilityNode) -> bool:
        """Определение, является ли узел новым"""
        # Проверяем, был ли узел в предыдущей индексации
        if node.node_id in self._previous_indices:
            return False
        
        # Проверяем по XPath
        xpath = self._generate_xpath(node)
        if xpath in self._previous_xpaths:
            return False
        
        return True
    
    def _extract_bounding_box(self, node: AccessibilityNode, 
                             dom_data: Optional[Dict[str, Any]]) -> Optional[Dict[str, int]]:
        """Извлечение координат элемента"""
        # TODO: Реализовать извлечение координат из DOM данных
        # Пока возвращаем None
        return None
    
    def _generate_xpath(self, node: AccessibilityNode) -> str:
        """Генерация XPath для узла"""
        # Простая генерация XPath на основе роли и имени
        parts = []
        
        if node.role and node.role != 'generic':
            parts.append(node.role)
        
        if node.name:
            # Очищаем имя для XPath
            clean_name = node.name.replace('"', '\\"').replace("'", "\\'")
            parts.append(f'[@name="{clean_name}"]')
        
        if node.value:
            clean_value = str(node.value).replace('"', '\\"').replace("'", "\\'")
            parts.append(f'[@value="{clean_value}"]')
        
        if not parts:
            parts.append('generic')
        
        return f"//{parts[0]}{''.join(parts[1:])}"
    
    def _extract_tag_name(self, node: AccessibilityNode, 
                          dom_data: Optional[Dict[str, Any]]) -> str:
        """Извлечение HTML тега"""
        # TODO: Реализовать извлечение тега из DOM данных
        # Пока возвращаем роль
        return node.role or 'generic'
    
    def _extract_attributes(self, node: AccessibilityNode, 
                           dom_data: Optional[Dict[str, Any]]) -> Dict[str, str]:
        """Извлечение HTML атрибутов"""
        attributes = {}
        
        # Добавляем состояния как атрибуты
        for state_name, state_value in node.state.items():
            if state_value is True:
                attributes[state_name] = "true"
            elif state_value is False:
                attributes[state_name] = "false"
        
        # Добавляем основные свойства
        if node.role:
            attributes['role'] = node.role
        
        if node.name:
            attributes['name'] = node.name
        
        if node.value:
            attributes['value'] = str(node.value)
        
        return attributes
    
    def _convert_to_indexed_element(self, indexed_node: IndexedNode) -> IndexedElement:
        """Конвертация IndexedNode в IndexedElement"""
        # Конвертируем состояния в ElementState
        states = []
        for state_name, state_value in indexed_node.node.state.items():
            if state_name in ElementState.__members__:
                try:
                    state_enum = ElementState(state_name)
                    states.append(state_enum)
                except ValueError:
                    # Игнорируем неизвестные состояния
                    pass
        
        return IndexedElement(
            index=indexed_node.index,
            role=ElementRole(indexed_node.node.role) if indexed_node.node.role else ElementRole.GENERIC,
            text=indexed_node.node.name or "",
            tag_name=indexed_node.tag_name,
            attributes=indexed_node.attributes,
            states=states,
            xpath=indexed_node.xpath,
            bounding_box=indexed_node.bounding_box,
            is_interactive=indexed_node.is_interactive,
            parent_index=indexed_node.parent_index,
            children_indices=indexed_node.children_indices
        )
    
    def _calculate_dom_hash(self, nodes: List[AccessibilityNode], 
                           dom_data: Optional[Dict[str, Any]]) -> str:
        """Вычисление хеша DOM для кэширования"""
        # Создаем строку для хеширования
        hash_string = ""
        
        # Добавляем информацию об узлах
        for node in nodes:
            node_info = f"{node.node_id}:{node.role}:{node.name}:{node.value}"
            hash_string += node_info + "|"
        
        # Добавляем DOM данные если есть
        if dom_data:
            hash_string += str(dom_data)
        
        # Создаем MD5 хеш
        return hashlib.md5(hash_string.encode()).hexdigest()
    
    def _update_indexing_stats(self, total_indexed: int):
        """Обновление статистики индексации"""
        self._indexing_stats['total_indexed'] = total_indexed
        
        # Подсчитываем интерактивные элементы
        interactive_count = 0
        for indexed_node in self._index_to_node.values():
            if indexed_node.is_interactive:
                interactive_count += 1
        
        self._indexing_stats['interactive_indexed'] = interactive_count
        
        if self._indexing_context:
            self._indexing_context.interactive_elements = interactive_count
            self._indexing_context.total_elements = total_indexed
    
    def _save_current_indices(self):
        """Сохранение текущих индексов для следующего сравнения"""
        self._previous_indices = self._node_id_to_index.copy()
        self._previous_xpaths = self._xpath_to_index.copy()
    
    def get_element_by_index(self, index: int) -> Optional[IndexedElement]:
        """Получение элемента по индексу"""
        indexed_node = self._index_to_node.get(index)
        if indexed_node:
            return self._convert_to_indexed_element(indexed_node)
        return None
    
    def get_interactive_elements(self) -> List[IndexedElement]:
        """Получение всех интерактивных элементов"""
        interactive_elements = []
        
        for indexed_node in self._index_to_node.values():
            if indexed_node.is_interactive:
                element = self._convert_to_indexed_element(indexed_node)
                interactive_elements.append(element)
        
        return sorted(interactive_elements, key=lambda x: x.index)
    
    def get_elements_by_role(self, role: ElementRole) -> List[IndexedElement]:
        """Получение элементов по роли"""
        elements = []
        
        for indexed_node in self._index_to_node.values():
            if indexed_node.node.role == role.value:
                element = self._convert_to_indexed_element(indexed_node)
                elements.append(element)
        
        return sorted(elements, key=lambda x: x.index)
    
    def get_indexing_stats(self) -> Dict[str, Any]:
        """Получение статистики индексации"""
        stats = self._indexing_stats.copy()
        
        if self._indexing_context:
            stats.update({
                'timestamp': self._indexing_context.timestamp,
                'dom_hash': self._indexing_context.dom_hash,
                'new_elements': self._indexing_context.new_elements,
                'removed_elements': self._indexing_context.removed_elements
            })
        
        return stats
    
    def clear_cache(self):
        """Очистка кэша индексации"""
        self._previous_indices.clear()
        self._previous_xpaths.clear()
        self._indexing_stats['cached_hits'] = 0
        self._indexing_stats['cache_misses'] = 0
    
    def get_cache_efficiency(self) -> float:
        """Получение эффективности кэша"""
        total_requests = self._indexing_stats['cached_hits'] + self._indexing_stats['cache_misses']
        if total_requests == 0:
            return 0.0
        
        return self._indexing_stats['cached_hits'] / total_requests
