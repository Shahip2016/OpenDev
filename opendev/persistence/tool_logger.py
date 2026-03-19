"""
Persistent log of tool executions (Section 2.5.2).

Records every tool call and its result to a dedicated JSONL file
for auditability, debugging, and trans-session learning.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, Optional

from opendev.models import ToolCall, ToolResult

logger = logging.getLogger(__name__)


class ToolLogger:
    """
    Handles logging of tool interactions to disk.
    """

    def __init__(self, log_dir: str = ".opendev/logs"):
        self.log_dir = log_dir
        os.makedirs(self.log_dir, exist_ok=True)
        self._current_log_path: Optional[str] = None

    def start_session(self, session_id: str) -> None:
        """Set the active log file for the session."""
        self._current_log_path = os.path.join(self.log_dir, f"tools_{session_id}.jsonl")

    def log_call(self, tool_call: ToolCall) -> None:
        """Record a tool call before execution."""
        if not self._current_log_path:
            return

        entry = {
            "type": "call",
            "timestamp": time.time(),
            "id": tool_call.id,
            "name": tool_call.name,
            "arguments": tool_call.arguments,
        }
        self._write_entry(entry)

    def log_result(self, result: ToolResult) -> None:
        """Record a tool result after execution."""
        if not self._current_log_path:
            return

        entry = {
            "type": "result",
            "timestamp": time.time(),
            "id": result.tool_call_id,
            "name": result.name,
            "content": result.content,
            "is_error": result.is_error,
        }
        self._write_entry(entry)

    def _write_entry(self, entry: Dict[str, Any]) -> None:
        """Append a JSON entry to the log file."""
        try:
            with open(self._current_log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except OSError as e:
            logger.error(f"Failed to write to tool log: {e}")
