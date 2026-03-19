"""
Advanced symbol search handler (Section 2.4.7).

Uses Python's ast module to provide high-precision code exploration:
  - find_symbol: Finds definitions of classes, functions, or variables.
  - list_symbols: Lists all symbols defined in a specific file.
"""

from __future__ import annotations

import ast
import os
import re
from typing import Any, Dict, List, Optional

from opendev.models import ToolResult
from opendev.tools.base_handler import BaseHandler


class SymbolSearchHandler(BaseHandler):
    """Handler for AST-based symbol search tools."""

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "find_symbol",
                "handler": self.find_symbol,
                "schema": {
                    "type": "function",
                    "function": {
                        "name": "find_symbol",
                        "description": "Find the definition of a class, function, or variable in the project.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string", "description": "The name of the symbol to find (or regex pattern)."},
                                "path": {"type": "string", "description": "Optional path to restrict search (default: project root)."},
                                "is_regex": {"type": "boolean", "description": "Whether to treat 'name' as a regular expression."},
                            },
                        },
                    },
                },
            },
            {
                "name": "list_symbols",
                "handler": self.list_symbols,
                "schema": {
                    "type": "function",
                    "function": {
                        "name": "list_symbols",
                        "description": "List all symbols (classes, functions, async functions) defined in a file.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "file_path": {"type": "string", "description": "Path to the file to analyze."},
                            },
                        },
                    },
                },
            },
        ]

    def find_symbol(self, args: Dict[str, Any], **kwargs: Any) -> ToolResult:
        """Find definitions of a symbol across the project."""
        name = args.get("name", "")
        path = args.get("path", ".")
        is_regex = args.get("is_regex", False)
        abs_path = self._resolve_path(path)

        if not name:
            return ToolResult(tool_call_id="", name="find_symbol", content="Error: Symbol 'name' is required.", is_error=True)

        try:
            pattern = re.compile(name) if is_regex else None
        except re.error as e:
            return ToolResult(tool_call_id="", name="find_symbol", content=f"Error: Invalid regex pattern: {e}", is_error=True)

        matches = []
        for root, _, files in os.walk(abs_path):
            skip = False
            for part in root.split(os.sep):
                if (part.startswith(".") and part not in [".", ".."]) or part in ["node_modules", "__pycache__", "venv", ".venv"]:
                    skip = True
                    break
            if skip:
                continue

            for filename in files:
                if not filename.endswith(".py"):
                    continue

                filepath = os.path.join(root, filename)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        tree = ast.parse(f.read(), filename=filepath)
                    for node in ast.walk(tree):
                        match = False
                        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                            target_name = node.name
                            if (pattern and pattern.search(target_name)) or (not pattern and target_name == name):
                                match = True
                                label = type(node).__name__
                        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                            target_name = node.id
                            if (pattern and pattern.search(target_name)) or (not pattern and target_name == name):
                                match = True
                                label = "Variable assignment"
                        
                        if match:
                            rel_path = os.path.relpath(filepath, self._working_dir)
                            matches.append(f"  {rel_path}:{node.lineno} ({label})")
                except Exception:
                    continue

        if not matches:
            return ToolResult(tool_call_id="", name="find_symbol", content=f"Symbol '{name}' not found.", summary=f"Symbol '{name}' not found")

        output = f"Matches for symbol '{name}':\n" + "\n".join(matches)
        return ToolResult(tool_call_id="", name="find_symbol", content=output, summary=f"Found {len(matches)} matches for '{name}'")

    def list_symbols(self, args: Dict[str, Any], **kwargs: Any) -> ToolResult:
        """List all symbols defined in a file."""
        file_path = args.get("file_path", "")
        abs_path = self._resolve_path(file_path)

        if not os.path.isfile(abs_path):
            return ToolResult(tool_call_id="", name="list_symbols", content=f"Error: File not found: {file_path}", is_error=True)

        try:
            with open(abs_path, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=abs_path)
            
            symbols = []
            for node in ast.iter_child_nodes(tree):
                if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    symbols.append(f"  L{node.lineno}: {type(node).__name__} '{node.name}'")
                    # Nested symbols
                    for subnode in ast.iter_child_nodes(node):
                        if isinstance(subnode, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            symbols.append(f"    L{subnode.lineno}: {type(subnode).__name__} '{subnode.name}'")

            if not symbols:
                return ToolResult(tool_call_id="", name="list_symbols", content=f"No symbols found in {file_path}.")

            output = f"Symbols in {file_path}:\n" + "\n".join(symbols)
            return ToolResult(tool_call_id="", name="list_symbols", content=output, summary=f"Listed symbols in {file_path}")
        except Exception as e:
            return ToolResult(tool_call_id="", name="list_symbols", content=f"Error analyzing {file_path}: {e}", is_error=True)

    def _resolve_path(self, path: str) -> str:
        if os.path.isabs(path):
            return path
        return os.path.join(self._working_dir, path)
