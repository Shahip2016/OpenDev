"""
Agent execution modes and approval levels (Section 2.5.3).

Three execution modes:
  - AUTO: Fully autonomous, no approval required for any action.
  - SEMI-AUTO: Approval required for medium/high risk actions.
  - PLAN: Read-only mode. Write/execute tools are hard-blocked.

Approval levels:
  - NONE: Read operations (read_file, search)
  - MEDIUM: Local state changes (write_file, edit_file)
  - HIGH: System changes, network, irreversible (run_command, drop db)
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from opendev.config import AgentMode, ApprovalLevel

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Mode Management
# ---------------------------------------------------------------------------

class ModeManager:
    """
    Manages the current execution mode (AUTO, SEMI-AUTO, PLAN).
    Enforces mode transitions and tool access restrictions.
    """

    def __init__(self, initial_mode: AgentMode = AgentMode.SEMI_AUTO):
        self._mode = initial_mode
        self._listeners: list[Callable[[AgentMode], None]] = []

    def get_mode(self) -> AgentMode:
        return self._mode

    def set_mode(self, mode: AgentMode) -> None:
        """Change mode and notify listeners."""
        if self._mode != mode:
            logger.info(f"Mode changed: {self._mode.value} -> {mode.value}")
            self._mode = mode
            for listener in self._listeners:
                listener(mode)

    def register_listener(self, listener: Callable[[AgentMode], None]) -> None:
        self._listeners.append(listener)


# ---------------------------------------------------------------------------
# Approval Management
# ---------------------------------------------------------------------------

class ApprovalManager:
    """
    Evaluates actions against the current mode and requests human
    approval via UI callbacks when necessary (Section 2.5.3, Table 7).
    """

    def __init__(
        self,
        mode_manager: ModeManager,
        ui_callback: Callable[[str, str, ApprovalLevel], bool],
    ):
        self._mode_manager = mode_manager
        self._ui_callback = ui_callback

        # Tool risk classifications
        self._risk_levels = {
            # Low / None (implicitly allowed in all modes)
            "read_file": ApprovalLevel.NONE,
            "list_files": ApprovalLevel.NONE,
            "search": ApprovalLevel.NONE,
            "find_symbol": ApprovalLevel.NONE,
            "fetch_url": ApprovalLevel.NONE,

            # Medium (requires approval in SEMI-AUTO)
            "write_file": ApprovalLevel.MEDIUM,
            "edit_file": ApprovalLevel.MEDIUM,
            "rename_symbol": ApprovalLevel.MEDIUM,
            "kill_process": ApprovalLevel.MEDIUM,
            "spawn_subagent": ApprovalLevel.MEDIUM,

            # High (requires approval in SEMI-AUTO and strict scrutiny)
            "run_command": ApprovalLevel.HIGH,
        }

    def requires_approval(self, tool_name: str, args: dict[str, Any]) -> bool:
        """
        Determine if the action requires human approval.

        Logic:
          - AUTO mode: Nothing requires approval.
          - PLAN mode: Handled by ToolRegistry (hard blocks writes).
          - SEMI-AUTO mode: Medium/High risk tools require approval.
            Special case: Some 'run_command' calls (like `ls` or `git status`)
            might be auto-approved via heuristics in a full implementation.
        """
        mode = self._mode_manager.get_mode()
        if mode == AgentMode.AUTO:
            return False

        if mode == AgentMode.PLAN:
            # Plan mode blocks all writes at the registry level.
            # If it reached here, it's a read tool.
            return False

        # SEMI-AUTO mode
        risk = self._risk_levels.get(tool_name, ApprovalLevel.HIGH)

        if risk == ApprovalLevel.NONE:
            return False

        # Heuristic: Auto-approve safe read-only shell commands
        if tool_name == "run_command":
            cmd = args.get("command", "").strip().lower()
            safe_prefixes = [
                "ls", "cat", "git status", "git log", "git diff", "echo", "pwd"
            ]
            if any(cmd.startswith(p) for p in safe_prefixes) and "|" not in cmd and ">" not in cmd:
                return False

        return True

    def request_approval(self, tool_name: str, args: dict[str, Any]) -> bool:
        """Request approval from the user via the UI callback."""
        if not self.requires_approval(tool_name, args):
            return True

        risk = self._risk_levels.get(tool_name, ApprovalLevel.HIGH)

        # Format details for user review
        details = []
        for k, v in args.items():
            if k == "content" and isinstance(v, str) and len(v) > 200:
                v = v[:200] + "..."
            details.append(f"  {k}: {v}")
        detail_str = "\n".join(details)

        try:
            # Blocks until UI callback returns boolean
            return self._ui_callback(tool_name, detail_str, risk)
        except Exception as e:
            logger.error(f"Approval callback failed: {e}")
            return False
