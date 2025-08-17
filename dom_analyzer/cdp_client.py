"""
CDP Client

Клиент для работы с Chrome DevTools Protocol (CDP).
Реализует подключение к Chrome и получение DOM/Accessibility Tree.
"""

import asyncio
import json
import logging
from typing import Dict, Any, Optional, List
from urllib.parse import urlparse

from .types import CDPResponse, PageState
from .config import CDPConfig


class CDPSession:
    """CDP сессия для конкретной вкладки"""
    
    def __init__(self, target_id: str, session_id: str, cdp_client):
        self.target_id = target_id
        self.session_id = session_id
        self.cdp_client = cdp_client
        self.logger = logging.getLogger(f"CDPSession-{target_id}")


class CDPClient:
    """Клиент для работы с Chrome DevTools Protocol"""
    
    def __init__(self, config: Optional[CDPConfig] = None):
        self.config = config or CDPConfig()
        self.connected = False
        self.port = None
        self.debugger_url = None
        self.targets = []
        self.sessions = {}
        self.logger = logging.getLogger("CDPClient")
        
        # Настройка логирования
        logging.basicConfig(level=logging.INFO)
    
    async def connect(self, port: int = 9222) -> CDPResponse:
        """Подключение к Chrome через CDP"""
        try:
            self.port = port
            self.debugger_url = f"http://localhost:{port}/json"
            
            # Получаем список доступных вкладок
            await self._get_targets()
            
            if not self.targets:
                return CDPResponse(
                    success=False,
                    error="No Chrome tabs found. Make sure Chrome is running with --remote-debugging-port"
                )
            
            self.connected = True
            self.logger.info(f"Connected to Chrome on port {port}, found {len(self.targets)} targets")
            
            return CDPResponse(
                success=True,
                data={
                    "port": port,
                    "status": "connected",
                    "targets_count": len(self.targets)
                }
            )
            
        except Exception as e:
            self.logger.error(f"Failed to connect to CDP: {e}")
            return CDPResponse(
                success=False,
                error=f"Connection failed: {str(e)}"
            )
    
    async def disconnect(self) -> CDPResponse:
        """Отключение от CDP"""
        try:
            # Закрываем все сессии
            for session in self.sessions.values():
                await self._close_session(session)
            
            self.sessions.clear()
            self.targets.clear()
            self.connected = False
            
            self.logger.info("Disconnected from CDP")
            return CDPResponse(
                success=True,
                data={"status": "disconnected"}
            )
            
        except Exception as e:
            self.logger.error(f"Error during disconnect: {e}")
            return CDPResponse(
                success=False,
                error=f"Disconnect failed: {str(e)}"
            )
    
    async def get_targets(self) -> CDPResponse:
        """Получение списка доступных вкладок"""
        if not self.connected:
            return CDPResponse(
                success=False,
                error="Not connected to CDP"
            )
        
        try:
            await self._get_targets()
            return CDPResponse(
                success=True,
                data={"targets": self.targets}
            )
        except Exception as e:
            return CDPResponse(
                success=False,
                error=f"Failed to get targets: {str(e)}"
            )
    
    async def get_or_create_session(self, target_id: str, focus: bool = False) -> CDPSession:
        """Получение или создание CDP сессии для вкладки"""
        if target_id in self.sessions:
            return self.sessions[target_id]
        
        try:
            # Создаем новую сессию
            session = await self._create_session(target_id, focus)
            self.sessions[target_id] = session
            return session
            
        except Exception as e:
            self.logger.error(f"Failed to create session for target {target_id}: {e}")
            raise
    
    async def get_dom_tree(self, target_id: str) -> CDPResponse:
        """Получение DOM дерева для конкретной вкладки"""
        if not self.connected:
            return CDPResponse(
                success=False,
                error="Not connected to CDP"
            )
        
        try:
            session = await self.get_or_create_session(target_id, focus=False)
            
            # Получаем DOM дерево через заглушку
            dom_result = await session.cdp_client.send.DOM.getDocument(
                session_id=session.session_id
            )
            
            return CDPResponse(
                success=True,
                data={"dom_tree": dom_result}
            )
            
        except Exception as e:
            return CDPResponse(
                success=False,
                error=f"Failed to get DOM tree: {str(e)}"
            )
    
    async def get_accessibility_tree(self, target_id: str) -> CDPResponse:
        """Получение Accessibility Tree для конкретной вкладки"""
        if not self.connected:
            return CDPResponse(
                success=False,
                error="Not connected to CDP"
            )
        
        try:
            session = await self.get_or_create_session(target_id, focus=False)
            
            # Получаем Accessibility Tree через заглушку
            ax_result = await session.cdp_client.send.Accessibility.getFullAXTree(
                session_id=session.session_id
            )
            
            return CDPResponse(
                success=True,
                data={"accessibility_tree": ax_result}
            )
            
        except Exception as e:
            return CDPResponse(
                success=False,
                error=f"Failed to get Accessibility Tree: {str(e)}"
            )
    
    async def get_page_metrics(self, target_id: str) -> CDPResponse:
        """Получение метрик страницы (размеры, скролл)"""
        if not self.connected:
            return CDPResponse(
                success=False,
                error="Not connected to CDP"
            )
        
        try:
            session = await self.get_or_create_session(target_id, focus=False)
            
            # Получаем метрики страницы через заглушку
            metrics = await session.cdp_client.send.Page.getLayoutMetrics(
                session_id=session.session_id
            )
            
            return CDPResponse(
                success=True,
                data={"page_metrics": metrics}
            )
            
        except Exception as e:
            return CDPResponse(
                success=False,
                error=f"Failed to get page metrics: {str(e)}"
            )
    
    async def execute_script(self, target_id: str, script: str) -> CDPResponse:
        """Выполнение JavaScript кода в конкретной вкладке"""
        if not self.connected:
            return CDPResponse(
                success=False,
                error="Not connected to CDP"
            )
        
        try:
            session = await self.get_or_create_session(target_id, focus=False)
            
            # Выполняем JavaScript через заглушку
            result = await session.cdp_client.send.Runtime.evaluate(
                params={'expression': script},
                session_id=session.session_id
            )
            
            return CDPResponse(
                success=True,
                data={"result": result}
            )
            
        except Exception as e:
            return CDPResponse(
                success=False,
                error=f"Failed to execute script: {str(e)}"
            )
    
    async def wait_for_page_load(self, target_id: str, timeout: int = 10000) -> CDPResponse:
        """Ожидание загрузки страницы"""
        if not self.connected:
            return CDPResponse(
                success=False,
                error="Not connected to CDP"
            )
        
        try:
            session = await self.get_or_create_session(target_id, focus=False)
            
            # Ждем готовности страницы
            start_time = asyncio.get_event_loop().time()
            while (asyncio.get_event_loop().time() - start_time) * 1000 < timeout:
                try:
                    result = await session.cdp_client.send.Runtime.evaluate(
                        params={'expression': 'document.readyState'},
                        session_id=session.session_id
                    )
                    
                    if result.get('result', {}).get('value') == 'complete':
                        return CDPResponse(
                            success=True,
                            data={"status": "page_loaded"}
                        )
                    
                    await asyncio.sleep(0.1)
                    
                except Exception:
                    await asyncio.sleep(0.1)
            
            return CDPResponse(
                success=False,
                error="Page load timeout"
            )
            
        except Exception as e:
            return CDPResponse(
                success=False,
                error=f"Failed to wait for page load: {str(e)}"
            )
    
    def is_connected(self) -> bool:
        """Проверка подключения"""
        return self.connected
    
    def get_target_info(self, target_id: str) -> Optional[Dict[str, Any]]:
        """Получение информации о вкладке"""
        for target in self.targets:
            if target.get('id') == target_id:
                return target
        return None
    
    async def _get_targets(self):
        """Получение списка вкладок из Chrome"""
        import httpx
        
        async with httpx.AsyncClient() as client:
            response = await client.get(self.debugger_url)
            response.raise_for_status()
            self.targets = response.json()
    
    async def _create_session(self, target_id: str, focus: bool) -> CDPSession:
        """Создание CDP сессии для вкладки"""
        # TODO: Реализовать создание реальной CDP сессии
        # Пока возвращаем заглушку для тестирования
        
        # Имитируем создание сессии
        session_id = f"session_{target_id}_{int(asyncio.get_event_loop().time())}"
        
        # Создаем заглушку cdp_client
        class MockCDPClient:
            class send:
                class DOM:
                    @staticmethod
                    async def getDocument(session_id: str):
                        return {"root": {"nodeId": 1, "nodeType": 1}}
                
                class Accessibility:
                    @staticmethod
                    async def getFullAXTree(session_id: str):
                        return {"nodes": []}
                
                class Page:
                    @staticmethod
                    async def getLayoutMetrics(session_id: str):
                        return {"visualViewport": {"width": 1920, "height": 1080}}
                
                class Runtime:
                    @staticmethod
                    async def evaluate(params: Dict, session_id: str):
                        return {"result": {"value": "complete"}}
        
        cdp_client = MockCDPClient()
        
        return CDPSession(target_id, session_id, cdp_client)
    
    async def _close_session(self, session: CDPSession):
        """Закрытие CDP сессии"""
        # TODO: Реализовать закрытие реальной CDP сессии
        pass
