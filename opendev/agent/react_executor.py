"""
Extended ReAct execution loop (Section 2.2.6, Algorithm 1).

Implements the four-phase iteration cycle:
  Phase 0: Staged context management (compaction)
  Phase 1: Thinking (optional, 4 depth levels, no tools)
  Phase 2: Action (with full tool schemas)
  Phase 3: Decision, dispatch, doom-loop detection

Termination through four paths:
  1. Explicit task_complete tool call
  2. Text response with no tool calls and no error (implicit completion)
  3. Error-recovery nudge budget exhausted (3 attempts)
  4. Iteration count reaches safety limit
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from opendev.config import AppConfig, ThinkingLevel
from opendev.persistence.tool_logger import ToolLogger
from opendev.models import (
    ConversationHistory,
    IterationContext,
    Message,
    Role,
    ToolCall,
    ToolResult,
)

logger = logging.getLogger(__name__)


class ReactExecutor:
    """
    Extended ReAct loop executor as described in Algorithm 1.

    Wraps the core reasoning loop with:
    - Five-stage compaction at Phase 0
    - Optional thinking + self-critique at Phase 1
    - Tool dispatch with doom-loop detection at Phase 3
    - Event-driven system reminders
    """

    def __init__(
        self,
        agent: Any,
        config: AppConfig,
        tool_registry: Any = None,
        compactor: Any = None,
        thinking_manager: Any = None,
        reminder_system: Any = None,
        memory_manager: Any = None,
        tool_logger: Any = None,
        depth: int = 0,
    ):
        self._agent = agent
        self._config = config
        self._tool_registry = tool_registry
        self._compactor = compactor
        self._thinking_manager = thinking_manager
        self._reminder_system = reminder_system
        self._memory_manager = memory_manager
        self._tool_logger = tool_logger
        self._depth = depth

    def execute(
        self,
        query: str,
        history: ConversationHistory,
        deps: Any = None,
    ) -> tuple[str, bool, float]:
        """
        Execute the full ReAct loop for a query.

        Returns: (summary, error_status, latency)
        """
        import time
        start = time.time()

        # Add user message
        history.add_user(query)

        # Create iteration context (Algorithm 1, line 1)
        ctx = IterationContext(
            max_iterations=self._config.max_iterations,
            doom_loop_window=self._config.doom_loop_window,
            doom_loop_threshold=self._config.doom_loop_threshold,
            max_nudge_attempts=self._config.max_nudge_attempts,
            max_todo_nudges=self._config.max_todo_nudges,
        )

        summary = ""
        error = False

        # Algorithm 1: repeat loop (line 2)
        while ctx.iteration < ctx.max_iterations and not ctx.cancelled:
            ctx.iteration += 1
            logger.debug(f"ReAct iteration {ctx.iteration}/{ctx.max_iterations}")

            result = self._run_iteration(ctx, history, deps)

            if result is not None:
                summary = result
                break

        latency = time.time() - start
        return summary, error, latency

    def _run_iteration(
        self,
        ctx: IterationContext,
        history: ConversationHistory,
        deps: Any = None,
    ) -> Optional[str]:
        """
        Execute a single iteration of the ReAct loop.

        Returns the final summary if the loop should terminate, None to continue.
        """
        # ── Phase 0: Staged Context Management (Algorithm 1, lines 3-9) ──
        self._phase0_context_management(history)

        # ── Phase 1: Thinking (Algorithm 1, lines 11-18) ──
        thinking_trace = self._phase1_thinking(ctx, history)

        # ── Phase 2: Action (Algorithm 1, lines 20-21) ──
        response, tool_calls = self._phase2_action(history, thinking_trace)

        # ── Phase 3: Decision (Algorithm 1, lines 21-38) ──
        return self._phase3_decision(ctx, history, response, tool_calls, deps)

    # -- Phase implementations ---------------------------------------------

    def _phase0_context_management(self, history: ConversationHistory) -> None:
        """
        Stage 0: Check context pressure and apply compaction.

        Five progressive stages (Section 2.3.6):
          70% → warning
          80% → observation masking
          85% → fast pruning
          90% → aggressive masking
          99% → full LLM compaction
        """
        if self._compactor:
            self._compactor.check_and_compact(history)

    def _phase1_thinking(
        self,
        ctx: IterationContext,
        history: ConversationHistory,
    ) -> Optional[str]:
        """
        Phase 1: Optional thinking phase (no tools).

        Depth levels:
          OFF    → skip
          LOW    → basic reasoning
          MEDIUM → detailed analysis
          HIGH   → full reasoning + self-critique
        """
        thinking_level = self._config.thinking_level
        if thinking_level == ThinkingLevel.OFF:
            return None

        if self._thinking_manager:
            trace = self._thinking_manager.think(
                history=history,
                level=thinking_level,
            )

            if trace:
                # Inject thinking trace as a system reminder
                history.add_system(f"[Thinking Trace]\n{trace}")

            return trace

        return None

    def _phase2_action(
        self,
        history: ConversationHistory,
        thinking_trace: Optional[str] = None,
    ) -> tuple[str, List[ToolCall]]:
        """
        Phase 2: Action LLM call with full tool schemas.

        The action model receives the conversation history including
        any thinking trace, along with available tool schemas.
        """
        messages = history.to_api_format()
        system_msg = {"role": "system", "content": self._agent.system_prompt}
        full_messages = [system_msg] + messages

        response = self._agent.call_llm(
            messages=full_messages,
            tools=self._agent.tool_schemas if self._agent.tool_schemas else None,
            model_role="action",
        )

        # Parse response
        choice = response["choices"][0]
        msg = choice["message"]
        content = msg.get("content", "") or ""
        raw_tool_calls = msg.get("tool_calls", [])

        tool_calls = []
        for tc in raw_tool_calls:
            func = tc.get("function", {})
            args = func.get("arguments", "{}")
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            tool_calls.append(ToolCall(
                id=tc.get("id", ""),
                name=func.get("name", ""),
                arguments=args,
            ))

        return content, tool_calls

    def _phase3_decision(
        self,
        ctx: IterationContext,
        history: ConversationHistory,
        response_content: str,
        tool_calls: List[ToolCall],
        deps: Any = None,
    ) -> Optional[str]:
        """
        Phase 3: Decision dispatch and doom-loop detection.

        Algorithm 1, lines 21-38:
        - If no tool calls: check for error recovery or implicit completion
        - If tool calls: fingerprint for doom-loop, then execute
        """
        if not tool_calls:
            # No tool calls → check conditions (Algorithm 1, lines 34-37)
            history.add_assistant(content=response_content)

            # Check if last tool failed
            last_msgs = history.get_recent(3)
            last_tool_failed = any(
                m.role == Role.TOOL and "Error" in (m.content or "")
                for m in last_msgs
            )

            if last_tool_failed and ctx.nudge_count < ctx.max_nudge_attempts:
                # Inject smart error recovery nudge (Section 2.3.5)
                nudge = self._get_smart_nudge(last_msgs)
                history.add_user(nudge)
                ctx.nudge_count += 1
                return None  # Continue loop

            # Implicit completion
            return response_content

        # Tool calls present → doom-loop detection (Algorithm 1, lines 23-27)
        doom_detected = False
        for tc in tool_calls:
            if ctx.add_fingerprint(tc.fingerprint):
                doom_detected = True

        history.add_assistant(content=response_content, tool_calls=tool_calls)

        if doom_detected:
            # Two-tier escalation:
            # First: inject warning message
            warning = (
                "[SYSTEM WARNING] The agent has called the same tool with "
                "identical arguments 3+ times. Try a different approach."
            )
            history.add_user(warning)
            return None  # Continue loop (skip tool execution this turn)

        # Execute tools (Algorithm 1, lines 29-31)
        results = self._execute_tools(ctx, history, tool_calls, deps)

        # Reflect and curate (Section 2.3.6)
        if self._memory_manager:
            self._memory_manager.reflect_and_curate(tool_calls, results, self._agent)

        # Check for explicit completion via task_complete
        for tc in tool_calls:
            if tc.name == "task_complete":
                return tc.arguments.get("summary", response_content)

        return None  # Continue loop

    def _execute_tools(
        self,
        ctx: IterationContext,
        history: ConversationHistory,
        tool_calls: List[ToolCall],
        deps: Any = None,
    ) -> List[ToolResult]:
        """
        Execute tool calls through the registry.

        Read-only tools run in parallel (up to 5 concurrent),
        write tools run sequentially (Section 2.2.3).
        """
        from opendev.tools.registry import ToolExecutionContext
        
        results = []
        for tc in tool_calls:
            if self._tool_logger:
                self._tool_logger.log_call(tc)

            if self._tool_registry:
                # Build context for this tool call (Section 2.4.1)
                ctx_data = ToolExecutionContext(
                    mode_manager=self._agent._mode_manager,
                    undo_manager=getattr(self._agent, "undo_manager", None),
                    working_dir=self._config.working_dir,
                    depth=self._depth,
                )
                
                result = self._tool_registry.execute(
                    tc.name, tc.arguments, deps=deps, ctx=ctx_data
                )
            else:
                result = ToolResult(
                    tool_call_id=tc.id,
                    name=tc.name,
                    content=f"Tool '{tc.name}' executed (stub).",
                )
            results.append(result)
            
            if self._tool_logger:
                self._tool_logger.log_result(result)

            history.add_tool_result(result)
        return results

    def _get_smart_nudge(self, recent_messages: List[Message]) -> str:
        """
        Generate a targeted error recovery nudge (Section 2.3.5).

        Classifies error into categories and provides specific guidance.
        """
        # Extract error info from recent messages
        error_msg = ""
        for m in recent_messages:
            if m.role == Role.TOOL and m.content and "Error" in m.content:
                error_msg = m.content
                break

        lower = error_msg.lower()

        if "permission" in lower or "access denied" in lower:
            return (
                "[Recovery Nudge] Permission denied. Try running with "
                "elevated permissions or check file ownership."
            )
        elif "not found" in lower or "no such file" in lower:
            return (
                "[Recovery Nudge] File not found. Verify the path exists "
                "using list_files, then retry with the correct path."
            )
        elif "content not found" in lower or "match" in lower:
            return (
                "[Recovery Nudge] The file has changed since you last read it. "
                "Re-read the file and retry your edit with the current content."
            )
        elif "syntax" in lower or "parse" in lower:
            return (
                "[Recovery Nudge] Syntax error in output. Check the format "
                "and fix invalid syntax before retrying."
            )
        elif "rate limit" in lower or "429" in lower:
            return (
                "[Recovery Nudge] Rate limit hit. Wait a moment before retrying."
            )
        elif "timeout" in lower:
            return (
                "[Recovery Nudge] Operation timed out. Try a simpler command "
                "or increase the timeout parameter."
            )
        else:
            return (
                "[Recovery Nudge] The previous operation failed. "
                "Review the error and try a different approach."
            )
