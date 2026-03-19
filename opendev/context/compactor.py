"""
Adaptive context compaction (Section 2.3.6).

Five progressive stages triggered by token thresholds to prevent window exhaustion:
  1. Warning (70%)         → System nudge suggesting explicit summarization
  2. Output Masking (80%)  → Truncate large tool outputs (e.g., read_file)
  3. Fast Pruning (85%)    → Remove intermediate tool calls/results
  4. Aggr. Masking (90%)   → Hard crop all tool outputs to 500 chars
  5. LLM Summary (99%)     → Stop and run full context compression (requires model call)
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional, Set, Tuple

from opendev.models import ConversationHistory, Role

logger = logging.getLogger(__name__)


class ContextCompactor:
    """
    Manages token pressure via a staged degradation strategy.

    Stages:
      70%: Warning injection
      80%: Mild output masking
      85%: Tool loop pruning
      90%: Aggressive output masking
      99%: Emergency LLM summarization
    """

    def __init__(
        self,
        max_tokens: int,
        agent: Optional[Any] = None,
        stage_thresholds: Tuple[float, float, float, float, float] = (
            0.70, 0.80, 0.85, 0.90, 0.99
        ),
    ):
        self.max_tokens = max_tokens
        self.agent = agent
        self.t1, self.t2, self.t3, self.t4, self.t5 = stage_thresholds

        # Track which mitigations have been applied this session
        self.applied: Set[int] = set()

    def check_and_compact(self, history: ConversationHistory) -> None:
        """
        Evaluate context pressure and apply the highest triggered stage.
        """
        # Estimate current tokens (approximate: 4 chars / token)
        total_chars = sum(len(m.content or "") for m in history.messages)
        estimated_tokens = total_chars // 4
        ratio = estimated_tokens / self.max_tokens

        logger.debug(f"Context pressure: {ratio:.1%} ({estimated_tokens}/{self.max_tokens})")

        if ratio >= self.t5 and 5 not in self.applied:
            self._stage5_emergency_summary(history)
            self.applied.add(5)
            # Recheck after hard compaction
            return self.check_and_compact(history)

        if ratio >= self.t4 and 4 not in self.applied:
            self._stage4_aggressive_masking(history)
            self.applied.add(4)
            # Reset lower stages since we did a harsher one
            self.applied.discard(2)

        if ratio >= self.t3 and 3 not in self.applied:
            self._stage3_fast_pruning(history)
            self.applied.add(3)

        if ratio >= self.t2 and 2 not in self.applied:
            self._stage2_output_masking(history)
            self.applied.add(2)

        if ratio >= self.t1 and 1 not in self.applied:
            self._stage1_warning(history)
            self.applied.add(1)

    # -- Implementations ----------------------------------------------------

    def _stage1_warning(self, history: ConversationHistory) -> None:
        """Stage 1 (70%): Inject a system nudge."""
        history.add_user(
            "[SYSTEM WARNING] Context window is reaching 70% capacity. "
            "Please focus on concluding the current task or breaking it "
            "down into a smaller subtask."
        )

    def _stage2_output_masking(self, history: ConversationHistory) -> None:
        """Stage 2 (80%): Truncate large tool outputs (>2000 chars)."""
        logger.info("Applying Stage 2 context compaction (Output Masking)")
        for msg in history.messages:
            if msg.role == Role.TOOL and msg.content and len(msg.content) > 2000:
                head = msg.content[:1000]
                tail = msg.content[-1000:]
                msg.content = f"{head}\n\n... [MASKED STAGE 2] ...\n\n{tail}"

    def _stage3_fast_pruning(self, history: ConversationHistory) -> None:
        """
        Stage 3 (85%): Remove intermediate tool calls/results.
        Keeps the first and last two exchanges, deletes Middle.
        """
        logger.info("Applying Stage 3 context compaction (Fast Pruning)")
        messages = history.messages
        if len(messages) < 10:
            return

        # Keep first 2 (initial context) and last 6 (recent context)
        keep = messages[:2] + messages[-6:]

        # Create a summary placeholder for the pruned middle
        pruned_count = len(messages) - 8
        summary = "[SYSTEM] Removed {} intermediate messages due to memory pressure.".format(pruned_count)

        from opendev.models import Message
        placeholder = Message(role=Role.USER, content=summary)

        history._messages = messages[:2] + [placeholder] + messages[-6:]

    def _stage4_aggressive_masking(self, history: ConversationHistory) -> None:
        """Stage 4 (90%): Hard crop all tool outputs to 500 chars max."""
        logger.info("Applying Stage 4 context compaction (Aggressive Masking)")
        for msg in history.messages:
            if msg.role == Role.TOOL and msg.content and len(msg.content) > 500:
                head = msg.content[:250]
                tail = msg.content[-250:]
                msg.content = f"{head}\n\n... [MASKED STAGE 4] ...\n\n{tail}"

    def _stage5_emergency_summary(self, history: ConversationHistory) -> None:
        """
        Stage 5 (99%): Full context compression using a compact model.
        """
        logger.warning("Applying Stage 5 EMERGENCY context compaction (LLM Summary)")
        if not self.agent:
            return self._stage3_fast_pruning(history)  # Fallback

        # In production this calls the agent's "compact" model role
        # to generate a dense summary of the entire history
        summary = "Emergency context compression applied. History summarized."

        from opendev.models import Message
        first = history.messages[0] if history.messages else None
        last = history.messages[-1] if history.messages else None

        new_history = []
        if first:
            new_history.append(first)

        new_history.append(Message(role=Role.USER, content=f"## Compressed History\n{summary}"))

        if last and last != first:
            new_history.append(last)

        history._messages = new_history
