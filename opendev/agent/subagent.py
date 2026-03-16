"""
Subagent orchestration (Section 2.2.7).

SubAgentSpec → SubAgentManager.register_subagent() → CompiledSubAgent.

Eight builtin subagent types with filtered tool access:
  - Code Explorer: read-only navigation
  - Planner: read + plan file write
  - PR-Reviewer: code review with diff analysis
  - Security-Reviewer: vulnerability scanning
  - Web-Clone: website replication
  - Web-Generator: site creation
  - Project-Init: scaffold generation
  - Ask-User: minimal UI-only structured surveys
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, TypedDict

from opendev.config import AppConfig


# ---------------------------------------------------------------------------
# Subagent specification
# ---------------------------------------------------------------------------

class SubAgentSpec(TypedDict, total=False):
    """
    Specification for a subagent before compilation.

    Contains name, description, system prompt, optional tool allowlist,
    optional model override, and optional Docker configuration.
    """
    name: str
    description: str
    system_prompt: str
    allowed_tools: Optional[list[str]]
    model_override: Optional[str]
    docker_config: Optional[dict[str, Any]]


@dataclass
class CompiledSubAgent:
    """
    Final compiled subagent ready for execution.

    Contains the agent instance with filtered tool schemas,
    name, description, and tool list.
    """
    name: str
    description: str
    agent: Any  # MainAgent instance
    tool_list: list[str]


# ---------------------------------------------------------------------------
# Default subagent tool sets (Section G - Capability Matrix)
# ---------------------------------------------------------------------------

# Read-only tools common to exploration subagents
_READ_ONLY_TOOLS = [
    "read_file", "list_files", "search", "find_symbol",
    "find_referencing_symbols", "fetch_url", "web_search",
]

# Default tool sets for each builtin subagent type
_BUILTIN_TOOL_SETS: dict[str, list[str]] = {
    "Code-Explorer": _READ_ONLY_TOOLS,
    "Planner": _READ_ONLY_TOOLS + ["write_file"],
    "PR-Reviewer": _READ_ONLY_TOOLS + ["run_command"],
    "Security-Reviewer": _READ_ONLY_TOOLS + ["run_command"],
    "Web-Clone": _READ_ONLY_TOOLS + ["write_file", "fetch_url"],
    "Web-Generator": _READ_ONLY_TOOLS + ["write_file", "edit_file", "run_command"],
    "Project-Init": _READ_ONLY_TOOLS + ["write_file", "run_command"],
    "Ask-User": ["ask_user"],
}


# ---------------------------------------------------------------------------
# SubAgentManager
# ---------------------------------------------------------------------------

class SubAgentManager:
    """
    Manages subagent registration and spawning (Section 2.2.7).

    register_subagent() executes a four-step pipeline:
      1. Resolve tool list (default to safe set if none specified)
      2. Create AppConfig copy with model override if provided
      3. Construct MainAgent with allowed_tools set to resolved list
      4. Set agent._subagent_system_prompt to the spec's prompt override

    Construction is cheap because all subagents share the same tool
    registry reference (no cloning or deep copying).
    """

    def __init__(
        self,
        config: AppConfig,
        tool_registry: Any = None,
        mode_manager: Any = None,
    ):
        self._config = config
        self._tool_registry = tool_registry
        self._mode_manager = mode_manager
        self._compiled: dict[str, CompiledSubAgent] = {}

    def register_subagent(self, spec: SubAgentSpec) -> CompiledSubAgent:
        """
        Compile a SubAgentSpec into a ready-to-execute CompiledSubAgent.

        Four-step pipeline:
          1. Resolve tool list (default to safe read-only set)
          2. Create config copy with model override
          3. Construct MainAgent with filtered tools
          4. Set subagent system prompt override
        """
        from opendev.agent.main_agent import MainAgent

        name = spec["name"]
        description = spec.get("description", "")

        # Step 1: Resolve tool list
        tools = spec.get("allowed_tools") or _READ_ONLY_TOOLS.copy()

        # Step 2: Config with model override
        config = self._config
        # (in full impl, would copy config and apply model_override)

        # Step 3: Construct MainAgent with filtered tools
        agent = MainAgent(
            config=config,
            tool_registry=self._tool_registry,
            mode_manager=self._mode_manager,
            allowed_tools=tools,
        )

        # Step 4: Set subagent system prompt
        if "system_prompt" in spec:
            agent._subagent_system_prompt = spec["system_prompt"]
            agent.system_prompt = spec["system_prompt"]

        compiled = CompiledSubAgent(
            name=name,
            description=description,
            agent=agent,
            tool_list=tools,
        )
        self._compiled[name] = compiled
        return compiled

    def register_defaults(self) -> None:
        """Register all eight builtin subagent types."""
        defaults: list[SubAgentSpec] = [
            {
                "name": "Code-Explorer",
                "description": "Read-only codebase navigation and analysis",
                "system_prompt": (
                    "You are a Code Explorer subagent. Your role is to explore "
                    "and understand codebases using read-only tools.\n\n"
                    "## Stop Conditions\n"
                    "- Stop when evidence is clear\n"
                    "- Stop if progress stalls\n"
                    "- Prefer depth over breadth\n"
                    "- Re-reading the same file triggers immediate stop"
                ),
                "allowed_tools": _BUILTIN_TOOL_SETS["Code-Explorer"],
            },
            {
                "name": "Planner",
                "description": "Strategic planning with read-only exploration + plan writing",
                "system_prompt": (
                    "You are a Planner subagent. Explore the codebase, analyze "
                    "patterns, and produce a structured plan with:\n"
                    "1. Goal\n2. Context\n3. Files to modify\n"
                    "4. New files to create\n5. Implementation steps\n"
                    "6. Verification criteria\n7. Risks\n\n"
                    "Include plan_file_path in your completion summary."
                ),
                "allowed_tools": _BUILTIN_TOOL_SETS["Planner"],
            },
            {
                "name": "PR-Reviewer",
                "description": "Code review with diff analysis",
                "system_prompt": (
                    "You are a PR Reviewer subagent. Analyze code changes, "
                    "identify potential issues, and provide constructive feedback."
                ),
                "allowed_tools": _BUILTIN_TOOL_SETS["PR-Reviewer"],
            },
            {
                "name": "Security-Reviewer",
                "description": "Security vulnerability scanning and analysis",
                "system_prompt": (
                    "You are a Security Reviewer subagent. Scan code for "
                    "security vulnerabilities, unsafe patterns, and potential "
                    "attack vectors."
                ),
                "allowed_tools": _BUILTIN_TOOL_SETS["Security-Reviewer"],
            },
            {
                "name": "Web-Clone",
                "description": "Website content replication",
                "system_prompt": (
                    "You are a Web Clone subagent. Fetch and replicate web "
                    "content, preserving structure and styling."
                ),
                "allowed_tools": _BUILTIN_TOOL_SETS["Web-Clone"],
            },
            {
                "name": "Web-Generator",
                "description": "Website creation from specifications",
                "system_prompt": (
                    "You are a Web Generator subagent. Create websites from "
                    "specifications, writing clean HTML/CSS/JS."
                ),
                "allowed_tools": _BUILTIN_TOOL_SETS["Web-Generator"],
            },
            {
                "name": "Project-Init",
                "description": "Project scaffold generation",
                "system_prompt": (
                    "You are a Project Init subagent. Generate project "
                    "scaffolding, directory structures, and boilerplate files."
                ),
                "allowed_tools": _BUILTIN_TOOL_SETS["Project-Init"],
            },
            {
                "name": "Ask-User",
                "description": "Structured user interaction for gathering requirements",
                "system_prompt": (
                    "You are an Ask-User subagent. Gather requirements and "
                    "preferences via structured multi-choice questions."
                ),
                "allowed_tools": _BUILTIN_TOOL_SETS["Ask-User"],
            },
        ]

        for spec in defaults:
            self.register_subagent(spec)

    def get(self, name: str) -> Optional[CompiledSubAgent]:
        """Get a compiled subagent by name."""
        return self._compiled.get(name)

    def list_agents(self) -> list[str]:
        """List all registered subagent names."""
        return list(self._compiled.keys())

    def spawn(self, name: str, query: str, deps: Any = None) -> str:
        """
        Spawn a subagent to handle a specific query.

        Each subagent runs in an isolated context with its own
        iteration budget and filtered tool access.
        """
        compiled = self._compiled.get(name)
        if not compiled:
            return f"Error: Unknown subagent '{name}'"

        # Run in isolated context (fresh history, no session persistence)
        return compiled.agent.run_sync(query, deps=deps)
