"""
Tool schema builder (Section 2.4.1).

Assembles JSON schemas from three sources:
  1. Static _BUILTIN_TOOL_SCHEMAS (∼40 built-in tools)
  2. Dynamically discovered MCP schemas
  3. Subagent schemas injected by SubAgentManager
"""

from __future__ import annotations

from typing import Any, Optional


# ---------------------------------------------------------------------------
# Built-in tool schema definitions
# ---------------------------------------------------------------------------

_BUILTIN_TOOL_SCHEMAS: list[dict[str, Any]] = [
    # -- File Operations --
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read file contents with line numbers. Supports offset and max_lines parameters.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Path to the file to read"},
                    "offset": {"type": "integer", "description": "1-based line start (default 1)", "default": 1},
                    "max_lines": {"type": "integer", "description": "Maximum lines to read (default 2000)", "default": 2000},
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create a new file. Rejects overwrites of existing files (use edit_file instead).",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Path for the new file"},
                    "content": {"type": "string", "description": "File content to write"},
                    "create_dirs": {"type": "boolean", "description": "Auto-create parent directories", "default": True},
                },
                "required": ["file_path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Edit an existing file using search-and-replace with 9-pass fuzzy matching.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Path to file to edit"},
                    "old_content": {"type": "string", "description": "Content to find (fuzzy matched)"},
                    "new_content": {"type": "string", "description": "Replacement content"},
                },
                "required": ["file_path", "old_content", "new_content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List directory contents or search with glob patterns.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory to list", "default": "."},
                    "pattern": {"type": "string", "description": "Glob pattern for filtering"},
                    "max_results": {"type": "integer", "description": "Maximum results", "default": 100},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search",
            "description": "Dual-mode content search: text (ripgrep regex) or ast (structural patterns).",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Regex or ast-grep pattern"},
                    "path": {"type": "string", "description": "Search root directory", "default": "."},
                    "type": {"type": "string", "enum": ["text", "ast"], "description": "Search mode", "default": "text"},
                    "lang": {"type": "string", "description": "Language hint for ast mode"},
                },
                "required": ["pattern"],
            },
        },
    },
    # -- Process --
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Execute a shell command with safety gates and timeout handling.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to execute"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 60},
                    "background": {"type": "boolean", "description": "Run in background", "default": False},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_processes",
            "description": "List all tracked background tasks with PID, status, and runtime.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_process_output",
            "description": "Retrieve the last 100 lines from a background task's output.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Background task ID"},
                },
                "required": ["task_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kill_process",
            "description": "Terminate a running background task with graceful escalation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Background task ID to terminate"},
                },
                "required": ["task_id"],
            },
        },
    },
    # -- Web --
    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": "Fetch web content using browser engine, converting HTML to markdown.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to fetch"},
                    "max_chars": {"type": "integer", "description": "Max output characters", "default": 50000},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web via DuckDuckGo. Returns up to 10 results.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "domain": {"type": "string", "description": "Restrict to specific domain"},
                },
                "required": ["query"],
            },
        },
    },
    # -- Symbols (LSP) --
    {
        "type": "function",
        "function": {
            "name": "find_symbol",
            "description": "Find symbol definitions via LSP. Supports qualified names, partial matches, wildcards.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol_name": {"type": "string", "description": "Symbol to find (e.g., MyClass.method)"},
                    "file_path": {"type": "string", "description": "Optional file scope"},
                },
                "required": ["symbol_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_referencing_symbols",
            "description": "Find all references to a symbol across files via LSP.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol_name": {"type": "string", "description": "Symbol to find references for"},
                    "file_path": {"type": "string", "description": "File where symbol is defined"},
                },
                "required": ["symbol_name", "file_path"],
            },
        },
    },
    # -- Task Management --
    {
        "type": "function",
        "function": {
            "name": "write_todos",
            "description": "Create or replace the entire task list.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tasks": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "description": {"type": "string"},
                                "status": {"type": "string", "enum": ["todo", "doing", "done"]},
                            },
                        },
                    },
                },
                "required": ["tasks"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "task_complete",
            "description": "Signal that the current task is finished.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "Completion summary"},
                    "status": {"type": "string", "enum": ["success", "failure"]},
                },
                "required": ["summary"],
            },
        },
    },
    # -- User Interaction --
    {
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": "Present structured multi-choice questions to the user.",
            "parameters": {
                "type": "object",
                "properties": {
                    "questions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "header": {"type": "string"},
                                "options": {"type": "array", "items": {"type": "object"}},
                            },
                        },
                    },
                },
                "required": ["questions"],
            },
        },
    },
    # -- Subagent --
    {
        "type": "function",
        "function": {
            "name": "spawn_subagent",
            "description": "Launch an isolated subagent for a specialized subtask.",
            "parameters": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "description": "Subagent type (e.g., Code-Explorer, Planner)"},
                    "query": {"type": "string", "description": "Task for the subagent"},
                    "background": {"type": "boolean", "default": False},
                },
                "required": ["type", "query"],
            },
        },
    },
    # -- Discovery --
    {
        "type": "function",
        "function": {
            "name": "search_tools",
            "description": "Search for external tools via MCP servers using keywords.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query for tools"},
                    "detail": {"type": "string", "enum": ["names", "brief", "full"], "default": "brief"},
                },
                "required": ["query"],
            },
        },
    },
    # -- Planning --
    {
        "type": "function",
        "function": {
            "name": "present_plan",
            "description": "Display a plan for user review and approval.",
            "parameters": {
                "type": "object",
                "properties": {
                    "plan_file_path": {"type": "string", "description": "Path to the plan file"},
                },
                "required": ["plan_file_path"],
            },
        },
    },
    # -- Skills --
    {
        "type": "function",
        "function": {
            "name": "invoke_skill",
            "description": "Load a skill's instructional content into the conversation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Skill name to invoke"},
                },
                "required": ["name"],
            },
        },
    },
    # -- Batch --
    {
        "type": "function",
        "function": {
            "name": "batch_tool",
            "description": "Execute multiple tool calls in a single turn (parallel or serial).",
            "parameters": {
                "type": "object",
                "properties": {
                    "mode": {"type": "string", "enum": ["parallel", "serial"]},
                    "calls": {"type": "array", "items": {"type": "object"}},
                },
                "required": ["mode", "calls"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Schema Builder
# ---------------------------------------------------------------------------

class ToolSchemaBuilder:
    """
    Assembles JSON schemas from three sources (Section 2.4.1):
      1. Static builtin tool schemas
      2. Dynamically discovered MCP schemas
      3. Subagent schemas from SubAgentManager

    Supports filtering by allowed_tools list for subagents.
    """

    def __init__(
        self,
        registry: Any = None,
        allowed_tools: Optional[list[str]] = None,
    ):
        self._registry = registry
        self._allowed_tools = allowed_tools

    def build(self) -> list[dict[str, Any]]:
        """Build the complete tool schema list."""
        schemas = list(_BUILTIN_TOOL_SCHEMAS)

        # Add MCP schemas from registry
        if self._registry:
            for schema in self._registry.get_schemas():
                if schema not in schemas:
                    schemas.append(schema)

        # Filter by allowed tools
        if self._allowed_tools is not None:
            schemas = [
                s for s in schemas
                if s.get("function", {}).get("name") in self._allowed_tools
            ]

        return schemas

    @staticmethod
    def get_builtin_schemas() -> list[dict[str, Any]]:
        """Return all builtin tool schemas."""
        return list(_BUILTIN_TOOL_SCHEMAS)
