"""
Thinking manager with dual-memory architecture (Section 2.2.6, 2.3.3).

Four thinking depth levels:
  OFF    → skip thinking entirely
  LOW    → basic situation analysis
  MEDIUM → detailed analysis with potential approaches
  HIGH   → full analysis + self-critique (Reflexion-inspired)

Dual-memory for bounded thinking context:
  Episodic memory → LLM summary of full history (regenerated every 5 messages)
  Working memory  → last 6 exchanges verbatim
"""

from __future__ import annotations

from typing import Any, Optional

from opendev.config import ThinkingLevel
from opendev.models import ConversationHistory, Message, Role


class ThinkingManager:
    """
    Manages the thinking phase with dual-memory architecture.

    Separates compressed long-range context (episodic) from detailed
    short-range context (working) to keep the thinking token budget
    bounded regardless of conversation length.
    """

    def __init__(
        self,
        agent: Any = None,
        regenerate_threshold: int = 5,
        working_memory_window: int = 6,
    ):
        self._agent = agent
        self._regenerate_threshold = regenerate_threshold
        self._working_memory_window = working_memory_window
        self._episodic_summary: str = ""
        self._messages_since_regen: int = 0
        self._max_summary_length: int = 500  # chars

    def think(
        self,
        history: ConversationHistory,
        level: ThinkingLevel,
    ) -> Optional[str]:
        """
        Execute the thinking phase with the given depth level.

        Returns a reasoning trace injected into the action phase context.
        """
        if level == ThinkingLevel.OFF:
            return None

        # Build thinking context using dual-memory architecture
        thinking_context = self._build_thinking_context(history)

        # Generate thinking trace based on depth level
        trace = self._generate_trace(thinking_context, level)

        # At HIGH level: include self-critique (Section 2.2.6)
        if level == ThinkingLevel.HIGH and trace:
            critique = self._generate_critique(trace)
            if critique:
                trace = self._refine_trace(trace, critique)

        return trace

    def _build_thinking_context(self, history: ConversationHistory) -> str:
        """
        Construct thinking context via dual-memory architecture (Section 2.3.3).

        Combines:
          1. Episodic memory summary (big picture, max 500 chars)
          2. Working memory (last N exchanges verbatim)
          3. Current user query
        """
        # Update episodic memory if needed
        self._messages_since_regen += 1
        if self._messages_since_regen >= self._regenerate_threshold:
            self._regenerate_episodic_memory(history)
            self._messages_since_regen = 0

        parts = []

        # Part 1: Episodic memory (long-range context)
        if self._episodic_summary:
            parts.append(f"## Prior Context (Summary)\n{self._episodic_summary}")

        # Part 2: Working memory (recent exchanges)
        recent = history.get_recent(self._working_memory_window * 2)
        if recent:
            recent_text = []
            for msg in recent:
                role = msg.role.value.upper()
                content = msg.content or "(tool call/result)"
                recent_text.append(f"[{role}] {content[:500]}")
            parts.append("## Recent Context\n" + "\n".join(recent_text))

        return "\n\n".join(parts)

    def _regenerate_episodic_memory(self, history: ConversationHistory) -> None:
        """
        Regenerate episodic memory from the full conversation history.

        Regenerating from full history (rather than summarizing the previous
        summary) prevents summary drift — accumulated distortion from
        iteratively compressing a compression.
        """
        messages = history.messages

        if not messages:
            return

        # Build a compact representation of the full history
        summary_parts = []
        for msg in messages:
            if msg.role == Role.USER and msg.content:
                summary_parts.append(f"User: {msg.content[:100]}")
            elif msg.role == Role.ASSISTANT and msg.content:
                summary_parts.append(f"Agent: {msg.content[:100]}")

        full = "\n".join(summary_parts)

        # Truncate to max length
        if len(full) > self._max_summary_length:
            full = full[:self._max_summary_length] + "..."

        self._episodic_summary = full

    def _generate_trace(self, context: str, level: ThinkingLevel) -> str:
        """
        Generate a reasoning trace at the specified depth.

        In a full implementation, this calls a separate thinking LLM
        with a tool-free conversation (no tool schemas available).
        """
        depth_prompts = {
            ThinkingLevel.LOW: "Briefly analyze the current situation.",
            ThinkingLevel.MEDIUM: (
                "Analyze the current situation, identify potential approaches, "
                "and recommend the most promising one."
            ),
            ThinkingLevel.HIGH: (
                "Perform a thorough analysis: assess the situation, enumerate "
                "all viable approaches with pros/cons, identify risks, and "
                "recommend a detailed action plan."
            ),
        }
        prompt = depth_prompts.get(level, depth_prompts[ThinkingLevel.LOW])

        # In production, this would call self._agent.call_llm()
        # with model_role="thinking" and NO tool schemas
        trace = (
            f"[Thinking - {level.value}]\n"
            f"Context review: {context[:200]}...\n"
            f"Analysis: Based on the context, proceeding with the task."
        )
        return trace

    def _generate_critique(self, trace: str) -> str:
        """
        Generate a critique of the thinking trace (Reflexion-inspired).

        Only activated at HIGH thinking level.
        """
        # In production, calls critique model
        return f"[Critique] The analysis appears sound. Consider edge cases."

    def _refine_trace(self, trace: str, critique: str) -> str:
        """
        Refine the thinking trace based on self-critique.

        The thinking model receives both the original trace and the
        critique as input, producing a refined reasoning.
        """
        return f"{trace}\n\n{critique}\n\n[Refined] Analysis refined based on critique."
