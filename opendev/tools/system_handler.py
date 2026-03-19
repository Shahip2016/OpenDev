"""
System-level management tools (Section 2.4.9).

Provides tools for workspace maintenance, checkpoints, and environment info:
  - take_snapshot: Capture current workspace state.
  - restore_snapshot: Revert to a previous state.
  - list_snapshots: View available checkpoints.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from opendev.models import ToolResult
from opendev.tools.base_handler import BaseHandler


class SystemHandler(BaseHandler):
    """Handler for workspace state and system tools."""

    def __init__(self, working_dir: str = ".", snapshot_manager: Any = None):
        super().__init__(working_dir)
        self._snapshot_manager = snapshot_manager

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "take_snapshot",
                "handler": self.take_snapshot,
                "schema": {
                    "type": "function",
                    "function": {
                        "name": "take_snapshot",
                        "description": "Capture the current state of the workspace (all files).",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "label": {"type": "string", "description": "Short label for the snapshot (e.g., 'before_refactor')."},
                            },
                        },
                    },
                },
            },
            {
                "name": "restore_snapshot",
                "handler": self.restore_snapshot,
                "schema": {
                    "type": "function",
                    "function": {
                        "name": "restore_snapshot",
                        "description": "Revert the workspace to a previous snapshot.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "snapshot_id": {"type": "string", "description": "The ID of the snapshot to restore."},
                            },
                            "required": ["snapshot_id"],
                        },
                    },
                },
            },
            {
                "name": "list_snapshots",
                "handler": self.list_snapshots,
                "schema": {
                    "type": "function",
                    "function": {
                        "name": "list_snapshots",
                        "description": "List all available workspace snapshots.",
                        "parameters": {
                            "type": "object",
                            "properties": {},
                        },
                    },
                },
            },
        ]

    def take_snapshot(self, args: Dict[str, Any], **kwargs: Any) -> ToolResult:
        """Capture workspace state."""
        if not self._snapshot_manager:
            return ToolResult(tool_call_id="", name="take_snapshot", content="Error: Snapshot manager not available.", is_error=True)

        label = args.get("label", "manual")
        try:
            snapshot_id = self._snapshot_manager.take_snapshot(label)
            return ToolResult(
                tool_call_id="",
                name="take_snapshot",
                content=f"Workspace snapshot captured: {snapshot_id}",
                summary=f"Created snapshot '{snapshot_id}'"
            )
        except Exception as e:
            return ToolResult(tool_call_id="", name="take_snapshot", content=f"Error capturing snapshot: {e}", is_error=True)

    def restore_snapshot(self, args: Dict[str, Any], **kwargs: Any) -> ToolResult:
        """Revert workspace state."""
        if not self._snapshot_manager:
            return ToolResult(tool_call_id="", name="restore_snapshot", content="Error: Snapshot manager not available.", is_error=True)

        snapshot_id = args.get("snapshot_id", "")
        if not snapshot_id:
            return ToolResult(tool_call_id="", name="restore_snapshot", content="Error: snapshot_id is required.", is_error=True)

        try:
            success = self._snapshot_manager.restore_snapshot(snapshot_id)
            if success:
                return ToolResult(
                    tool_call_id="",
                    name="restore_snapshot",
                    content=f"Workspace restored to snapshot: {snapshot_id}",
                    summary=f"Restored workspace from '{snapshot_id}'"
                )
            else:
                return ToolResult(tool_call_id="", name="restore_snapshot", content=f"Snapshot '{snapshot_id}' not found.", is_error=True)
        except Exception as e:
            return ToolResult(tool_call_id="", name="restore_snapshot", content=f"Error restoring snapshot: {e}", is_error=True)

    def list_snapshots(self, args: Dict[str, Any], **kwargs: Any) -> ToolResult:
        """List all snapshots."""
        if not self._snapshot_manager:
            return ToolResult(tool_call_id="", name="list_snapshots", content="Error: Snapshot manager not available.", is_error=True)

        try:
            snapshots = self._snapshot_manager.list_snapshots()
            if not snapshots:
                return ToolResult(tool_call_id="", name="list_snapshots", content="No snapshots found.")

            lines = ["Available snapshots (newest first):"]
            for s in snapshots:
                lines.append(f"  - {s['id']} (Label: {s['label']})")
            
            output = "\n".join(lines)
            return ToolResult(tool_call_id="", name="list_snapshots", content=output, summary=f"Listed {len(snapshots)} snapshots")
        except Exception as e:
            return ToolResult(tool_call_id="", name="list_snapshots", content=f"Error listing snapshots: {e}", is_error=True)
