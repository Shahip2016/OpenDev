"""
Session persistence (Section 2.5.1).

Serializes conversation history to JSON lines (JSONL), allowing
the agent to pause, resume, and fork sessions seamlessly.
Supports workspace recovery across terminal restarts.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

from opendev.config import AppConfig
from opendev.models import ConversationHistory, Message, Role, ToolCall, ToolResult

logger = logging.getLogger(__name__)


class SessionManager:
    """
    Manages loading and saving sessions to disk.
    Sessions are stored as JSONL files in the configured data directory.
    """

    def __init__(self, config: AppConfig):
        self._dir = os.path.join(config.user_config_dir, "sessions")
        os.makedirs(self._dir, exist_ok=True)
        self._current_session_id: Optional[str] = None

    def create_session(self, session_id: str) -> None:
        """Initialize a new empty session."""
        self._current_session_id = session_id
        path = self._get_path(session_id)
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                f.write("")  # Create empty file

    def save_history(self, session_id: str, history: ConversationHistory) -> None:
        """Overwrite the session file with current history."""
        path = self._get_path(session_id)
        try:
            with open(path, "w", encoding="utf-8") as f:
                for msg in history.messages:
                    f.write(json.dumps(self._serialize_msg(msg)) + "\n")
        except OSError as e:
            logger.error(f"Failed to save session {session_id}: {e}")

    def append_message(self, session_id: str, msg: Message) -> None:
        """Append a single message to the session file (fast path)."""
        path = self._get_path(session_id)
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(self._serialize_msg(msg)) + "\n")
        except OSError as e:
            logger.error(f"Failed to append to session {session_id}: {e}")

    def load_session(self, session_id: str) -> Optional[ConversationHistory]:
        """Load history from a JSONL session file."""
        path = self._get_path(session_id)
        if not os.path.exists(path):
            return None

        history = ConversationHistory()
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    data = json.loads(line)
                    history.messages.append(self._deserialize_msg(data))
            self._current_session_id = session_id
            return history
        except (OSError, json.JSONDecodeError) as e:
            logger.error(f"Failed to load session {session_id}: {e}")
            return None

    def list_sessions(self) -> List[str]:
        """Return a list of available session IDs (sorted by modified time)."""
        if not os.path.isdir(self._dir):
            return []

        files = [
            f for f in os.listdir(self._dir)
            if f.endswith(".jsonl") and os.path.isfile(os.path.join(self._dir, f))
        ]

        # Sort by mtime (newest first)
        def get_mtime(f):
            try:
                return os.path.getmtime(os.path.join(self._dir, f))
            except OSError:
                return 0

        files.sort(key=get_mtime, reverse=True)
        return [f[:-6] for f in files]  # Strip .jsonl

    def _get_path(self, session_id: str) -> str:
        """Resolve session ID to file path."""
        safe_id = "".join(c for c in session_id if c.isalnum() or c in "-_")
        return os.path.join(self._dir, f"{safe_id}.jsonl")

    @staticmethod
    def _serialize_msg(msg: Message) -> Dict[str, Any]:
        """Convert Message to dict for JSON serialization."""
        data = {
            "role": msg.role.value,
            "content": msg.content,
        }
        if msg.tool_calls:
            data["tool_calls"] = [
                {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                for tc in msg.tool_calls
            ]
        if msg.tool_result:
            data["tool_result"] = {
                "tool_call_id": msg.tool_result.tool_call_id,
                "name": msg.tool_result.name,
                "content": msg.tool_result.content,
                "is_error": msg.tool_result.is_error,
            }
        return data

    @staticmethod
    def _deserialize_msg(data: Dict[str, Any]) -> Message:
        """Convert dict from JSON into Message object."""
        role = Role(data["role"])

        tool_calls = None
        if "tool_calls" in data:
            tool_calls = [
                ToolCall(id=tc["id"], name=tc["name"], arguments=tc["arguments"])
                for tc in data.get("tool_calls", [])
            ]

        tool_result = None
        if "tool_result" in data:
            tr = data["tool_result"]
            tool_result = ToolResult(
                tool_call_id=tr["tool_call_id"],
                name=tr.get("name", ""),
                content=tr["content"],
                is_error=tr.get("is_error", False)
            )

        return Message(
            role=role,
            content=data.get("content"),
            tool_calls=tool_calls,
            tool_result=tool_result,
        )
