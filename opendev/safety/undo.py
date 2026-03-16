"""
Transactional capability for file modifications (Section 2.5.4).

Maintains a stack of file diffs for single-step and global undo,
allowing the user to roll back unintended changes made by the agent
or subagents across nested execution boundaries.
"""

from __future__ import annotations

import difflib
import logging
import os
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class UndoRecord:
    """Represents a single file modification."""
    tool_call_id: str
    file_path: str
    content_before: Optional[str]  # None if file was created
    content_after: str


class UndoManager:
    """
    Manages a stack of file diffs for transactional rollback.
    """

    def __init__(self, max_history: int = 50):
        self._history: list[UndoRecord] = []
        self._max_history = max_history

    def record_change(
        self,
        tool_call_id: str,
        file_path: str,
        content_before: Optional[str],
        content_after: str,
    ) -> None:
        """Push a file change onto the undo stack."""
        record = UndoRecord(tool_call_id, file_path, content_before, content_after)
        self._history.append(record)

        if len(self._history) > self._max_history:
            self._history.pop(0)

        logger.debug(f"Recorded undo snapshot for {file_path}")

    def undo_last(self) -> Optional[UndoRecord]:
        """Pop and revert the most recent file change."""
        if not self._history:
            return None

        record = self._history.pop()

        try:
            if record.content_before is None:
                # File was created, delete it
                if os.path.exists(record.file_path):
                    os.remove(record.file_path)
            else:
                # Revert to previous content
                with open(record.file_path, "w", encoding="utf-8") as f:
                    f.write(record.content_before)

            logger.info(f"Undid change: {record.file_path}")
            return record

        except OSError as e:
            logger.error(f"Undo failed for {record.file_path}: {e}")
            return None

    def undo_all(self, tool_call_id: str) -> int:
        """Undo all changes associated with a specific tool call ID."""
        records = [r for r in self._history if r.tool_call_id == tool_call_id]

        if not records:
            return 0

        # Revert in reverse chronological order
        count = 0
        for record in reversed(records):
            try:
                if record.content_before is None and os.path.exists(record.file_path):
                    os.remove(record.file_path)
                elif record.content_before is not None:
                    with open(record.file_path, "w", encoding="utf-8") as f:
                        f.write(record.content_before)
                count += 1
            except OSError:
                pass

        # Remove reverted records from history
        self._history = [r for r in self._history if r.tool_call_id != tool_call_id]

        return count

    def pre_hook_handler(self, tool_name: str, args: dict[str, Any]) -> None:
        """
        Pre-tool hook to capture file state before an edit.
        (Called via ToolRegistry).
        """
        # Only capture writes
        if tool_name not in ["write_file", "edit_file"]:
            return

        file_path = args.get("file_path", "")
        if not file_path:
            return

        if not os.path.exists(file_path):
            self.record_change(args.get("__call_id", "manual"), file_path, None, "")
        else:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                self.record_change(args.get("__call_id", "manual"), file_path, content, "")
            except OSError:
                pass
