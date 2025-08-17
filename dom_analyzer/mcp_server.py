"""
MCP Server для DOM Analyzer

MCP сервер, который предоставляет инструменты для взаимодействия
с веб-страницами через DOM анализатор.
"""

import asyncio
import json
import logging
import sys
from typing import Dict, List, Any, Optional
from pathlib import Path

# Импортируем наши инструменты
from .mcp_tools import mcp_dom_tools
from .config import DOMAnalyzerConfig


class MCPDOMServer:
    """MCP сервер для DOM анализатора"""
    
    def __init__(self, config: Optional[DOMAnalyzerConfig] = None):
        self.config = config or DOMAnalyzerConfig()
        self.logger = logging.getLogger("MCPDOMServer")
        
        # Инициализируем инструменты
        self.tools = mcp_dom_tools
        
        # Состояние сервера
        self.initialized = False
        
        # Настройка логирования
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
    
    async def initialize(self) -> bool:
        """Инициализация сервера"""
        try:
            self.logger.info("Initializing MCP DOM Server...")
            
            # Инициализируем инструменты
            init_result = await self.tools.initialize()
            
            if not init_result.get('success'):
                self.logger.error(f"Failed to initialize tools: {init_result.get('error')}")
                return False
            
            self.initialized = True
            self.logger.info("MCP DOM Server initialized successfully")
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error initializing server: {e}")
            return False
    
    async def handle_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Обработка MCP запроса"""
        try:
            if not self.initialized:
                return {
                    "error": "Server not initialized",
                    "code": "SERVER_ERROR"
                }
            
            # Извлекаем информацию о запросе
            method = request.get('method', '')
            params = request.get('params', {})
            request_id = request.get('id')
            
            self.logger.info(f"Handling request: {method}")
            
            # Обрабатываем различные методы
            if method == 'tools/list':
                result = await self._handle_tools_list()
            elif method == 'tools/call':
                result = await self._handle_tools_call(params)
            elif method == 'initialize':
                result = await self._handle_initialize(params)
            else:
                result = {
                    "error": f"Unknown method: {method}",
                    "code": "METHOD_NOT_FOUND"
                }
            
            # Добавляем ID запроса если есть
            if request_id:
                result['id'] = request_id
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error handling request: {e}")
            return {
                "error": str(e),
                "code": "INTERNAL_ERROR"
            }
    
    async def _handle_initialize(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Обработка инициализации"""
        return {
            "jsonrpc": "2.0",
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {
                        "listChanged": False
                    }
                },
                "serverInfo": {
                    "name": "DOM Analyzer MCP Server",
                    "version": "1.0.0"
                }
            }
        }
    
    async def _handle_tools_list(self) -> Dict[str, Any]:
        """Обработка запроса списка инструментов"""
        tools = [
            {
                "name": "browser_get_state",
                "description": "Get the current page state including all interactive elements with their indices. Essential for interaction",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "include_screenshot": {
                            "type": "boolean",
                            "description": "Whether to include a screenshot of the page",
                            "default": False
                        },
                        "target_id": {
                            "type": "string",
                            "description": "Target ID to get state for. If not provided, uses current target"
                        }
                    }
                }
            },
            {
                "name": "browser_click",
                "description": "Click on an element by its index from browser_get_state. Supports opening links in new tabs",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "index": {
                            "type": "integer",
                            "description": "Index of the element to click"
                        },
                        "target_id": {
                            "type": "string",
                            "description": "Target ID to click on. If not provided, uses current target"
                        },
                        "open_in_new_tab": {
                            "type": "boolean",
                            "description": "Whether to open link in new tab (for link elements)",
                            "default": False
                        }
                    },
                    "required": ["index"]
                }
            },
            {
                "name": "browser_type",
                "description": "Type text into an input field identified by its index. Use after browser_get_state to find inputs",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "index": {
                            "type": "integer",
                            "description": "Index of the input element"
                        },
                        "text": {
                            "type": "string",
                            "description": "Text to type into the input field"
                        },
                        "target_id": {
                            "type": "string",
                            "description": "Target ID to type on. If not provided, uses current target"
                        }
                    },
                    "required": ["index", "text"]
                }
            },
            {
                "name": "browser_navigate",
                "description": "Navigate to a URL in the current tab or open a new tab. Example: Navigate to https://example.com",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "URL to navigate to"
                        },
                        "target_id": {
                            "type": "string",
                            "description": "Target ID to navigate on. If not provided, uses current target"
                        },
                        "new_tab": {
                            "type": "boolean",
                            "description": "Whether to open in new tab",
                            "default": False
                        }
                    },
                    "required": ["url"]
                }
            },
            {
                "name": "browser_extract_content",
                "description": "Extract structured content from the page using AI. Perfect for scraping specific information",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "extraction_prompt": {
                            "type": "string",
                            "description": "AI prompt describing what content to extract"
                        },
                        "target_id": {
                            "type": "string",
                            "description": "Target ID to extract from. If not provided, uses current target"
                        }
                    },
                    "required": ["extraction_prompt"]
                }
            },
            {
                "name": "browser_scroll",
                "description": "Scroll the page up or down by one viewport height",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "direction": {
                            "type": "string",
                            "enum": ["up", "down"],
                            "description": "Direction to scroll",
                            "default": "down"
                        },
                        "target_id": {
                            "type": "string",
                            "description": "Target ID to scroll. If not provided, uses current target"
                        }
                    }
                }
            },
            {
                "name": "browser_go_back",
                "description": "Navigate back to the previous page in browser history",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "target_id": {
                            "type": "string",
                            "description": "Target ID to go back on. If not provided, uses current target"
                        }
                    }
                }
            },
            {
                "name": "browser_list_tabs",
                "description": "List all open browser tabs with their URLs and titles",
                "inputSchema": {
                    "type": "object",
                    "properties": {}
                }
            }
        ]
        
        return {
            "jsonrpc": "2.0",
            "result": {
                "tools": tools
            }
        }
    
    async def _handle_tools_call(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Обработка вызова инструмента"""
        tool_name = params.get('name', '')
        arguments = params.get('arguments', {})
        
        self.logger.info(f"Calling tool: {tool_name} with arguments: {arguments}")
        
        # Вызываем соответствующий инструмент
        if tool_name == 'browser_get_state':
            result = await self.tools.browser_get_state(
                include_screenshot=arguments.get('include_screenshot', False),
                target_id=arguments.get('target_id')
            )
        elif tool_name == 'browser_click':
            result = await self.tools.browser_click(
                index=arguments['index'],
                target_id=arguments.get('target_id'),
                open_in_new_tab=arguments.get('open_in_new_tab', False)
            )
        elif tool_name == 'browser_type':
            result = await self.tools.browser_type(
                index=arguments['index'],
                text=arguments['text'],
                target_id=arguments.get('target_id')
            )
        elif tool_name == 'browser_navigate':
            result = await self.tools.browser_navigate(
                url=arguments['url'],
                target_id=arguments.get('target_id'),
                new_tab=arguments.get('new_tab', False)
            )
        elif tool_name == 'browser_extract_content':
            result = await self.tools.browser_extract_content(
                extraction_prompt=arguments['extraction_prompt'],
                target_id=arguments.get('target_id')
            )
        elif tool_name == 'browser_scroll':
            result = await self.tools.browser_scroll(
                direction=arguments.get('direction', 'down'),
                target_id=arguments.get('target_id')
            )
        elif tool_name == 'browser_go_back':
            result = await self.tools.browser_go_back(
                target_id=arguments.get('target_id')
            )
        elif tool_name == 'browser_list_tabs':
            result = await self.tools.browser_list_tabs()
        else:
            result = {
                "success": False,
                "error": f"Unknown tool: {tool_name}"
            }
        
        return {
            "jsonrpc": "2.0",
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(result, indent=2, ensure_ascii=False)
                    }
                ]
            }
        }
    
    async def run(self):
        """Запуск MCP сервера"""
        try:
            # Инициализируем сервер
            if not await self.initialize():
                self.logger.error("Failed to initialize server")
                return
            
            self.logger.info("MCP DOM Server is running...")
            self.logger.info("Waiting for MCP requests...")
            
            # Основной цикл обработки запросов
            while True:
                try:
                    # Читаем запрос из stdin
                    line = await asyncio.get_event_loop().run_in_executor(None, sys.stdin.readline)
                    
                    if not line:
                        break
                    
                    # Парсим JSON запрос
                    request = json.loads(line.strip())
                    
                    # Обрабатываем запрос
                    response = await self.handle_request(request)
                    
                    # Отправляем ответ в stdout
                    print(json.dumps(response, ensure_ascii=False))
                    sys.stdout.flush()
                    
                except json.JSONDecodeError as e:
                    self.logger.error(f"Invalid JSON request: {e}")
                except Exception as e:
                    self.logger.error(f"Error processing request: {e}")
                    
        except KeyboardInterrupt:
            self.logger.info("Server interrupted by user")
        except Exception as e:
            self.logger.error(f"Server error: {e}")
        finally:
            # Очищаем ресурсы
            await self.cleanup()
    
    async def cleanup(self):
        """Очистка ресурсов сервера"""
        try:
            if self.tools:
                await self.tools.cleanup()
            self.logger.info("Server cleanup completed")
        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")


async def main():
    """Основная функция"""
    # Создаем и запускаем сервер
    server = MCPDOMServer()
    await server.run()


if __name__ == "__main__":
    asyncio.run(main())
