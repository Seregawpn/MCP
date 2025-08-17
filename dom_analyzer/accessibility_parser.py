"""
Accessibility Parser

Парсер Accessibility Tree для извлечения информации об элементах.
Реализует анализ AX узлов и извлечение ролей, состояний и свойств.
"""

import logging
import re
from typing import Dict, List, Any, Optional, Set
from dataclasses import dataclass

from .types import AccessibilityNode, ElementRole, ElementState
from .config import AccessibilityConfig


@dataclass
class AXProperty:
    """Свойство Accessibility узла"""
    name: str
    value: str | bool | None
    source: str = "accessibility"


@dataclass
class ParsedAXNode:
    """Распарсенный Accessibility узел"""
    node_id: int
    role: str
    name: str
    value: Optional[str]
    description: Optional[str]
    properties: List[AXProperty]
    states: List[str]
    children: List[int]
    parent_id: Optional[int]
    backend_dom_node_id: Optional[int]
    ignored: bool = False
    is_interactive: bool = False


class AccessibilityParser:
    """Парсер Accessibility Tree"""
    
    def __init__(self, config: Optional[AccessibilityConfig] = None):
        self.config = config or AccessibilityConfig()
        self.logger = logging.getLogger("AccessibilityParser")
        
        # Роли, которые считаются интерактивными
        self.interactive_roles = self.config.interactive_roles
        
        # Состояния, которые важны для автоматизации
        self.important_states = {
            'expanded', 'collapsed', 'selected', 'checked', 'pressed',
            'disabled', 'readonly', 'required', 'invalid', 'focused',
            'hidden', 'visible', 'busy', 'live'
        }
    
    def parse_accessibility_tree(self, ax_tree_data: Dict[str, Any]) -> List[AccessibilityNode]:
        """Парсинг Accessibility Tree из CDP ответа"""
        try:
            if not ax_tree_data or 'nodes' not in ax_tree_data:
                self.logger.warning("Invalid accessibility tree data")
                return []
            
            nodes_data = ax_tree_data['nodes']
            parsed_nodes = []
            
            # Первый проход: парсим все узлы
            for node_data in nodes_data:
                parsed_node = self._parse_single_node(node_data)
                if parsed_node:
                    parsed_nodes.append(parsed_node)
            
            # Второй проход: определяем интерактивность
            for node in parsed_nodes:
                node.is_interactive = self._is_node_interactive(node)
            
            # Конвертируем в наши типы
            accessibility_nodes = []
            for parsed_node in parsed_nodes:
                ax_node = self._convert_to_accessibility_node(parsed_node)
                if ax_node:
                    accessibility_nodes.append(ax_node)
            
            self.logger.info(f"Parsed {len(accessibility_nodes)} accessibility nodes")
            return accessibility_nodes
            
        except Exception as e:
            self.logger.error(f"Error parsing accessibility tree: {e}")
            return []
    
    def _parse_single_node(self, node_data: Dict[str, Any]) -> Optional[ParsedAXNode]:
        """Парсинг отдельного AX узла"""
        try:
            # Извлекаем основные поля
            node_id = node_data.get('nodeId', 0)
            role_data = node_data.get('role', {})
            name_data = node_data.get('name', {})
            value_data = node_data.get('value', {})
            description_data = node_data.get('description', {})
            
            # Роль узла
            role = role_data.get('value', 'generic') if role_data else 'generic'
            
            # Имя узла
            name = name_data.get('value', '') if name_data else ''
            
            # Значение узла
            value = value_data.get('value') if value_data else None
            
            # Описание узла
            description = description_data.get('value') if description_data else None
            
            # Свойства узла
            properties = self._parse_node_properties(node_data)
            
            # Состояния узла
            states = self._extract_node_states(node_data)
            
            # Дочерние узлы
            children = node_data.get('childIds', [])
            
            # Родительский узел
            parent_id = node_data.get('parentId')
            
            # ID DOM узла
            backend_dom_node_id = node_data.get('backendDOMNodeId')
            
            # Игнорируется ли узел
            ignored = node_data.get('ignored', False)
            
            # Проверяем валидность текста
            if not self.is_text_valid(name):
                name = ""
            
            return ParsedAXNode(
                node_id=node_id,
                role=role,
                name=name,
                value=value,
                description=description,
                properties=properties,
                states=states,
                children=children,
                parent_id=parent_id,
                backend_dom_node_id=backend_dom_node_id,
                ignored=ignored,
                is_interactive=False  # Будет установлено позже
            )
            
        except Exception as e:
            self.logger.error(f"Error parsing single node: {e}")
            return None
    
    def _parse_node_properties(self, node_data: Dict[str, Any]) -> List[AXProperty]:
        """Парсинг свойств узла"""
        properties = []
        
        try:
            # Получаем свойства из разных источников
            ax_properties = node_data.get('properties', [])
            
            for prop_data in ax_properties:
                prop_name = prop_data.get('name', {}).get('value', '')
                prop_value = prop_data.get('value', {}).get('value')
                
                if prop_name and prop_value is not None:
                    property_obj = AXProperty(
                        name=prop_name,
                        value=prop_value,
                        source="accessibility"
                    )
                    properties.append(property_obj)
            
            # Добавляем дополнительные свойства из других полей
            if 'checked' in node_data:
                properties.append(AXProperty('checked', node_data['checked'], 'node'))
            
            if 'expanded' in node_data:
                properties.append(AXProperty('expanded', node_data['expanded'], 'node'))
            
            if 'selected' in node_data:
                properties.append(AXProperty('selected', node_data['selected'], 'node'))
            
            if 'disabled' in node_data:
                properties.append(AXProperty('disabled', node_data['disabled'], 'node'))
            
        except Exception as e:
            self.logger.error(f"Error parsing node properties: {e}")
        
        return properties
    
    def _extract_node_states(self, node_data: Dict[str, Any]) -> List[str]:
        """Извлечение состояний узла"""
        states = []
        
        try:
            # Получаем состояния из properties
            ax_properties = node_data.get('properties', [])
            for prop_data in ax_properties:
                prop_name = prop_data.get('name', {}).get('value', '')
                prop_value = prop_data.get('value', {}).get('value')
                
                if prop_name in self.important_states and prop_value:
                    states.append(prop_name)
            
            # Добавляем состояния из основных полей
            if node_data.get('checked'):
                states.append('checked')
            
            if node_data.get('expanded'):
                states.append('expanded')
            
            if node_data.get('selected'):
                states.append('selected')
            
            if node_data.get('disabled'):
                states.append('disabled')
            
            if node_data.get('readonly'):
                states.append('readonly')
            
            if node_data.get('required'):
                states.append('required')
            
            if node_data.get('invalid'):
                states.append('invalid')
            
            if node_data.get('focused'):
                states.append('focused')
            
            if node_data.get('hidden'):
                states.append('hidden')
            else:
                states.append('visible')
            
        except Exception as e:
            self.logger.error(f"Error extracting node states: {e}")
        
        return states
    
    def _is_node_interactive(self, node: ParsedAXNode) -> bool:
        """Определение, является ли узел интерактивным"""
        # Проверяем роль
        if node.role in self.interactive_roles:
            return True
        
        # Проверяем состояния
        interactive_states = {'button', 'link', 'menuitem', 'tab'}
        if any(state in interactive_states for state in node.states):
            return True
        
        # Проверяем свойства
        interactive_properties = {'clickable', 'pressable', 'selectable'}
        if any(prop.name in interactive_properties and prop.value for prop in node.properties):
            return True
        
        # Проверяем наличие обработчиков событий
        event_properties = {'onclick', 'onkeydown', 'onkeyup', 'onsubmit'}
        if any(prop.name in event_properties for prop in node.properties):
            return True
        
        return False
    
    def filter_interactive_elements(self, nodes: List[AccessibilityNode]) -> List[AccessibilityNode]:
        """Фильтрация интерактивных элементов"""
        interactive_nodes = []
        
        for node in nodes:
            if self._is_node_interactive_from_accessibility_node(node):
                interactive_nodes.append(node)
        
        self.logger.info(f"Found {len(interactive_nodes)} interactive elements out of {len(nodes)} total")
        return interactive_nodes
    
    def _is_node_interactive_from_accessibility_node(self, node: AccessibilityNode) -> bool:
        """Определение интерактивности для AccessibilityNode"""
        # Проверяем роль
        if node.role in self.interactive_roles:
            return True
        
        # Проверяем состояния
        interactive_states = {'button', 'link', 'menuitem', 'tab'}
        if any(state in interactive_states for state in node.state.values()):
            return True
        
        return False
    
    def extract_element_states(self, node: AccessibilityNode) -> List[ElementState]:
        """Извлечение состояний элемента"""
        states = []
        
        try:
            # Конвертируем состояния из AccessibilityNode в ElementState
            state_mapping = {
                'visible': ElementState.VISIBLE,
                'hidden': ElementState.HIDDEN,
                'disabled': ElementState.DISABLED,
                'readonly': ElementState.READONLY,
                'required': ElementState.REQUIRED,
                'invalid': ElementState.INVALID,
                'expanded': ElementState.EXPANDED,
                'collapsed': ElementState.COLLAPSED,
                'selected': ElementState.SELECTED,
                'checked': ElementState.CHECKED,
                'focused': ElementState.FOCUSED
            }
            
            for state_name, state_value in node.state.items():
                if state_name in state_mapping and state_value:
                    states.append(state_mapping[state_name])
            
        except Exception as e:
            self.logger.error(f"Error extracting element states: {e}")
        
        return states
    
    def is_text_valid(self, text: str) -> bool:
        """Проверка валидности текста"""
        if not text:
            return False
        
        text_length = len(text.strip())
        return (
            text_length >= self.config.min_text_length and
            text_length <= self.config.max_text_length
        )
    
    def clean_text(self, text: str) -> str:
        """Очистка текста от лишних символов"""
        if not text:
            return ""
        
        # Базовая очистка
        cleaned = text.strip()
        
        # Убираем множественные пробелы
        cleaned = re.sub(r'\s+', ' ', cleaned)
        
        # Убираем невидимые символы
        cleaned = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', cleaned)
        
        # Убираем HTML теги (если есть)
        cleaned = re.sub(r'<[^>]+>', '', cleaned)
        
        return cleaned
    
    def _convert_to_accessibility_node(self, parsed_node: ParsedAXNode) -> Optional[AccessibilityNode]:
        """Конвертация ParsedAXNode в AccessibilityNode"""
        try:
            # Конвертируем состояния в словарь
            state_dict = {}
            for state in parsed_node.states:
                state_dict[state] = True
            
            # Конвертируем свойства в словарь
            properties_dict = {}
            for prop in parsed_node.properties:
                properties_dict[prop.name] = prop.value
            
            return AccessibilityNode(
                node_id=parsed_node.node_id,
                role=parsed_node.role,
                name=parsed_node.name,
                value=parsed_node.value,
                description=parsed_node.description,
                state=state_dict,
                children=parsed_node.children,
                parent_id=parsed_node.parent_id,
                backend_dom_node_id=parsed_node.backend_dom_node_id
            )
            
        except Exception as e:
            self.logger.error(f"Error converting to AccessibilityNode: {e}")
            return None
    
    def get_node_summary(self, node: AccessibilityNode) -> str:
        """Получение краткого описания узла"""
        parts = []
        
        if node.role:
            parts.append(f"role={node.role}")
        
        if node.name:
            parts.append(f"name='{self.clean_text(node.name)}'")
        
        if node.value:
            parts.append(f"value='{self.clean_text(str(node.value))}'")
        
        if node.state:
            # Фильтруем только True состояния
            true_states = [k for k, v in node.state.items() if v is True]
            if true_states:
                parts.append(f"states=[{', '.join(true_states)}]")
        
        return f"AccessibilityNode({', '.join(parts)})"
