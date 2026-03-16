"""
Agentic Context Engineering (ACE) long-term memory (Section 2.5.5).

Trans-session persistence of learned behaviors via flat markdown bullets.
"""

from __future__ import annotations

import os


class MemoryManager:
    """
    Manages the ACE playbook file (memories.md).
    """

    def __init__(self, project_dir: str = ".opendev"):
        self.playbook_path = os.path.join(project_dir, "playbook.md")

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
        os.makedirs(os.path.dirname(self.playbook_path), exist_ok=True)
        try:
            with open(self.playbook_path, "a", encoding="utf-8") as f:
                f.write(f"\n- {rule}\n")
        except OSError:
            pass
