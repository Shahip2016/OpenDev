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
import queue
from typing import Any, Optional

from opendev.agent.base import BaseAgent
from opendev.config import AppConfig, ConfigManager
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
        allowed_tools: Optional[list[str]] = None,
    ) -> None:
        self._allowed_tools = allowed_tools
        self.is_subagent: bool = allowed_tools is not None
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

    def build_tool_schemas(self) -> list[dict[str, Any]]:
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
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        model_role: str = "action",
    ) -> dict[str, Any]:
        """
        Execute a single LLM call.

        Selects the appropriate model based on the role, with fallback chains.
        """
        model_config = self._config.models.resolve(model_role)

        # Build the request
        request: dict[str, Any] = {
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

        The ReAct loop alternates between reasoning and action phases:
          Phase 0: Staged context management (compaction)
          Phase 1: Thinking (optional, no tools)
          Phase 2: Action (with tools)
          Phase 3: Decision, dispatch, doom-loop detection
        """
        # Add user message to history
        self.history.add_user(query)

        # Create iteration context
        ctx = IterationContext(
            max_iterations=self._config.max_iterations,
            doom_loop_window=self._config.doom_loop_window,
            doom_loop_threshold=self._config.doom_loop_threshold,
            max_nudge_attempts=self._config.max_nudge_attempts,
            max_todo_nudges=self._config.max_todo_nudges,
        )

        final_response = ""

        while ctx.iteration < ctx.max_iterations and not ctx.cancelled:
            ctx.iteration += 1

            # -- Phase 0: Drain injection queue --
            while not self._injection_queue.empty():
                try:
                    injected = self._injection_queue.get_nowait()
                    self.history.add_user(injected)
                except queue.Empty:
                    break

            # -- Phase 2: Action LLM call --
            messages = self.history.to_api_format()
            system_msg = {"role": "system", "content": self.system_prompt}
            full_messages = [system_msg] + messages

            response = self.call_llm(
                messages=full_messages,
                tools=self.tool_schemas if self.tool_schemas else None,
                model_role="action",
            )

            # Parse the response
            choice = response["choices"][0]
            assistant_msg = choice["message"]
            content = assistant_msg.get("content", "")
            tool_calls_raw = assistant_msg.get("tool_calls", [])

            # Record token usage
            usage = response.get("usage", {})

            if not tool_calls_raw:
                # No tool calls → implicit completion
                self.history.add_assistant(content=content)
                final_response = content or ""
                break

            # Parse tool calls
            tool_calls = []
            for tc in tool_calls_raw:
                func = tc.get("function", {})
                args = func.get("arguments", "{}")
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                tool_calls.append(ToolCall(
                    id=tc.get("id", ""),
                    name=func.get("name", ""),
                    arguments=args,
                ))

            self.history.add_assistant(content=content, tool_calls=tool_calls)

            # -- Phase 3: Doom-loop detection & tool execution --
            doom_detected = False
            for tc in tool_calls:
                if ctx.add_fingerprint(tc.fingerprint):
                    doom_detected = True

            if doom_detected:
                warning = (
                    "[SYSTEM WARNING] Agent is repeating the same action. "
                    "Try a different approach."
                )
                self.history.add_user(warning)
                continue

            # Execute tools
            for tc in tool_calls:
                if self._tool_registry:
                    result = self._tool_registry.execute(
                        tc.name, tc.arguments, deps=deps,
                    )
                else:
                    result = ToolResult(
                        tool_call_id=tc.id,
                        name=tc.name,
                        content=f"Tool '{tc.name}' executed successfully.",
                    )
                self.history.add_tool_result(result)

        return final_response

    # -- Injection queue (thread-safe message delivery) ---------------------

    def inject_message(self, content: str) -> bool:
        """Inject a follow-up message from the UI thread."""
        try:
            self._injection_queue.put_nowait(content)
            return True
        except queue.Full:
            return False
