"""
DOM Analyzer Package

Пакет для анализа DOM через Chrome DevTools Protocol (CDP) и Accessibility Tree.
Реализует индексированный подход browser-use для взаимодействия с веб-страницами.
"""

from .cdp_client import CDPClient, CDPSession
from .accessibility_parser import AccessibilityParser, AXProperty, ParsedAXNode
from .element_indexer import ElementIndexer, IndexedNode, IndexingContext
from .dom_analyzer import DOMAnalyzer, PageAnalysisResult, ElementInteractionInfo
from .mcp_tools import MCPDOMTools, mcp_dom_tools
from .mcp_server import MCPDOMServer
from .types import (
    CDPResponse, AccessibilityNode, ElementRole, ElementState,
    IndexedElement, PageState
)
from .config import DOMAnalyzerConfig, CDPConfig, AccessibilityConfig, IndexingConfig

__version__ = "0.1.0"
__author__ = "Browser Assistant Team"

__all__ = [
    "CDPClient",
    "CDPSession", 
    "AccessibilityParser",
    "AXProperty",
    "ParsedAXNode",
    "ElementIndexer",
    "IndexedNode",
    "IndexingContext",
    "DOMAnalyzer",
    "PageAnalysisResult",
    "ElementInteractionInfo",
    "MCPDOMTools",
    "mcp_dom_tools",
    "MCPDOMServer",
    "CDPResponse",
    "AccessibilityNode",
    "ElementRole",
    "ElementState",
    "IndexedElement",
    "PageState",
    "DOMAnalyzerConfig",
    "CDPConfig",
    "AccessibilityConfig",
    "IndexingConfig"
]
