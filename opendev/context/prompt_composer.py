"""
Modular prompt composition pipeline (Section 2.3.1, Appendix C).

Four-stage filter -> sort -> load -> join pipeline.
Supports two-part composition for Anthropic prompt caching, separating
stable (cacheable) rules from dynamic (volatile) state.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable

from opendev.config import AppConfig


@dataclass
class PromptSection:
    id: str
    priority: int
    condition: Callable[[dict[str, Any]], bool]
    cacheable: bool
    content: str


class PromptComposer:
    """
    Composes system prompts from priority-ordered modular sections.
    """

    def __init__(self, config: AppConfig):
        self._config = config
        self._sections: list[PromptSection] = []

    def register(self, section: PromptSection) -> None:
        """Register a prompt section."""
        self._sections.append(section)

    def compose(self, context: dict[str, Any]) -> str:
        """Standard compilation (all sections combined)."""
        active = [s for s in self._sections if s.condition(context)]
        active.sort(key=lambda s: s.priority)
        return "\n\n".join(s.content for s in active)

    def compose_two_part(self, context: dict[str, Any]) -> tuple[str, str]:
        """
        Two-part compilation for prompt caching.
        Returns (stable_content, dynamic_content).
        """
        active = [s for s in self._sections if s.condition(context)]
        active.sort(key=lambda s: s.priority)

        stable = [s.content for s in active if s.cacheable]
        dynamic = [s.content for s in active if not s.cacheable]

        return "\n\n".join(stable), "\n\n".join(dynamic)


def create_default_composer(config: AppConfig) -> PromptComposer:
    """Factory for standard action-mode agent composer."""
    composer = PromptComposer(config)

    # Core identity (Priority 10)
    composer.register(PromptSection(
        id="core",
        priority=10,
        condition=lambda c: True,
        cacheable=True,
        content=(
            "You are OpenDev, an autonomous software engineering agent.\n"
            "You operate in a continuous ReAct loop. Your goal is to solve "
            "the user's task using available tools."
        )
    ))

    # Safety rules (Priority 20)
    composer.register(PromptSection(
        id="safety",
        priority=20,
        condition=lambda c: True,
        cacheable=True,
        content=(
            "## Safety Guidelines\n"
            "1. Read Before Edit: Always read a file before editing it to "
            "prevent overwriting concurrent changes.\n"
            "2. Destructive Commands: Ask for approval before running `rm -rf` "
            "or dropping databases."
        )
    ))

    # Dynamic state — Scratchpad (Priority 90)
    composer.register(PromptSection(
        id="scratchpad",
        priority=90,
        condition=lambda c: bool(c.get("scratchpad")),
        cacheable=False,  # Volatile!
        content="## Current Working State\n{scratchpad}"
    ))

    return composer
