"""
Base handler class for tool categories (Section 2.4.1).

Each handler category receives a ToolExecutionContext with cross-cutting
services and registers its tools with the ToolRegistry.
"""

from __future__ import annotations

from abc import ABC
from typing import Any, Dict, List


class BaseHandler(ABC):
    """
    Abstract base for tool handler categories.

    Subclasses implement get_tool_definitions() returning a list of
    {name, handler, schema} dicts, and individual handler methods.
    """

    def __init__(self, working_dir: str = "."):
        self._working_dir = working_dir

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """
        Return list of tool definitions for registration.

        Each definition is a dict with:
          - name: str
          - handler: callable
          - schema: dict (OpenAI function schema)
        """
        return []
