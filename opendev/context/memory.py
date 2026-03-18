"""
Agentic Context Engineering (ACE) long-term memory (Section 2.5.5).

Trans-session persistence of learned behaviors via flat markdown bullets.
Includes Reflector and Curator for automated experience-driven learning.
"""

from __future__ import annotations

import os
import logging
from typing import Any, List

from opendev.models import ToolCall, ToolResult

logger = logging.getLogger(__name__)


class MemoryManager:
    """
    Manages the ACE playbook file (playbook.md).
    """

    def __init__(self, project_dir: str = ".opendev"):
        self.playbook_path = os.path.join(project_dir, "playbook.md")
        self.reflector = Reflector()
        self.curator = Curator(self.playbook_path)

    def load_playbook(self) -> str:
        """Load the project playbook to inject into system prompt."""
        if not os.path.exists(self.playbook_path):
            return ""

        try:
            with open(self.playbook_path, "r", encoding="utf-8") as f:
                return f.read()
        except OSError:
            return ""

    def append_learning(self, rule: str) -> None:
        """Append a newly abstracted rule to the playbook."""
        self.curator.add_rule(rule)

    def reflect_and_curate(self, tool_calls: List[ToolCall], results: List[ToolResult], agent: Any) -> None:
        """
        Analyze tool outcomes and update the playbook with new lessons.
        (Section 2.3.6: Multi-stage reflection pipeline)
        """
        new_lessons = self.reflector.reflect(tool_calls, results, agent)
        for lesson in new_lessons:
            self.curator.add_rule(lesson)


class Reflector:
    """
    Analyzes tool results to extract strategic lessons.
    """

    def reflect(self, tool_calls: List[ToolCall], results: List[ToolResult], agent: Any) -> List[str]:
        """
        Heuristic-based reflection (placeholder for LLM-based reflection).
        In a full implementation, this uses a separate LLM call to categorize
        successful strategies or recurring failures.
        """
        lessons = []
        for tc, res in zip(tool_calls, results):
            if res.is_error:
                # Example heuristic: recurring path errors
                if "File not found" in res.content and "/" in tc.arguments.get("file_path", ""):
                    lessons.append(f"Always verify file paths with list_files before using {tc.name}.")
            else:
                # Example heuristic: successful complex edit
                if tc.name == "edit_file" and len(tc.arguments.get("old_content", "")) > 100:
                    lessons.append(f"Fuzzy matching works best for large edits in {tc.arguments.get('file_path')}.")
        
        # Deduplicate locally
        return list(set(lessons))


class Curator:
    """
    Manages and deduplicates the playbook.md.
    """

    def __init__(self, playbook_path: str):
        self.playbook_path = playbook_path

    def add_rule(self, rule: str) -> None:
        """Add a rule if it doesn't already exist (simple string matching)."""
        existing = self._get_existing_rules()
        if rule.strip("- ") not in [r.strip("- ") for r in existing]:
            os.makedirs(os.path.dirname(self.playbook_path), exist_ok=True)
            try:
                with open(self.playbook_path, "a", encoding="utf-8") as f:
                    f.write(f"\n- {rule}\n")
            except OSError:
                pass

    def _get_existing_rules(self) -> List[str]:
        if not os.path.exists(self.playbook_path):
            return []
        try:
            with open(self.playbook_path, "r", encoding="utf-8") as f:
                return [line.strip() for line in f if line.strip().startswith("-")]
        except OSError:
            return []
