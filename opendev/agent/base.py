"""
Base agent and agent interface definitions (Section 2.2.1).

All agents inherit from BaseAgent with eager construction:
  - build_system_prompt() and build_tool_schemas() are called in __init__
  - By the time __init__ completes, the agent is fully ready to serve

AgentInterface is a @runtime_checkable Protocol that downstream code
depends on, decoupling factory from concrete agent class.
"""

from __future__ import annotations

import abc
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from opendev.config import AppConfig


# ---------------------------------------------------------------------------
# Agent Interface Protocol (Section 2.2.1)
# ---------------------------------------------------------------------------

@runtime_checkable
class AgentInterface(Protocol):
    """
    Runtime-checkable Protocol for agent instances.

    Downstream code depends on this interface rather than BaseAgent directly,
    decoupling the factory from the concrete agent class.
    """

    system_prompt: str
    tool_schemas: List[Dict[str, Any]]

    def refresh_tools(self) -> None:
        """Re-invoke build methods when tool registry changes."""
        ...

    def call_llm(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        model_role: str = "action",
    ) -> Dict[str, Any]:
        """Execute a single LLM call."""
        ...

    def run_sync(
        self,
        query: str,
        deps: Any = None,
    ) -> str:
        """Run a full ReAct loop for the given query."""
        ...


# ---------------------------------------------------------------------------
# Base Agent (Section 2.2.1)
# ---------------------------------------------------------------------------

class BaseAgent(abc.ABC):
    """
    Abstract base class for all agents.

    Accepts three constructor arguments: config, tool_registry, mode_manager.
    Defines four abstract methods and uses eager construction — both
    build_system_prompt() and build_tool_schemas() are called before
    __init__ returns.

    Design decision: eager construction guarantees every agent is complete
    at construction time, eliminating first-call latency and race conditions
    with MCP server discovery.
    """

    def __init__(
        self,
        config: AppConfig,
        tool_registry: Any = None,
        mode_manager: Any = None,
    ) -> None:
        self._config = config
        self._tool_registry = tool_registry
        self._mode_manager = mode_manager

        # Eager construction: build prompt and schemas immediately
        self.system_prompt: str = self.build_system_prompt()
        self.tool_schemas: List[Dict[str, Any]] = self.build_tool_schemas()

    @abc.abstractmethod
    def build_system_prompt(self) -> str:
        """Assemble the system prompt string."""
        ...

    @abc.abstractmethod
    def build_tool_schemas(self) -> List[Dict[str, Any]]:
        """Return OpenAI-format tool schemas."""
        ...

    @abc.abstractmethod
    def call_llm(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        model_role: str = "action",
    ) -> Dict[str, Any]:
        """Execute a single LLM call."""
        ...

    @abc.abstractmethod
    def run_sync(
        self,
        query: str,
        deps: Any = None,
    ) -> str:
        """Run a full ReAct loop for the given query."""
        ...

    def refresh_tools(self) -> None:
        """
        Re-invoke both build methods when the tool registry changes
        (e.g., after MCP server discovery or dynamic skill loading).
        """
        self.system_prompt = self.build_system_prompt()
        self.tool_schemas = self.build_tool_schemas()
