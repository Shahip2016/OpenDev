"""
Skill loader with two-phase discovery (Section 2.4.8).

Phase 1 (Metadata): At startup, scan skill directories and parse only
  YAML frontmatter to extract names and descriptions. This lightweight
  index is included in the system prompt.

Phase 2 (On-demand): When the agent invokes a skill, load the full
  markdown content and inject into conversation context. Deduplication
  cache ensures each skill loads at most once per session.

Skills from three tiers with strict priority:
  1. Project-local (.opendev/skills/) — highest
  2. User-global (~/.opendev/skills/)
  3. Built-in (opendev/skills/builtin/) — lowest
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class SkillMetadata:
    """Metadata extracted from a skill's YAML frontmatter."""
    name: str
    description: str
    source_path: str
    tier: str  # "builtin", "user", "project"


@dataclass
class LoadedSkill:
    """A fully loaded skill with content."""
    metadata: SkillMetadata
    content: str


class SkillLoader:
    """
    Two-phase skill discovery and loading.

    Discovers skill metadata from three directories at startup,
    then loads full content on demand with deduplication.
    """

    def __init__(
        self,
        builtin_dir: str = "opendev/skills/builtin",
        user_dir: str = "",
        project_dir: str = ".opendev/skills",
    ):
        self._dirs = {
            "builtin": builtin_dir,
            "user": user_dir,
            "project": project_dir,
        }
        self._metadata: Dict[str, SkillMetadata] = {}
        self._loaded_cache: Dict[str, LoadedSkill] = {}

    def discover(self) -> Dict[str, SkillMetadata]:
        """
        Phase 1: Scan all skill directories and parse YAML frontmatter.

        Higher-priority tiers override lower-priority ones when same name.
        """
        # Process in priority order: builtin (lowest) → user → project (highest)
        for tier in ["builtin", "user", "project"]:
            dir_path = self._dirs.get(tier, "")
            if not dir_path or not os.path.isdir(dir_path):
                continue

            for filename in os.listdir(dir_path):
                if not filename.endswith(".md"):
                    continue

                filepath = os.path.join(dir_path, filename)
                metadata = self._parse_frontmatter(filepath, tier)
                if metadata:
                    # Higher-priority tier overwrites lower
                    self._metadata[metadata.name] = metadata

        return self._metadata

    def get_metadata_index(self) -> List[SkillMetadata]:
        """Return all discovered skill metadata for system prompt inclusion."""
        return list(self._metadata.values())

    def get_prompt_index(self) -> str:
        """Format skill index for inclusion in system prompt."""
        if not self._metadata:
            return ""

        lines = ["## Available Skills"]
        for meta in self._metadata.values():
            lines.append(f"- **{meta.name}**: {meta.description}")
        return "\n".join(lines)

    def load_skill(self, name: str) -> Optional[LoadedSkill]:
        """
        Phase 2: Load full skill content on demand.

        Deduplication cache ensures each skill loads at most once per session.
        """
        # Check deduplication cache
        if name in self._loaded_cache:
            return self._loaded_cache[name]

        metadata = self._metadata.get(name)
        if not metadata:
            return None

        try:
            with open(metadata.source_path, "r", encoding="utf-8") as f:
                raw = f.read()

            # Strip YAML frontmatter
            content = self._strip_frontmatter(raw)

            loaded = LoadedSkill(metadata=metadata, content=content)
            self._loaded_cache[name] = loaded
            return loaded
        except (OSError, PermissionError):
            return None

    def _parse_frontmatter(self, filepath: str, tier: str) -> Optional[SkillMetadata]:
        """Extract name and description from YAML frontmatter."""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()

            if not content.startswith("---"):
                return None

            end = content.find("---", 3)
            if end < 0:
                return None

            frontmatter = content[3:end].strip()
            name = ""
            description = ""

            for line in frontmatter.split("\n"):
                line = line.strip()
                if line.startswith("name:"):
                    name = line[5:].strip().strip("'\"")
                elif line.startswith("description:"):
                    description = line[12:].strip().strip("'\"")

            if not name:
                # Derive from filename
                name = Path(filepath).stem

            return SkillMetadata(
                name=name,
                description=description,
                source_path=filepath,
                tier=tier,
            )
        except (OSError, PermissionError):
            return None

    @staticmethod
    def _strip_frontmatter(content: str) -> str:
        """Remove YAML frontmatter from markdown content."""
        if not content.startswith("---"):
            return content
        end = content.find("---", 3)
        if end < 0:
            return content
        return content[end + 3:].strip()
