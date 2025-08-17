"""
Типы данных для DOM Analyzer

Определяет структуры данных для работы с DOM, Accessibility Tree и индексацией элементов.
"""

from typing import Dict, List, Optional, Union, Any
from pydantic import BaseModel, Field
from enum import Enum


class ElementRole(str, Enum):
    """Роли элементов из Accessibility Tree"""
    BUTTON = "button"
    LINK = "link"
    TEXTBOX = "textbox"
    CHECKBOX = "checkbox"
    RADIO = "radio"
    COMBOBOX = "combobox"
    LISTBOX = "listbox"
    MENU = "menu"
    MENUITEM = "menuitem"
    TAB = "tab"
    TABPANEL = "tabpanel"
    DIALOG = "dialog"
    ALERT = "alert"
    STATUS = "status"
    TOOLBAR = "toolbar"
    TOOLTIP = "tooltip"
    GRID = "grid"
    GRIDCELL = "gridcell"
    ROW = "row"
    COLUMN = "column"
    ROWHEADER = "rowheader"
    COLUMNHEADER = "columnheader"
    GENERIC = "generic"


class ElementState(str, Enum):
    """Состояния элементов"""
    VISIBLE = "visible"
    HIDDEN = "hidden"
    DISABLED = "disabled"
    READONLY = "readonly"
    REQUIRED = "required"
    INVALID = "invalid"
    EXPANDED = "expanded"
    COLLAPSED = "collapsed"
    SELECTED = "selected"
    CHECKED = "checked"
    FOCUSED = "focused"


class IndexedElement(BaseModel):
    """Индексированный элемент страницы"""
    index: int = Field(..., description="Уникальный индекс элемента")
    role: ElementRole = Field(..., description="Роль элемента")
    text: str = Field(..., description="Видимый текст элемента")
    tag_name: str = Field(..., description="HTML тег")
    attributes: Dict[str, str] = Field(default_factory=dict, description="HTML атрибуты")
    states: List[ElementState] = Field(default_factory=list, description="Состояния элемента")
    xpath: str = Field(..., description="XPath элемента")
    bounding_box: Optional[Dict[str, int]] = Field(None, description="Координаты элемента")
    is_interactive: bool = Field(..., description="Можно ли взаимодействовать с элементом")
    parent_index: Optional[int] = Field(None, description="Индекс родительского элемента")
    children_indices: List[int] = Field(default_factory=list, description="Индексы дочерних элементов")


class PageState(BaseModel):
    """Состояние страницы с индексированными элементами"""
    url: str = Field(..., description="URL страницы")
    title: str = Field(..., description="Заголовок страницы")
    timestamp: float = Field(..., description="Время анализа")
    elements: List[IndexedElement] = Field(..., description="Индексированные элементы")
    interactive_count: int = Field(..., description="Количество интерактивных элементов")
    dom_hash: str = Field(..., description="Хеш DOM структуры для кэширования")


class CDPResponse(BaseModel):
    """Ответ от CDP"""
    success: bool = Field(..., description="Успешность операции")
    data: Optional[Any] = Field(None, description="Данные ответа")
    error: Optional[str] = Field(None, description="Описание ошибки")


class AccessibilityNode(BaseModel):
    """Узел Accessibility Tree"""
    node_id: int = Field(..., description="ID узла")
    role: str = Field(..., description="Роль узла")
    name: str = Field(..., description="Имя узла")
    value: Optional[str] = Field(None, description="Значение узла")
    description: Optional[str] = Field(None, description="Описание узла")
    state: Dict[str, Any] = Field(default_factory=dict, description="Состояния узла")
    children: List[int] = Field(default_factory=list, description="ID дочерних узлов")
    parent_id: Optional[int] = Field(None, description="ID родительского узла")
    backend_dom_node_id: Optional[int] = Field(None, description="ID DOM узла")
