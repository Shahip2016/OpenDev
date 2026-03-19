"""
MainAgent — the single concrete agent class (Section 2.2.1).

There is no class hierarchy of agent types. MainAgent is the only concrete
subclass of BaseAgent, and every agent in the system (main, subagents,
custom agents) is an instance of this single class.

Behavioral variation comes from construction parameters:
  - allowed_tools: filters which tool schemas appear
  - _subagent_system_prompt: override prompt set after construction
  - is_subagent: derived from whether allowed_tools is non-null
"""

from __future__ import annotations

import json
import os
import queue
from typing import Any, Dict, List, Optional

from opendev.agent.base import BaseAgent
from opendev.agent.react_executor import ReactExecutor
from opendev.config import AppConfig, ConfigManager
from opendev.persistence.snapshot_manager import SnapshotManager
from opendev.persistence.tool_logger import ToolLogger
from opendev.models import (
    ConversationHistory,
    IterationContext,
    Message,
    Role,
    ToolCall,
    ToolResult,
)


class MainAgent(BaseAgent):
    """
    Single concrete subclass of BaseAgent.

    Every agent (main, builtin subagents, user-defined custom agents)
    is an instance of this class. Behavioral variation comes entirely
    from construction parameters.
    """

    def __init__(
        self,
        config: AppConfig,
        tool_registry: Any = None,
        mode_manager: Any = None,
        memory_manager: Any = None,
        snapshot_manager: Any = None,
        allowed_tools: Optional[List[str]] = None,
        depth: int = 0,
    ) -> None:
        self._memory_manager = memory_manager
        self._allowed_tools = allowed_tools
        self.is_subagent: bool = allowed_tools is not None
        self._depth = depth
        self._subagent_system_prompt: Optional[str] = None

        # Lazy HTTP client slots for the five model roles (Section 2.2.5)
        # Each materializes a provider-specific client on first access
        self._normal_client: Any = None   # action model
        self._thinking_client: Any = None  # thinking model
        self._critique_client: Any = None  # critique model
        self._vlm_client: Any = None       # vision model

        # Thread-safe message injection queue (Web UI support)
        self._injection_queue: queue.Queue = queue.Queue(maxsize=10)

        # Conversation history
        self.history = ConversationHistory()

        # Tool execution logger (Feature 2)
        self.tool_logger = ToolLogger(
            log_dir=os.path.join(config.user_config_dir, "logs")
        )

        # Snapshot manager (Feature 3)
        self.snapshot_manager = snapshot_manager or SnapshotManager(
            workspace_dir=config.working_dir,
            snapshot_dir=os.path.join(config.user_config_dir, "snapshots")
        )

        # Eager construction via parent
        super().__init__(config, tool_registry, mode_manager)

    # -- Build methods (called eagerly in __init__) -------------------------

    def build_system_prompt(self) -> str:
        """
        Assemble the system prompt.

        If a subagent system prompt override is set, use that.
        Otherwise, compose from modular prompt sections.
        """
        if self._subagent_system_prompt:
            return self._subagent_system_prompt

        # Core identity prompt
        parts = [
            "You are OpenDev, an AI-powered command-line agent for software engineering.",
            "",
            "You operate as a terminal-native coding assistant with access to tools for",
            "reading files, editing code, searching codebases, running commands, and more.",
            "",
            "## Core Principles",
            "- Always read a file before editing it",
            "- Use the most appropriate tool for each task",
            "- Follow the read-before-edit safety pattern",
            "- Report progress via task management tools",
            "- Ask for clarification when requirements are ambiguous",
        ]

        if not self.is_subagent:
            parts.extend([
                "",
                "## Tool Selection Guidelines",
                "- Symbol names (e.g., AuthController.validate) → use find_symbol",
                "- String literals / error messages → use search (text mode)",
                "- Structural patterns (e.g., all if-statements) → use search (ast mode)",
                "- File paths / naming conventions → use list_files",
                "",
                "## Safety Policy",
                "- Never execute destructive commands without approval",
                "- Always create backups before modifying critical files",
                "- Read files before editing to prevent stale-content overwrites",
                "- Follow git workflow conventions",
            ])

        return "\n".join(parts)

    def build_tool_schemas(self) -> List[Dict[str, Any]]:
        """
        Return OpenAI-format tool schemas.

        If allowed_tools is set, only include schemas for those tools.
        """
        if self._tool_registry is None:
            return []

        all_schemas = self._tool_registry.get_schemas()

        if self._allowed_tools is not None:
            return [
                s for s in all_schemas
                if s.get("function", {}).get("name") in self._allowed_tools
            ]

        return all_schemas

    # -- LLM Interaction ----------------------------------------------------

    def call_llm(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        model_role: str = "action",
    ) -> Dict[str, Any]:
        """
        Execute a single LLM call.

        Selects the appropriate model based on the role, with fallback chains.
        """
        model_config = self._config.models.resolve(model_role)

        # Build the request
        request: Dict[str, Any] = {
            "model": model_config.model,
            "messages": messages,
            "temperature": model_config.temperature,
            "max_tokens": model_config.max_tokens,
        }

        if tools:
            request["tools"] = tools

        # In a full implementation, this would call the actual API
        # For now, return a placeholder structure
        return {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": "I'll help you with that task.",
                    "tool_calls": [],
                },
                "finish_reason": "stop",
            }],
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
        }

    # -- ReAct execution (Section 2.2.6) ------------------------------------

    def run_sync(
        self,
        query: str,
        deps: Any = None,
    ) -> str:
        """
        Run a full ReAct loop for the given query.
        Delegates to ReactExecutor (Algorithm 1).
        """
        executor = ReactExecutor(
            agent=self,
            config=self._config,
            tool_registry=self._tool_registry,
            memory_manager=self._memory_manager,
            tool_logger=self.tool_logger,
            depth=self._depth,
        )
        summary, error, latency = executor.execute(query, self.history, deps)
        return summary

    # -- Injection queue (thread-safe message delivery) ---------------------

    def inject_message(self, content: str) -> bool:
        """Inject a follow-up message from the UI thread."""
        try:
            self._injection_queue.put_nowait(content)
            return True
        except queue.Full:
            return False
