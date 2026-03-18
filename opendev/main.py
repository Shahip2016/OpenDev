"""
Command Line Interface (CLI) entry point (Table 5).

Parses arguments, initializes the configuration 4-tier hierarchy,
assembles the agent factory, and launches the interactive REPL.
"""

from __future__ import annotations

import argparse
import sys

from opendev.agent.factory import AgentFactory
from opendev.config import AppConfig, ConfigManager
from opendev.context.compactor import ContextCompactor
from opendev.context.prompt_composer import create_default_composer
from opendev.context.reminders import ReminderSystem
from opendev.persistence.session import SessionManager
from opendev.safety.approvals import ApprovalManager, ModeManager
from opendev.safety.undo import UndoManager
from opendev.tools.file_handler import FileHandler
from opendev.tools.mcp_client import MCPClientManager
from opendev.tools.process_handler import ProcessHandler
from opendev.tools.search_handler import SymbolSearchHandler
from opendev.tools.registry import ToolExecutionContext, ToolRegistry
from opendev.tools.schema_builder import ToolSchemaBuilder


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="OpenDev: Terminal-native AI software engineering agent."
    )
    parser.add_argument("--mode", choices=["auto", "semi-auto", "plan"], default="semi-auto", help="Execution mode (default: semi-auto)")
    parser.add_argument("--thinking", choices=["high", "medium", "low", "off"], default="medium", help="Reasoning depth (default: medium)")
    parser.add_argument("--provider", choices=["anthropic", "openai"], default=None, help="Force LLM provider")
    parser.add_argument("--resume", type=str, metavar="SESSION_ID", help="Resume an existing session")
    parser.add_argument("--tui", action="store_true", help="Launch interactive Textual TUI")
    return parser.parse_args()


# -- REPL Stubs (Simulated UI) ----------------------------------------------

def _ui_approval_callback(tool_name: str, details: str, risk: Any) -> bool:
    """CLI approval prompt block."""
    try:
        from rich.console import Console
        console = Console()
        console.print(f"\n[bold yellow]Approval Required: {tool_name}[/]")
        console.print(f"[dim]{details}[/]")
        result = input(f"Approve {risk.name} risk action? [y/N/edit]: ").strip().lower()
        return result == "y"
    except Exception:
        # Fallback if rich not installed
        print(f"\nApproval Required: {tool_name}")
        print(details)
        result = input(f"Approve {risk} risk action? [y/N/edit]: ").strip().lower()
        return result == "y"


def main() -> int:
    """Main CLI entry point."""
    args = _parse_args()

    # 1. Configuration (4-tier hierarchy)
    config_mgr = ConfigManager()
    config = config_mgr.get_config()
    
    # Apply CLI overrides
    if args.provider:
        config.models.action.provider = args.provider
        config.models.thinking.provider = args.provider
    config.set_mode(args.mode)
    config.set_thinking(args.thinking)

    # 2. Safety & Persistence
    mode_mgr = ModeManager(config.agent_mode)
    approval_mgr = ApprovalManager(mode_mgr, _ui_approval_callback)
    undo_mgr = UndoManager()
    session_mgr = SessionManager(config)

    # 3. Tool Registry & Handlers
    registry = ToolRegistry()
    registry.register_hook("PRE_TOOL_USE", undo_mgr.pre_hook_handler)

    file_handler = FileHandler()
    process_handler = ProcessHandler()
    symbol_handler = SymbolSearchHandler()

    registry.register_handler(file_handler)
    registry.register_handler(process_handler)
    registry.register_handler(symbol_handler)

    mcp_client = MCPClientManager(registry)
    mcp_client.connect_all([f"{config.user_config_dir}/mcp.json"])

    # 4. Context Engineering
    composer = create_default_composer(config)
    compactor = ContextCompactor(max_tokens=config.max_context_tokens)
    reminder_sys = ReminderSystem()

    # 5. Agent Factory (3-Phase Pipeline)
    factory = AgentFactory(config, registry, mode_mgr)
    suite = factory.create_agents()
    main_agent = suite.main_agent

    # 6. Schema Builder Setup
    builder = ToolSchemaBuilder(registry)
    main_agent.tool_schemas = builder.build()

    # 7. Start interactive UI
    if args.tui:
        from opendev.tui import launch_tui
        launch_tui(suite, config)
        return 0

    # REPL loop (stub for actual toolkit prompt)
    console.print("\nType [dim]/help[/] for commands or just start typing tasks.")
    
    # In a full run, we would launch a prompt-toolkit REPL here.
    return 0


if __name__ == "__main__":
    sys.exit(main())
