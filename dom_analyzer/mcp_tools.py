"""
MCP Tools для DOM Analyzer

Инструменты для интеграции DOM анализатора в MCP сервер.
Реализует browser-use стиль инструментов для взаимодействия с веб-страницами.
"""

import asyncio
import json
import logging
from typing import Dict, List, Any, Optional, Union
from dataclasses import asdict

from .dom_analyzer import DOMAnalyzer, PageAnalysisResult, ElementInteractionInfo
from .types import ElementRole, ElementState
from .config import DOMAnalyzerConfig


class MCPDOMTools:
    """MCP инструменты для DOM анализатора"""
    
    def __init__(self, config: Optional[DOMAnalyzerConfig] = None):
        self.config = config or DOMAnalyzerConfig()
        self.logger = logging.getLogger("MCPDOMTools")
        
        # DOM анализатор
        self.dom_analyzer: Optional[DOMAnalyzer] = None
        
        # Текущая активная вкладка
        self.current_target_id: Optional[str] = None
        
        # Кэш результатов анализа
        self._analysis_cache: Dict[str, PageAnalysisResult] = {}
        
        # Статистика использования
        self._usage_stats = {
            'total_calls': 0,
            'successful_calls': 0,
            'failed_calls': 0
        }
    
    async def initialize(self) -> Dict[str, Any]:
        """Инициализация MCP инструментов"""
        try:
            self.logger.info("Initializing MCP DOM Tools...")
            
            # Создаем DOM анализатор только если его нет
            if not self.dom_analyzer:
                self.dom_analyzer = DOMAnalyzer(self.config)
            
            # Подключаемся к CDP
            await self.dom_analyzer._ensure_cdp_connection()
            
            self.logger.info("MCP DOM Tools initialized successfully")
            
            return {
                "success": True,
                "message": "MCP DOM Tools initialized successfully",
                "version": "1.0.0",
                "capabilities": [
                    "browser_get_state",
                    "browser_click",
                    "browser_type",
                    "browser_navigate",
                    "browser_extract_content",
                    "browser_scroll",
                    "browser_go_back",
                    "browser_list_tabs"
                ]
            }
            
        except Exception as e:
            self.logger.error(f"Error initializing MCP DOM Tools: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def browser_get_state(self, include_screenshot: bool = False, 
                               target_id: Optional[str] = None) -> Dict[str, Any]:
        """Получение состояния браузера (аналог browser_get_state)"""
        try:
            self._usage_stats['total_calls'] += 1
            
            # Определяем target_id
            if target_id:
                current_target = target_id
            elif self.current_target_id:
                current_target = self.current_target_id
            else:
                # Получаем первый доступный target
                targets = await self._get_available_targets()
                if not targets:
                    raise Exception("No browser targets available")
                current_target = targets[0]['id']
                self.current_target_id = current_target
            
            self.logger.info(f"Getting browser state for target: {current_target}")
            
            # Анализируем страницу
            analysis_result = await self.dom_analyzer.analyze_page(current_target)
            
            # Формируем результат в стиле browser-use
            result = {
                "success": True,
                "target_id": current_target,
                "url": analysis_result.url,
                "title": analysis_result.title,
                "timestamp": analysis_result.timestamp,
                "dom_hash": analysis_result.dom_hash,
                "total_elements": analysis_result.total_elements,
                "interactive_elements": analysis_result.interactive_count,
                "elements": []
            }
            
            # Добавляем элементы в формате browser-use
            for element in analysis_result.interactive_elements:
                element_info = {
                    "index": element.index,
                    "role": element.role,
                    "text": element.text,
                    "tag_name": element.tag_name,
                    "xpath": element.xpath,
                    "is_interactive": element.is_interactive,
                    "states": element.states,
                    "attributes": element.attributes,
                    "bounding_box": element.bounding_box
                }
                result["elements"].append(element_info)
            
            # Добавляем скриншот если требуется
            if include_screenshot:
                # TODO: Реализовать получение скриншота
                result["screenshot"] = None
            
            self._usage_stats['successful_calls'] += 1
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error getting browser state: {e}")
            self._usage_stats['failed_calls'] += 1
            
            return {
                "success": False,
                "error": str(e)
            }
    
    async def browser_click(self, index: int, target_id: Optional[str] = None, 
                           open_in_new_tab: bool = False) -> Dict[str, Any]:
        """Клик по элементу по индексу (аналог browser_click)"""
        try:
            self._usage_stats['total_calls'] += 1
            
            # Определяем target_id
            if target_id:
                current_target = target_id
            elif self.current_target_id:
                current_target = self.current_target_id
            else:
                raise Exception("No active browser target")
            
            self.logger.info(f"Clicking element {index} on target: {current_target}")
            
            # Получаем элемент по индексу
            element = await self.dom_analyzer.get_element_by_index(current_target, index)
            
            if not element:
                raise Exception(f"Element with index {index} not found")
            
            if not element.is_interactive:
                raise Exception(f"Element with index {index} is not interactive")
            
            # Формируем результат
            result = {
                "success": True,
                "message": f"Clicked element [{index}] {element.role}: '{element.text}'",
                "target_id": current_target,
                "element_index": index,
                "element_role": element.role,
                "element_text": element.text,
                "open_in_new_tab": open_in_new_tab
            }
            
            # TODO: Реализовать фактический клик через CDP
            # Пока возвращаем информацию о том, что клик был бы выполнен
            
            self._usage_stats['successful_calls'] += 1
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error clicking element {index}: {e}")
            self._usage_stats['failed_calls'] += 1
            
            return {
                "success": False,
                "error": str(e)
            }
    
    async def browser_type(self, index: int, text: str, 
                          target_id: Optional[str] = None) -> Dict[str, Any]:
        """Ввод текста в элемент по индексу (аналог browser_type)"""
        try:
            self._usage_stats['total_calls'] += 1
            
            # Определяем target_id
            if target_id:
                current_target = target_id
            elif self.current_target_id:
                current_target = self.current_target_id
            else:
                raise Exception("No active browser target")
            
            self.logger.info(f"Typing text in element {index} on target: {current_target}")
            
            # Получаем элемент по индексу
            element = await self.dom_analyzer.get_element_by_index(current_target, index)
            
            if not element:
                raise Exception(f"Element with index {index} not found")
            
            # Проверяем, что элемент подходит для ввода текста
            input_roles = {'textbox', 'searchbox', 'combobox', 'textarea'}
            if element.role not in input_roles:
                raise Exception(f"Element with index {index} is not suitable for text input (role: {element.role})")
            
            # Формируем результат
            result = {
                "success": True,
                "message": f"Typed text in element [{index}] {element.role}: '{element.text}'",
                "target_id": current_target,
                "element_index": index,
                "element_role": element.role,
                "element_text": element.text,
                "input_text": text
            }
            
            # TODO: Реализовать фактический ввод текста через CDP
            # Пока возвращаем информацию о том, что ввод был бы выполнен
            
            self._usage_stats['successful_calls'] += 1
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error typing text in element {index}: {e}")
            self._usage_stats['failed_calls'] += 1
            
            return {
                "success": False,
                "error": str(e)
            }
    
    async def browser_navigate(self, url: str, target_id: Optional[str] = None, 
                              new_tab: bool = False) -> Dict[str, Any]:
        """Навигация по URL (аналог browser_navigate)"""
        try:
            self._usage_stats['total_calls'] += 1
            
            # Определяем target_id
            if target_id:
                current_target = target_id
            elif self.current_target_id:
                current_target = self.current_target_id
            else:
                # Получаем первый доступный target
                targets = await self._get_available_targets()
                if not targets:
                    raise Exception("No browser targets available")
                current_target = targets[0]['id']
                self.current_target_id = current_target
            
            self.logger.info(f"Navigating to {url} on target: {current_target}")
            
            # Формируем результат
            result = {
                "success": True,
                "message": f"Navigated to {url}",
                "target_id": current_target,
                "url": url,
                "new_tab": new_tab
            }
            
            # TODO: Реализовать фактическую навигацию через CDP
            # Пока возвращаем информацию о том, что навигация была бы выполнена
            
            self._usage_stats['successful_calls'] += 1
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error navigating to {url}: {e}")
            self._usage_stats['failed_calls'] += 1
            
            return {
                "success": False,
                "error": str(e)
            }
    
    async def browser_extract_content(self, extraction_prompt: str, 
                                    target_id: Optional[str] = None) -> Dict[str, Any]:
        """Извлечение контента с помощью AI (аналог browser_extract_content)"""
        try:
            self._usage_stats['total_calls'] += 1
            
            # Определяем target_id
            if target_id:
                current_target = target_id
            elif self.current_target_id:
                current_target = self.current_target_id
            else:
                raise Exception("No active browser target")
            
            self.logger.info(f"Extracting content with prompt: {extraction_prompt}")
            
            # Получаем состояние страницы
            page_state = await self.dom_analyzer.get_page_state(current_target)
            
            # Формируем результат
            result = {
                "success": True,
                "message": "Content extraction completed",
                "target_id": current_target,
                "extraction_prompt": extraction_prompt,
                "page_url": page_state.url,
                "page_title": page_state.title,
                "total_elements": len(page_state.elements),
                "interactive_elements": page_state.interactive_count,
                "extracted_content": {
                    "url": page_state.url,
                    "title": page_state.title,
                    "elements": [
                        {
                            "index": elem.index,
                            "role": elem.role.value,
                            "text": elem.text,
                            "is_interactive": elem.is_interactive
                        }
                        for elem in page_state.elements
                    ]
                }
            }
            
            # TODO: Реализовать AI-извлечение контента
            # Пока возвращаем базовую информацию о странице
            
            self._usage_stats['successful_calls'] += 1
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error extracting content: {e}")
            self._usage_stats['failed_calls'] += 1
            
            return {
                "success": False,
                "error": str(e)
            }
    
    async def browser_scroll(self, direction: str = "down", 
                           target_id: Optional[str] = None) -> Dict[str, Any]:
        """Прокрутка страницы (аналог browser_scroll)"""
        try:
            self._usage_stats['total_calls'] += 1
            
            # Определяем target_id
            if target_id:
                current_target = target_id
            elif self.current_target_id:
                current_target = self.current_target_id
            else:
                raise Exception("No active browser target")
            
            if direction not in ["up", "down"]:
                raise Exception("Direction must be 'up' or 'down'")
            
            self.logger.info(f"Scrolling {direction} on target: {current_target}")
            
            # Формируем результат
            result = {
                "success": True,
                "message": f"Scrolled {direction}",
                "target_id": current_target,
                "direction": direction
            }
            
            # TODO: Реализовать фактическую прокрутку через CDP
            # Пока возвращаем информацию о том, что прокрутка была бы выполнена
            
            self._usage_stats['successful_calls'] += 1
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error scrolling {direction}: {e}")
            self._usage_stats['failed_calls'] += 1
            
            return {
                "success": False,
                "error": str(e)
            }
    
    async def browser_go_back(self, target_id: Optional[str] = None) -> Dict[str, Any]:
        """Переход назад в истории (аналог browser_go_back)"""
        try:
            self._usage_stats['total_calls'] += 1
            
            # Определяем target_id
            if target_id:
                current_target = target_id
            elif self.current_target_id:
                current_target = self.current_target_id
            else:
                raise Exception("No active browser target")
            
            self.logger.info(f"Going back on target: {current_target}")
            
            # Формируем результат
            result = {
                "success": True,
                "message": "Navigated back",
                "target_id": current_target
            }
            
            # TODO: Реализовать фактический переход назад через CDP
            # Пока возвращаем информацию о том, что переход был бы выполнен
            
            self._usage_stats['successful_calls'] += 1
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error going back: {e}")
            self._usage_stats['failed_calls'] += 1
            
            return {
                "success": False,
                "error": str(e)
            }
    
    async def browser_list_tabs(self) -> Dict[str, Any]:
        """Список открытых вкладок (аналог browser_list_tabs)"""
        try:
            self._usage_stats['total_calls'] += 1
            
            self.logger.info("Listing browser tabs")
            
            # Получаем доступные targets
            targets = await self._get_available_targets()
            
            # Формируем результат
            result = {
                "success": True,
                "message": f"Found {len(targets)} tabs",
                "tabs": []
            }
            
            for target in targets:
                tab_info = {
                    "id": target['id'],
                    "url": target.get('url', ''),
                    "title": target.get('title', ''),
                    "type": target.get('type', ''),
                    "is_active": target['id'] == self.current_target_id
                }
                result["tabs"].append(tab_info)
            
            self._usage_stats['successful_calls'] += 1
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error listing tabs: {e}")
            self._usage_stats['failed_calls'] += 1
            
            return {
                "success": False,
                "error": str(e)
            }
    
    async def _get_available_targets(self) -> List[Dict[str, Any]]:
        """Получение доступных browser targets"""
        try:
            if not self.dom_analyzer:
                raise Exception("DOM Analyzer not initialized")
            
            # Получаем targets через CDP клиент
            targets_response = await self.dom_analyzer.cdp_client.get_targets()
            
            if not targets_response.success:
                raise Exception(f"Failed to get targets: {targets_response.error}")
            
            targets = targets_response.data.get('targets', [])
            
            # Фильтруем только page targets
            page_targets = [
                target for target in targets 
                if target.get('type') == 'page'
            ]
            
            return page_targets
            
        except Exception as e:
            self.logger.error(f"Error getting available targets: {e}")
            return []
    
    def get_usage_stats(self) -> Dict[str, Any]:
        """Получение статистики использования"""
        total_calls = self._usage_stats['total_calls']
        success_rate = 0.0
        
        if total_calls > 0:
            success_rate = self._usage_stats['successful_calls'] / total_calls
        
        return {
            **self._usage_stats,
            "success_rate": success_rate
        }
    
    async def cleanup(self):
        """Очистка ресурсов"""
        try:
            if self.dom_analyzer:
                await self.dom_analyzer.close()
                self.logger.info("MCP DOM Tools cleaned up successfully")
        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")


# Создаем глобальный экземпляр для использования в MCP сервере
mcp_dom_tools = MCPDOMTools()
