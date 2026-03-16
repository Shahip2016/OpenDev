"""
Edit tool fuzzy matching chain (Section 2.4.2, Appendix D).

Nine replacer classes in chain-of-responsibility pattern.
Each addresses a specific mismatch category. The chain short-circuits
on first match and returns the ACTUAL substring found in the file
(preserving original formatting).

Order:
  1. Simple         — exact string match (baseline)
  2. LineTrimmed    — strip trailing whitespace per line
  3. BlockAnchor    — first/last line anchors + SequenceMatcher (0.3 threshold)
  4. WhitespaceNorm — collapse all whitespace runs to single spaces
  5. IndentFlex     — ignore leading whitespace, skip blanks
  6. EscapeNorm     — unescape common sequences (\\n, \\t, \\\\)
  7. TrimmedBound   — trimmed content expanded to full line boundaries
  8. ContextAware   — first/last non-empty anchors + 0.5 threshold
  9. MultiOccurrence — trimmed line-by-line exact match (last resort)
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from difflib import SequenceMatcher
from typing import Optional


class BaseReplacer(ABC):
    """Abstract base for replacer chain links."""

    @abstractmethod
    def find(self, file_content: str, search: str) -> Optional[str]:
        """
        Search for `search` in `file_content`.

        Returns the ACTUAL substring found in the file (not the search query),
        preserving the file's original formatting. Returns None if no match.
        """
        ...


class SimpleReplacer(BaseReplacer):
    """Pass 1: Exact string match (baseline, zero overhead)."""

    def find(self, file_content: str, search: str) -> Optional[str]:
        if search in file_content:
            return search
        return None


class LineTrimmedReplacer(BaseReplacer):
    """Pass 2: Strip trailing whitespace per line before comparing."""

    def find(self, file_content: str, search: str) -> Optional[str]:
        search_trimmed = "\n".join(
            line.rstrip() for line in search.split("\n")
        )
        file_lines = file_content.split("\n")

        for i in range(len(file_lines)):
            chunk_lines = file_lines[i:i + search_trimmed.count("\n") + 1]
            chunk_trimmed = "\n".join(line.rstrip() for line in chunk_lines)
            if chunk_trimmed == search_trimmed:
                return "\n".join(chunk_lines)
        return None


class BlockAnchorReplacer(BaseReplacer):
    """
    Pass 3: Use first and last lines as anchors, score middle via
    SequenceMatcher with a 0.3 similarity threshold.
    """

    THRESHOLD = 0.3

    def find(self, file_content: str, search: str) -> Optional[str]:
        search_lines = search.strip().split("\n")
        if len(search_lines) < 2:
            return None

        first = search_lines[0].strip()
        last = search_lines[-1].strip()
        file_lines = file_content.split("\n")
        expected_len = len(search_lines)

        candidates = []
        for i, line in enumerate(file_lines):
            if line.strip() == first:
                end = i + expected_len
                if end <= len(file_lines) and file_lines[end - 1].strip() == last:
                    candidate = "\n".join(file_lines[i:end])
                    ratio = SequenceMatcher(None, search, candidate).ratio()
                    if ratio >= self.THRESHOLD:
                        candidates.append((ratio, candidate))

        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            return candidates[0][1]
        return None


class WhitespaceNormalizedReplacer(BaseReplacer):
    """Pass 4: Collapse all whitespace runs to single spaces."""

    def find(self, file_content: str, search: str) -> Optional[str]:
        search_norm = re.sub(r"\s+", " ", search.strip())
        file_lines = file_content.split("\n")

        for i in range(len(file_lines)):
            for j in range(i + 1, min(i + len(search.split("\n")) + 5, len(file_lines) + 1)):
                chunk = "\n".join(file_lines[i:j])
                chunk_norm = re.sub(r"\s+", " ", chunk.strip())
                if chunk_norm == search_norm:
                    return chunk
        return None


class IndentationFlexibleReplacer(BaseReplacer):
    """Pass 5: Ignore leading whitespace, skip blank lines."""

    def find(self, file_content: str, search: str) -> Optional[str]:
        search_stripped = [
            line.lstrip() for line in search.split("\n") if line.strip()
        ]
        if not search_stripped:
            return None

        file_lines = file_content.split("\n")
        file_stripped = [(i, line.lstrip()) for i, line in enumerate(file_lines) if line.strip()]

        for start_idx in range(len(file_stripped)):
            if file_stripped[start_idx][1] == search_stripped[0]:
                end_idx = start_idx + len(search_stripped)
                if end_idx <= len(file_stripped):
                    candidate_stripped = [fs[1] for fs in file_stripped[start_idx:end_idx]]
                    if candidate_stripped == search_stripped:
                        first_line = file_stripped[start_idx][0]
                        last_line = file_stripped[end_idx - 1][0]
                        return "\n".join(file_lines[first_line:last_line + 1])
        return None


class EscapeNormalizedReplacer(BaseReplacer):
    """Pass 6: Unescape common sequences (\\n, \\t, \\\\)."""

    def find(self, file_content: str, search: str) -> Optional[str]:
        unescaped = (
            search.replace("\\n", "\n")
            .replace("\\t", "\t")
            .replace("\\\\", "\\")
        )
        if unescaped != search and unescaped in file_content:
            return unescaped
        return None


class TrimmedBoundaryReplacer(BaseReplacer):
    """Pass 7: Try trimmed content; expand to full line boundaries."""

    def find(self, file_content: str, search: str) -> Optional[str]:
        trimmed = search.strip()
        if not trimmed:
            return None

        idx = file_content.find(trimmed)
        if idx < 0:
            return None

        # Expand to full line boundaries
        start = file_content.rfind("\n", 0, idx)
        start = start + 1 if start >= 0 else 0
        end = file_content.find("\n", idx + len(trimmed))
        end = end if end >= 0 else len(file_content)

        return file_content[start:end]


class ContextAwareReplacer(BaseReplacer):
    """
    Pass 8: Use first and last non-empty lines as anchors,
    score all candidate regions with a 0.5 similarity threshold.
    """

    THRESHOLD = 0.5

    def find(self, file_content: str, search: str) -> Optional[str]:
        search_nonempty = [l for l in search.split("\n") if l.strip()]
        if len(search_nonempty) < 2:
            return None

        first = search_nonempty[0].strip()
        last = search_nonempty[-1].strip()
        file_lines = file_content.split("\n")

        candidates = []
        for i, line in enumerate(file_lines):
            if line.strip() == first:
                search_range = len(search.split("\n")) + 3
                for j in range(i + 1, min(i + search_range, len(file_lines))):
                    if file_lines[j].strip() == last:
                        candidate = "\n".join(file_lines[i:j + 1])
                        ratio = SequenceMatcher(None, search, candidate).ratio()
                        if ratio >= self.THRESHOLD:
                            candidates.append((ratio, candidate))

        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            return candidates[0][1]
        return None


class MultiOccurrenceReplacer(BaseReplacer):
    """Pass 9: Trimmed line-by-line exact match (last resort)."""

    def find(self, file_content: str, search: str) -> Optional[str]:
        search_lines = [line.strip() for line in search.split("\n") if line.strip()]
        if not search_lines:
            return None

        file_lines = file_content.split("\n")

        for i in range(len(file_lines)):
            file_stripped = [
                file_lines[k].strip()
                for k in range(i, min(i + len(search_lines) + 5, len(file_lines)))
                if file_lines[k].strip()
            ][:len(search_lines)]

            if file_stripped == search_lines:
                # Find actual line range
                count = 0
                end = i
                for k in range(i, len(file_lines)):
                    if file_lines[k].strip():
                        count += 1
                        if count == len(search_lines):
                            end = k
                            break
                return "\n".join(file_lines[i:end + 1])
        return None


# ---------------------------------------------------------------------------
# Chain assembly
# ---------------------------------------------------------------------------

def build_replacer_chain() -> list[BaseReplacer]:
    """Build the 9-pass fuzzy matching chain in priority order."""
    return [
        SimpleReplacer(),
        LineTrimmedReplacer(),
        BlockAnchorReplacer(),
        WhitespaceNormalizedReplacer(),
        IndentationFlexibleReplacer(),
        EscapeNormalizedReplacer(),
        TrimmedBoundaryReplacer(),
        ContextAwareReplacer(),
        MultiOccurrenceReplacer(),
    ]


def fuzzy_find(file_content: str, search: str) -> Optional[str]:
    """
    Run the 9-pass fuzzy matching chain.

    Short-circuits on first match. Returns the ACTUAL substring
    found in the file (preserving original formatting).
    """
    for replacer in build_replacer_chain():
        result = replacer.find(file_content, search)
        if result is not None:
            return result
    return None
