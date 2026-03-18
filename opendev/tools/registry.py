"""
Tool registry — central dispatcher (Section 2.4.1).

Maps tool names to handler methods across 12 handler classes organized
by category (file, process, web, symbols, user interaction, task
management, thinking, MCP discovery, batch execution).

Separates three concerns:
  1. Schema construction (ToolSchemaBuilder)
  2. Dispatch routing (ToolRegistry)
  3. Lifecycle hooks (pre/post execution)
"""

from __future__ import annotations

import logging
import concurrent.futures
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from opendev.config import AgentMode
from opendev.models import ToolResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool execution context
# ---------------------------------------------------------------------------

@dataclass
class ToolExecutionContext:
    """
    Cross-cutting services passed to every tool handler.

    Bundles mode_manager, approval_manager, undo_manager, task_monitor,
    session_manager, ui_callback, and file_time_tracker.
    """
    mode_manager: Any = None
    approval_manager: Any = None
    undo_manager: Any = None
    task_monitor: Any = None
    session_manager: Any = None
    ui_callback: Any = None
    file_time_tracker: Any = None
    working_dir: str = "."


# ---------------------------------------------------------------------------
# Tool Registry
# ---------------------------------------------------------------------------

class ToolRegistry:
    """
    Central tool dispatcher.

    Maps tool names → handler callables. Enforces mode restrictions
    (blocking writes in plan mode). Supports batch execution
    (parallel/serial), MCP tool discovery, and lifecycle hooks.
    """

    # Tools that are safe in plan mode (read-only)
    READ_ONLY_TOOLS = frozenset([
        "read_file", "list_files", "search", "find_symbol", "list_symbols",
        "find_referencing_symbols", "fetch_url", "web_search", "browse_url",
        "capture_web_screenshot", "screenshot", "list_processes", "get_process_output",
        "list_todos", "search_tools",
    ])

    # Write tools that require approval in semi-auto mode
    WRITE_TOOLS = frozenset([
        "write_file", "edit_file", "run_command", "kill_process",
        "rename_symbol", "replace_symbol_body",
        "insert_before_symbol", "insert_after_symbol",
    ])

    def __init__(self):
        self._handlers: dict[str, Callable] = {}
        self._schemas: list[dict[str, Any]] = []
        self._discovered_mcp_tools: set[str] = set()
        self._mcp_schemas: list[dict[str, Any]] = []
        self._subagent_manager: Any = None
        self._skill_loader: Any = None
        self._hooks: dict[str, list[Callable]] = {}
        self._max_concurrent: int = 5

    # -- Registration -------------------------------------------------------

    def register(self, name: str, handler: Callable, schema: dict[str, Any]) -> None:
        """Register a tool with its handler and schema."""
        self._handlers[name] = handler
        self._schemas.append(schema)

    def register_handler(self, handler: Any) -> None:
        """Register all tools from a handler class."""
        if hasattr(handler, "get_tool_definitions"):
            for defn in handler.get_tool_definitions():
                self.register(
                    defn["name"],
                    defn["handler"],
                    defn["schema"],
                )

    def register_skill_loader(self, loader: Any) -> None:
        """Register the skill loader for invoke_skill tool."""
        self._skill_loader = loader

    def set_subagent_manager(self, manager: Any) -> None:
        """Register the subagent manager for spawn_subagent tool."""
        self._subagent_manager = manager

    # -- Schema access ------------------------------------------------------

    def get_schemas(self) -> list[dict[str, Any]]:
        """Return all tool schemas (builtin + discovered MCP + subagent)."""
        schemas = list(self._schemas)

        # Add discovered MCP tool schemas
        for mcp_schema in self._mcp_schemas:
            name = mcp_schema.get("function", {}).get("name", "")
            if name in self._discovered_mcp_tools:
                schemas.append(mcp_schema)

        return schemas

    # -- Execution ----------------------------------------------------------

    def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        deps: Any = None,
        ctx: Optional[ToolExecutionContext] = None,
    ) -> ToolResult:
        """
        Execute a tool by name with the given arguments.

        Enforces mode restrictions and fires lifecycle hooks.
        """
        # Mode restriction: block writes in plan mode
        if ctx and ctx.mode_manager:
            current_mode = ctx.mode_manager.get_mode()
            if current_mode == AgentMode.PLAN and tool_name not in self.READ_ONLY_TOOLS:
                return ToolResult(
                    tool_call_id="",
                    name=tool_name,
                    content=f"Error: Tool '{tool_name}' is not available in plan mode. "
                            f"Only read-only tools are accessible during planning.",
                    is_error=True,
                )

        # Fire pre-execution hooks
        hook_block = self._fire_pre_hooks(tool_name, arguments)
        if hook_block:
            return ToolResult(
                tool_call_id="",
                name=tool_name,
                content=f"Blocked by pre-tool hook: {hook_block}",
                is_error=True,
            )

        # Dispatch to handler
        handler = self._handlers.get(tool_name)
        if not handler:
            return ToolResult(
                tool_call_id="",
                name=tool_name,
                content=f"Error: Unknown tool '{tool_name}'",
                is_error=True,
            )

        try:
            result = handler(arguments, ctx=ctx)
            if isinstance(result, ToolResult):
                return result
            return ToolResult(
                tool_call_id="",
                name=tool_name,
                content=str(result),
            )
        except Exception as e:
            logger.error(f"Tool execution error: {tool_name}: {e}")
            return ToolResult(
                tool_call_id="",
                name=tool_name,
                content=f"Error executing {tool_name}: {str(e)[:200]}",
                is_error=True,
            )

    def execute_batch(
        self,
        calls: list[tuple[str, dict[str, Any]]],
        mode: str = "parallel",
        deps: Any = None,
        ctx: Optional[ToolExecutionContext] = None,
    ) -> list[ToolResult]:
        """
        Execute multiple tool calls in batch.

        mode="parallel" → thread pool with max 5 concurrent workers
        mode="serial"   → sequential execution for dependent operations
        """
        if mode == "serial":
            return [
                self.execute(name, args, deps=deps, ctx=ctx)
                for name, args in calls
            ]

        # Parallel execution
        results = []
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=self._max_concurrent
        ) as executor:
            futures = {
                executor.submit(
                    self.execute, name, args, deps=deps, ctx=ctx
                ): i
                for i, (name, args) in enumerate(calls)
            }
            # Collect in order
            ordered = [None] * len(calls)
            for future in concurrent.futures.as_completed(futures):
                idx = futures[future]
                ordered[idx] = future.result()
            results = [r for r in ordered if r is not None]

        return results

    # -- MCP tool discovery -------------------------------------------------

    def discover_mcp_tool(self, tool_name: str) -> None:
        """Mark an MCP tool as discovered (include its schema)."""
        self._discovered_mcp_tools.add(tool_name)

    def register_mcp_schemas(self, schemas: list[dict[str, Any]]) -> None:
        """Register MCP tool schemas (from connected servers)."""
        self._mcp_schemas.extend(schemas)

    # -- Lifecycle hooks ----------------------------------------------------

    def register_hook(self, event: str, callback: Callable) -> None:
        """Register a lifecycle hook callback."""
        if event not in self._hooks:
            self._hooks[event] = []
        self._hooks[event].append(callback)

    def _fire_pre_hooks(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> Optional[str]:
        """Fire pre-tool-use hooks. Returns block reason or None."""
        for hook in self._hooks.get("PRE_TOOL_USE", []):
            try:
                result = hook(tool_name, arguments)
                if result and isinstance(result, str):
                    return result
            except Exception:
                pass
        return None
