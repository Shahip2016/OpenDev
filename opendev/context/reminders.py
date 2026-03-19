"""
Event-driven system reminders (Section 2.3.4, Appendix F).

Injects contextual nudges into the conversation history right before
the next LLM action call, countering instruction fade-out.
"""

from __future__ import annotations

from typing import Any, Dict, List

from opendev.models import ConversationHistory, Role


class ReminderSystem:
    """
    Analyzes recent history and agent state to inject targeted nudges.
    """

    def check_and_inject(
        self,
        history: ConversationHistory,
        state: Dict[str, Any]
    ) -> None:
        """Analyze state and inject reminder if conditions met."""
        messages = history.messages
        if not messages:
            return

        # Condition 1: Tool failure loop
        if self._detect_tool_failures(messages):
            if state.get("tool_failure_nudge_count", 0) < 3:
                history.add_user(
                    "[SYSTEM REMINDER] You have had multiple tool failures "
                    "in a row. Please analyze the errors and try a fundamentally "
                    "different approach rather than simply retrying."
                )
                state["tool_failure_nudge_count"] = state.get("tool_failure_nudge_count", 0) + 1
                return

        # Condition 2: Deep directory exploration without writing
        if self._detect_exploration_spiral(messages):
            if not state.get("exploration_nudge_sent"):
                history.add_user(
                    "[SYSTEM REMINDER] You have been exploring for a while "
                    "without taking concrete actions. If you have enough "
                    "context, specify your plan and start implementing."
                )
                state["exploration_nudge_sent"] = True
                return

    def _detect_tool_failures(self, messages: List) -> bool:
        """Look for 3 consecutive tool failures."""
        tool_results = [m for m in messages[-6:] if m.role == Role.TOOL]
        if len(tool_results) < 3:
            return False
        return all("Error" in (m.content or "") for m in tool_results[-3:])

    def _detect_exploration_spiral(self, messages: List) -> bool:
        """Look for 5+ sequential read_file or list_files calls."""
        tools_called = []
        for m in messages[-10:]:
            if m.role == Role.ASSISTANT and hasattr(m, "tool_calls"):
                for tc in m.tool_calls:
                    tools_called.append(tc.name)

        if len(tools_called) < 5:
            return False

        reads = sum(1 for t in tools_called[-5:] if t in ("read_file", "list_files", "search"))
        return reads == 5
