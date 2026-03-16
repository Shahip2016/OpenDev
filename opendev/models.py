"""
Core data models for OpenDev.

Defines the message, tool-call, and conversation structures that flow
through the agent pipeline.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from collections import deque
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Message roles
# ---------------------------------------------------------------------------

class Role(str, Enum):
    """Message role in the conversation."""
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


# ---------------------------------------------------------------------------
# Tool-related models
# ---------------------------------------------------------------------------

class ToolCall(BaseModel):
    """A single tool invocation requested by the LLM."""
    id: str = Field(default_factory=lambda: f"call_{uuid.uuid4().hex[:12]}")
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)

    @property
    def fingerprint(self) -> str:
        """MD5 hash of (name, args) for doom-loop detection (Section 2.2.6)."""
        raw = f"{self.name}:{sorted(self.arguments.items())}"
        return hashlib.md5(raw.encode()).hexdigest()


class ToolResult(BaseModel):
    """Result from executing a tool call."""
    tool_call_id: str
    name: str
    content: str
    is_error: bool = False
    summary: Optional[str] = None  # Compact summary for context optimization


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------

class Message(BaseModel):
    """A single message in the conversation."""
    role: Role
    content: Optional[str] = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_call_id: Optional[str] = None  # For role=tool messages
    name: Optional[str] = None
    timestamp: float = Field(default_factory=time.time)
    token_count: Optional[int] = None  # API-reported token count

    def to_api_format(self) -> dict[str, Any]:
        """Convert to OpenAI-compatible message format."""
        msg: dict[str, Any] = {"role": self.role.value}

        if self.content is not None:
            msg["content"] = self.content

        if self.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments)
                        if isinstance(tc.arguments, dict) else tc.arguments,
                    },
                }
                for tc in self.tool_calls
            ]

        if self.tool_call_id is not None:
            msg["tool_call_id"] = self.tool_call_id

        if self.name is not None:
            msg["name"] = self.name

        return msg


# ---------------------------------------------------------------------------
# Conversation history
# ---------------------------------------------------------------------------

class ConversationHistory:
    """
    Thread-safe conversation history with validated message alternation.

    Enforces structural integrity: every assistant message with tool calls
    must be followed by matching tool results before the next user turn.
    """

    def __init__(self) -> None:
        self._messages: list[Message] = []

    def add(self, message: Message) -> None:
        """Add a message to the history."""
        self._messages.append(message)

    def add_user(self, content: str) -> None:
        self.add(Message(role=Role.USER, content=content))

    def add_assistant(
        self,
        content: Optional[str] = None,
        tool_calls: Optional[list[ToolCall]] = None,
    ) -> None:
        self.add(Message(
            role=Role.ASSISTANT,
            content=content,
            tool_calls=tool_calls or [],
        ))

    def add_tool_result(self, result: ToolResult) -> None:
        self.add(Message(
            role=Role.TOOL,
            content=result.content,
            tool_call_id=result.tool_call_id,
            name=result.name,
        ))

    def add_system(self, content: str) -> None:
        self.add(Message(role=Role.SYSTEM, content=content))

    @property
    def messages(self) -> list[Message]:
        return list(self._messages)

    @property
    def last_n(self) -> int:
        return len(self._messages)

    def get_recent(self, n: int) -> list[Message]:
        """Get the last n messages."""
        return self._messages[-n:]

    def to_api_format(self) -> list[dict[str, Any]]:
        """Convert entire history to OpenAI-compatible format."""
        return [m.to_api_format() for m in self._messages]

    def clear(self) -> None:
        self._messages.clear()

    def replace_message(self, index: int, new_message: Message) -> None:
        """Replace a message at the given index (used by compaction)."""
        if 0 <= index < len(self._messages):
            self._messages[index] = new_message

    def serialize(self) -> list[dict[str, Any]]:
        """Serialize all messages for persistence."""
        return [m.model_dump() for m in self._messages]

    @classmethod
    def deserialize(cls, data: list[dict[str, Any]]) -> "ConversationHistory":
        """Restore from serialized data."""
        history = cls()
        for item in data:
            history.add(Message(**item))
        return history


# ---------------------------------------------------------------------------
# Iteration context  (Section 2.2.6)
# ---------------------------------------------------------------------------

class IterationContext(BaseModel):
    """
    Per-query state carried through the ReAct loop.

    Tracks iteration counters, one-shot guard flags, doom-loop fingerprints,
    and nudge budgets.
    """
    iteration: int = 0
    max_iterations: int = 100

    # Doom-loop detection  (sliding window of recent fingerprints)
    fingerprints: list[str] = Field(default_factory=list)
    doom_loop_window: int = 20
    doom_loop_threshold: int = 3

    # Nudge budgets  (Section 2.3.4)
    nudge_count: int = 0
    max_nudge_attempts: int = 3
    todo_nudge_count: int = 0
    max_todo_nudges: int = 2

    # One-shot flags
    plan_approved_reminded: bool = False
    all_todos_complete_reminded: bool = False
    completion_summary_reminded: bool = False

    # Cancellation
    cancelled: bool = False

    def add_fingerprint(self, fp: str) -> bool:
        """
        Add a tool-call fingerprint and check for doom-loops.

        Returns True if a doom-loop is detected (fingerprint appears
        >= threshold times in the sliding window).
        """
        self.fingerprints.append(fp)
        # Keep only the last `doom_loop_window` fingerprints
        if len(self.fingerprints) > self.doom_loop_window:
            self.fingerprints = self.fingerprints[-self.doom_loop_window:]

        count = self.fingerprints.count(fp)
        return count >= self.doom_loop_threshold


# ---------------------------------------------------------------------------
# Command result  (Section 2.2.4)
# ---------------------------------------------------------------------------

class CommandResult(BaseModel):
    """Result from a REPL command handler."""
    success: bool
    message: str
    data: Optional[dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Cost tracking  (Section 2.2.3)
# ---------------------------------------------------------------------------

class CostTracker(BaseModel):
    """Cumulative API usage and cost tracking per session."""
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_usd: float = 0.0
    api_calls: int = 0

    def record(
        self,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
    ) -> None:
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.total_cost_usd += cost_usd
        self.api_calls += 1


# ---------------------------------------------------------------------------
# Artifact index  (Section 2.3.6)
# ---------------------------------------------------------------------------

class ArtifactEntry(BaseModel):
    """A single file operation tracked by the compaction artifact index."""
    path: str
    operations: list[str] = Field(default_factory=list)  # read, created, modified, deleted


class ArtifactIndex(BaseModel):
    """
    Registry of all files touched during a session.

    Serialized into the compaction summary so the agent remembers which
    files it has worked with even after context is compressed.
    """
    entries: dict[str, ArtifactEntry] = Field(default_factory=dict)

    def record(self, path: str, operation: str) -> None:
        if path not in self.entries:
            self.entries[path] = ArtifactEntry(path=path)
        if operation not in self.entries[path].operations:
            self.entries[path].operations.append(operation)

    def summary(self) -> str:
        lines = ["Files touched this session:"]
        for path, entry in self.entries.items():
            ops = ", ".join(entry.operations)
            lines.append(f"  {path} [{ops}]")
        return "\n".join(lines)


# Needed for Message.to_api_format
import json  # noqa: E402
