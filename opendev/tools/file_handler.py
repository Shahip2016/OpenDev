"""
File operations handler (Section 2.4.2).

Five file tools:
  - read_file:  line-numbered output, binary detection, head-tail truncation
  - write_file: create new files only (rejects existing)
  - edit_file:  9-pass fuzzy matching chain-of-responsibility
  - list_files: glob search with .gitignore-aware filtering
  - search:     dual-mode — text (regex) + ast (structural patterns)

FileTimeTracker maintains last-read timestamps for stale-read detection.
"""

from __future__ import annotations

import fnmatch
import os
import re
import time
from pathlib import Path
from typing import Any, Optional

from opendev.models import ToolResult
from opendev.tools.base_handler import BaseHandler
from opendev.tools.edit_replacers import fuzzy_find


# ---------------------------------------------------------------------------
# File time tracker (stale-read detection)
# ---------------------------------------------------------------------------

class FileTimeTracker:
    """
    Tracks when each file was last read by the agent.

    Used by edit_file to detect stale reads — the agent must re-read
    a file before editing it if the file has been modified since the
    last read. This prevents overwriting concurrent edits.
    """

    def __init__(self):
        self._read_times: dict[str, float] = {}

    def record_read(self, path: str) -> None:
        self._read_times[os.path.abspath(path)] = time.time()

    def get_read_time(self, path: str) -> Optional[float]:
        return self._read_times.get(os.path.abspath(path))

    def is_stale(self, path: str) -> bool:
        """Check if file was modified after last agent read."""
        abs_path = os.path.abspath(path)
        read_time = self._read_times.get(abs_path)
        if read_time is None:
            return True  # Never read = stale
        try:
            mtime = os.path.getmtime(abs_path)
            return mtime > read_time
        except OSError:
            return True


# ---------------------------------------------------------------------------
# File handler
# ---------------------------------------------------------------------------

class FileHandler(BaseHandler):
    """Handler for file operation tools."""

    # Binary file extensions
    BINARY_EXTENSIONS = frozenset([
        ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svg",
        ".pdf", ".zip", ".tar", ".gz", ".7z", ".rar",
        ".exe", ".dll", ".so", ".dylib", ".bin",
        ".mp3", ".mp4", ".wav", ".avi", ".mkv",
        ".woff", ".woff2", ".ttf", ".eot",
        ".pyc", ".pyo", ".class",
    ])

    # Default gitignore patterns
    DEFAULT_IGNORE = [
        "__pycache__", "node_modules", ".git", ".venv", "venv",
        "dist", "build", ".eggs", "*.egg-info",
    ]

    def __init__(self, working_dir: str = "."):
        super().__init__(working_dir)
        self.file_tracker = FileTimeTracker()

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {"name": "read_file", "handler": self.read_file, "schema": {}},
            {"name": "write_file", "handler": self.write_file, "schema": {}},
            {"name": "edit_file", "handler": self.edit_file, "schema": {}},
            {"name": "list_files", "handler": self.list_files, "schema": {}},
            {"name": "search", "handler": self.search, "schema": {}},
        ]

    # -- read_file ----------------------------------------------------------

    def read_file(self, args: dict[str, Any], **kwargs: Any) -> ToolResult:
        """
        Read file with line numbers. Handles binary detection,
        offset/max_lines pagination, and head-tail truncation for
        large outputs (>30k chars).
        """
        file_path = args.get("file_path", "")
        offset = args.get("offset", 1)
        max_lines = args.get("max_lines", 2000)

        abs_path = self._resolve_path(file_path)

        if not os.path.isfile(abs_path):
            return ToolResult(
                tool_call_id="", name="read_file",
                content=f"Error: File not found: {file_path}",
                is_error=True,
            )

        # Binary detection
        ext = Path(abs_path).suffix.lower()
        if ext in self.BINARY_EXTENSIONS:
            size = os.path.getsize(abs_path)
            return ToolResult(
                tool_call_id="", name="read_file",
                content=f"Binary file: {file_path} ({size} bytes, type: {ext})",
            )

        try:
            with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                all_lines = f.readlines()
        except OSError as e:
            return ToolResult(
                tool_call_id="", name="read_file",
                content=f"Error reading file: {e}",
                is_error=True,
            )

        # Track read time for stale detection
        self.file_tracker.record_read(abs_path)

        total = len(all_lines)
        start = max(0, offset - 1)
        end = min(total, start + max_lines)
        selected = all_lines[start:end]

        # Format with line numbers
        numbered = []
        for i, line in enumerate(selected, start=start + 1):
            numbered.append(f"{i:>6} | {line.rstrip()}")

        output = "\n".join(numbered)
        header = f"File: {file_path} ({total} lines total, showing {start + 1}-{end})"

        # Head-tail truncation for large outputs
        if len(output) > 30000:
            head = output[:10000]
            tail = output[-10000:]
            output = f"{head}\n\n... [truncated {len(output) - 20000} chars] ...\n\n{tail}"

        return ToolResult(
            tool_call_id="", name="read_file",
            content=f"{header}\n\n{output}",
            summary=f"Read {file_path}: {end - start} lines from line {start + 1}",
        )

    # -- write_file ---------------------------------------------------------

    def write_file(self, args: dict[str, Any], **kwargs: Any) -> ToolResult:
        """Create a new file. Rejects overwrites of existing files."""
        file_path = args.get("file_path", "")
        content = args.get("content", "")
        create_dirs = args.get("create_dirs", True)

        abs_path = self._resolve_path(file_path)

        if os.path.exists(abs_path):
            return ToolResult(
                tool_call_id="", name="write_file",
                content=f"Error: File already exists: {file_path}. Use edit_file to modify.",
                is_error=True,
            )

        try:
            if create_dirs:
                os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            with open(abs_path, "w", encoding="utf-8") as f:
                f.write(content)
        except OSError as e:
            return ToolResult(
                tool_call_id="", name="write_file",
                content=f"Error writing file: {e}",
                is_error=True,
            )

        lines = content.count("\n") + 1
        return ToolResult(
            tool_call_id="", name="write_file",
            content=f"Created file: {file_path} ({lines} lines)",
            summary=f"Created {file_path}",
        )

    # -- edit_file ----------------------------------------------------------

    def edit_file(self, args: dict[str, Any], **kwargs: Any) -> ToolResult:
        """
        Edit file using 9-pass fuzzy matching chain (Appendix D).

        1. Check stale read (file modified since last agent read)
        2. Run fuzzy_find() to locate the actual target substring
        3. Replace and write back
        """
        file_path = args.get("file_path", "")
        old_content = args.get("old_content", "")
        new_content = args.get("new_content", "")

        abs_path = self._resolve_path(file_path)

        if not os.path.isfile(abs_path):
            return ToolResult(
                tool_call_id="", name="edit_file",
                content=f"Error: File not found: {file_path}",
                is_error=True,
            )

        # Stale read check
        if self.file_tracker.is_stale(abs_path):
            return ToolResult(
                tool_call_id="", name="edit_file",
                content=(
                    f"Error: Stale read — {file_path} has been modified since "
                    f"your last read. Re-read the file and retry with current content."
                ),
                is_error=True,
            )

        try:
            with open(abs_path, "r", encoding="utf-8") as f:
                file_content = f.read()
        except OSError as e:
            return ToolResult(
                tool_call_id="", name="edit_file",
                content=f"Error reading file: {e}",
                is_error=True,
            )

        # 9-pass fuzzy matching chain
        actual_match = fuzzy_find(file_content, old_content)
        if actual_match is None:
            return ToolResult(
                tool_call_id="", name="edit_file",
                content=(
                    f"Error: Content not found in {file_path}. "
                    f"Re-read the file and retry with the exact current content."
                ),
                is_error=True,
            )

        # Replace (using actual matched content, not search query)
        new_file = file_content.replace(actual_match, new_content, 1)

        try:
            with open(abs_path, "w", encoding="utf-8") as f:
                f.write(new_file)
        except OSError as e:
            return ToolResult(
                tool_call_id="", name="edit_file",
                content=f"Error writing file: {e}",
                is_error=True,
            )

        self.file_tracker.record_read(abs_path)
        return ToolResult(
            tool_call_id="", name="edit_file",
            content=f"Successfully edited {file_path}",
            summary=f"Edited {file_path}",
        )

    # -- list_files ---------------------------------------------------------

    def list_files(self, args: dict[str, Any], **kwargs: Any) -> ToolResult:
        """List directory contents with .gitignore-aware filtering."""
        path = args.get("path", ".")
        pattern = args.get("pattern", "*")
        max_results = args.get("max_results", 100)

        abs_path = self._resolve_path(path)

        if not os.path.isdir(abs_path):
            return ToolResult(
                tool_call_id="", name="list_files",
                content=f"Error: Directory not found: {path}",
                is_error=True,
            )

        results = []
        for root, dirs, files in os.walk(abs_path):
            # Filter ignored directories
            dirs[:] = [
                d for d in dirs
                if d not in self.DEFAULT_IGNORE and not d.startswith(".")
            ]

            rel_root = os.path.relpath(root, abs_path)
            for name in sorted(files):
                if fnmatch.fnmatch(name, pattern):
                    rel_path = os.path.join(rel_root, name) if rel_root != "." else name
                    size = os.path.getsize(os.path.join(root, name))
                    results.append(f"  {rel_path} ({size} bytes)")

                    if len(results) >= max_results:
                        break
            if len(results) >= max_results:
                break

        total = len(results)
        output = "\n".join(results) if results else "(empty)"
        return ToolResult(
            tool_call_id="", name="list_files",
            content=f"Directory: {path} ({total} files)\n\n{output}",
            summary=f"Listed {total} files in {path}",
        )

    # -- search -------------------------------------------------------------

    def search(self, args: dict[str, Any], **kwargs: Any) -> ToolResult:
        """
        Dual-mode search: text (regex) or ast (structural patterns).

        Text mode uses Python regex. AST mode is a placeholder for
        tree-sitter/ast-grep integration.
        """
        search_pattern = args.get("pattern", "")
        path = args.get("path", ".")
        mode = args.get("type", "text")

        abs_path = self._resolve_path(path)

        if mode == "ast":
            return ToolResult(
                tool_call_id="", name="search",
                content="AST search requires tree-sitter integration (not yet configured).",
            )

        # Text search using regex
        results = []
        try:
            compiled = re.compile(search_pattern, re.IGNORECASE)
        except re.error as e:
            return ToolResult(
                tool_call_id="", name="search",
                content=f"Invalid regex pattern: {e}",
                is_error=True,
            )

        for root, dirs, files in os.walk(abs_path):
            dirs[:] = [d for d in dirs if d not in self.DEFAULT_IGNORE]

            for name in files:
                filepath = os.path.join(root, name)
                ext = Path(name).suffix.lower()
                if ext in self.BINARY_EXTENSIONS:
                    continue

                try:
                    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                        for i, line in enumerate(f, 1):
                            if compiled.search(line):
                                rel = os.path.relpath(filepath, abs_path)
                                results.append(f"  {rel}:{i}: {line.rstrip()[:200]}")
                                if len(results) >= 100:
                                    break
                except OSError:
                    continue

                if len(results) >= 100:
                    break

        total = len(results)
        output = "\n".join(results) if results else "No matches found."
        return ToolResult(
            tool_call_id="", name="search",
            content=f"Search: '{search_pattern}' in {path} ({total} matches)\n\n{output}",
            summary=f"Found {total} matches for '{search_pattern}'",
        )

    # -- helpers ------------------------------------------------------------

    def _resolve_path(self, path: str) -> str:
        """Resolve a relative path against the working directory."""
        if os.path.isabs(path):
            return path
        return os.path.join(self._working_dir, path)
