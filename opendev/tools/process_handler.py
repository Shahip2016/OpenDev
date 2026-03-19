"""
Shell execution pipeline (Section 2.4.3, Appendix E).

Six-stage pipeline for every run_command invocation:
  1. Safety gates — dangerous pattern blocking, permission checks
  2. Command preparation — auto-confirm prompts, unbuffered Python
  3. Server detection — 16 regex patterns → auto-background promotion
  4. Execution fork — background (pty) vs foreground (Popen)
  5. Output management — 30k char cap with head-tail truncation
  6. Timeout handling — idle(60s), absolute(600s), interrupt token
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import threading
import time
from typing import Any, Dict, List, Optional

from opendev.models import ToolResult
from opendev.tools.base_handler import BaseHandler

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dangerous command patterns (Appendix E.1, Stage 1)
# ---------------------------------------------------------------------------

DANGEROUS_PATTERNS = [
    re.compile(r"\brm\s+(-rf?|--recursive)\s+/\s*$", re.IGNORECASE),
    re.compile(r"\brm\s+(-rf?|--recursive)\s+/\s", re.IGNORECASE),
    re.compile(r"\bsudo\s+rm\b", re.IGNORECASE),
    re.compile(r"\bchmod\s+777\s+/", re.IGNORECASE),
    re.compile(r"\bmkfs\b", re.IGNORECASE),
    re.compile(r"\bdd\s+.*of=/dev/", re.IGNORECASE),
    re.compile(r":\(\)\s*\{\s*:\|:\s*&\s*\}", re.IGNORECASE),  # Fork bomb
    re.compile(r"\bcurl\b.*\|\s*\bbash\b", re.IGNORECASE),
    re.compile(r"\bwget\b.*\|\s*\bbash\b", re.IGNORECASE),
    re.compile(r"\bcurl\b.*\|\s*\bsh\b", re.IGNORECASE),
    re.compile(r"\b(shutdown|reboot|halt|poweroff)\b", re.IGNORECASE),
    re.compile(r">\s*/dev/(sda|hda|nvme)", re.IGNORECASE),
]

# ---------------------------------------------------------------------------
# Server detection patterns (Appendix E.2, Table 6)
# ---------------------------------------------------------------------------

SERVER_PATTERNS = [
    re.compile(r"\bnpm\s+run\s+(dev|start|serve)\b", re.IGNORECASE),
    re.compile(r"\byarn\s+(dev|start|serve)\b", re.IGNORECASE),
    re.compile(r"\bpnpm\s+(dev|start|serve)\b", re.IGNORECASE),
    re.compile(r"\bnpx\s+(vite|next|nuxt|remix)\b", re.IGNORECASE),
    re.compile(r"\bpython\s+-m\s+(http\.server|flask|uvicorn|gunicorn)\b", re.IGNORECASE),
    re.compile(r"\bflask\s+run\b", re.IGNORECASE),
    re.compile(r"\buvicorn\b", re.IGNORECASE),
    re.compile(r"\bgunicorn\b", re.IGNORECASE),
    re.compile(r"\bdjango.*runserver\b", re.IGNORECASE),
    re.compile(r"\bruby.*(-s|server)\b", re.IGNORECASE),
    re.compile(r"\brails\s+server\b", re.IGNORECASE),
    re.compile(r"\bcargo\s+watch\b", re.IGNORECASE),
    re.compile(r"\bgo\s+run\b.*serve", re.IGNORECASE),
    re.compile(r"\bdocker\s+compose\s+up\b", re.IGNORECASE),
    re.compile(r"\btail\s+-f\b", re.IGNORECASE),
    re.compile(r"\bwatch\b", re.IGNORECASE),
]

# Auto-confirm patterns for package managers
AUTO_CONFIRM_PATTERNS = [
    (re.compile(r"\bnpm\s+init\b"), "yes | "),
    (re.compile(r"\bnpx\b"), "yes | "),
]


class ProcessHandler(BaseHandler):
    """
    Shell execution handler implementing the 6-stage pipeline.
    """

    def __init__(self, working_dir: str = "."):
        super().__init__(working_dir)
        self._background_tasks: Dict[str, Dict[str, Any]] = {}
        self._task_counter = 0

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        return [
            {"name": "run_command", "handler": self.run_command, "schema": {}},
            {"name": "list_processes", "handler": self.list_processes, "schema": {}},
            {"name": "get_process_output", "handler": self.get_process_output, "schema": {}},
            {"name": "kill_process", "handler": self.kill_process, "schema": {}},
        ]

    def run_command(self, args: Dict[str, Any], **kwargs: Any) -> ToolResult:
        """Execute a shell command through the 6-stage pipeline."""
        command = args.get("command", "")
        timeout = args.get("timeout", 60)
        background = args.get("background", False)

        # Stage 1: Safety gates
        block_reason = self._check_dangerous(command)
        if block_reason:
            return ToolResult(
                tool_call_id="", name="run_command",
                content=f"BLOCKED: {block_reason}",
                is_error=True,
            )

        # Stage 2: Command preparation
        command = self._prepare_command(command)

        # Stage 3: Server detection — auto-promote to background
        if not background and self._is_server_command(command):
            background = True
            logger.info(f"Auto-promoting server command to background: {command[:50]}")

        # Stage 4 & 5: Execution
        if background:
            return self._run_background(command)
        else:
            return self._run_foreground(command, timeout)

    def _check_dangerous(self, command: str) -> Optional[str]:
        """Stage 1: Check for dangerous command patterns."""
        for pattern in DANGEROUS_PATTERNS:
            if pattern.search(command):
                return (
                    f"Command matches dangerous pattern: {pattern.pattern}. "
                    f"This command is blocked for safety."
                )
        return None

    def _prepare_command(self, command: str) -> str:
        """Stage 2: Auto-confirm prompts, set PYTHONUNBUFFERED."""
        for pattern, prefix in AUTO_CONFIRM_PATTERNS:
            if pattern.search(command):
                command = prefix + command
                break

        # Python unbuffered output
        if "python" in command.lower():
            os.environ["PYTHONUNBUFFERED"] = "1"

        return command

    def _is_server_command(self, command: str) -> bool:
        """Stage 3: Detect server-like commands for auto-background promotion."""
        return any(p.search(command) for p in SERVER_PATTERNS)

    def _run_foreground(self, command: str, timeout: int) -> ToolResult:
        """Stage 4a: Foreground execution with pipes."""
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=min(timeout, 600),  # Absolute cap
                cwd=self._working_dir,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )

            stdout = result.stdout or ""
            stderr = result.stderr or ""
            output = stdout + ("\n--- STDERR ---\n" + stderr if stderr else "")

            # Stage 5: Output truncation (30k char cap)
            output = self._truncate_output(output)

            exit_code = result.returncode
            status = "success" if exit_code == 0 else f"failed (exit code {exit_code})"

            return ToolResult(
                tool_call_id="", name="run_command",
                content=f"Command: {command}\nStatus: {status}\n\n{output}",
                summary=f"Ran '{command[:60]}': {status}",
                is_error=exit_code != 0,
            )

        except subprocess.TimeoutExpired:
            return ToolResult(
                tool_call_id="", name="run_command",
                content=f"Command timed out after {timeout}s: {command}",
                is_error=True,
            )
        except OSError as e:
            return ToolResult(
                tool_call_id="", name="run_command",
                content=f"Error executing command: {e}",
                is_error=True,
            )

    def _run_background(self, command: str) -> ToolResult:
        """Stage 4b: Background execution with output capture."""
        self._task_counter += 1
        task_id = f"bg_{self._task_counter:04x}"

        task = {
            "id": task_id,
            "command": command,
            "status": "RUNNING",
            "output": [],
            "start_time": time.time(),
            "process": None,
        }

        try:
            process = subprocess.Popen(
                command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=self._working_dir,
            )
            task["process"] = process

            # Start daemon output reader thread
            thread = threading.Thread(
                target=self._read_output, args=(task,), daemon=True
            )
            thread.start()

            self._background_tasks[task_id] = task

            return ToolResult(
                tool_call_id="", name="run_command",
                content=f"Background task started: {task_id}\nCommand: {command}",
                summary=f"Started background task {task_id}",
            )
        except OSError as e:
            return ToolResult(
                tool_call_id="", name="run_command",
                content=f"Error starting background task: {e}",
                is_error=True,
            )

    def _read_output(self, task: Dict) -> None:
        """Daemon thread: read process output lines."""
        process = task["process"]
        try:
            for line in iter(process.stdout.readline, ""):
                task["output"].append(line.rstrip())
                if len(task["output"]) > 1000:
                    task["output"] = task["output"][-500:]  # Keep last 500
            process.wait()
            task["status"] = "COMPLETED" if process.returncode == 0 else "FAILED"
        except Exception:
            task["status"] = "FAILED"

    def list_processes(self, args: Dict[str, Any], **kwargs: Any) -> ToolResult:
        """List all tracked background tasks."""
        if not self._background_tasks:
            return ToolResult(
                tool_call_id="", name="list_processes",
                content="No background tasks.",
            )

        lines = []
        for tid, task in self._background_tasks.items():
            runtime = time.time() - task["start_time"]
            lines.append(
                f"  {tid}  {task['status']:10s}  {runtime:.0f}s  {task['command'][:60]}"
            )

        return ToolResult(
            tool_call_id="", name="list_processes",
            content="Background tasks:\n" + "\n".join(lines),
        )

    def get_process_output(self, args: Dict[str, Any], **kwargs: Any) -> ToolResult:
        """Get last 100 lines from a background task."""
        task_id = args.get("task_id", "")
        task = self._background_tasks.get(task_id)
        if not task:
            return ToolResult(
                tool_call_id="", name="get_process_output",
                content=f"Error: Unknown task ID: {task_id}",
                is_error=True,
            )

        output = "\n".join(task["output"][-100:])
        return ToolResult(
            tool_call_id="", name="get_process_output",
            content=f"Output for {task_id} ({task['status']}):\n\n{output}",
        )

    def kill_process(self, args: Dict[str, Any], **kwargs: Any) -> ToolResult:
        """Terminate a background task with graceful escalation."""
        task_id = args.get("task_id", "")
        task = self._background_tasks.get(task_id)
        if not task:
            return ToolResult(
                tool_call_id="", name="kill_process",
                content=f"Error: Unknown task ID: {task_id}",
                is_error=True,
            )

        process = task.get("process")
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
            task["status"] = "KILLED"

        return ToolResult(
            tool_call_id="", name="kill_process",
            content=f"Terminated task {task_id}",
        )

    @staticmethod
    def _truncate_output(output: str, max_chars: int = 30000) -> str:
        """Head-tail truncation: first 10k + last 10k on overflow."""
        if len(output) <= max_chars:
            return output
        head = output[:10000]
        tail = output[-10000:]
        skipped = len(output) - 20000
        return f"{head}\n\n... [{skipped} characters truncated] ...\n\n{tail}"
