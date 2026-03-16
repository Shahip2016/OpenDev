"""
Agent dependency injection (Section 2.2.1).

AgentDependencies carries seven fields that tools need at execution time.
SubAgentDeps carries a lighter three-field subset, enforcing an isolation
boundary: subagents do not get session_manager, console, or config.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel


class AgentDependencies(BaseModel):
    """
    Full dependency set for the main agent's ReAct loop.

    Individual managers are unpacked from this object and passed as
    keyword arguments to execute_tool(), keeping the tool registry
    interface flat.
    """
    mode_manager: Any = None
    approval_manager: Any = None
    undo_manager: Any = None
    session_manager: Any = None
    working_dir: str = "."
    console: Any = None
    config: Any = None

    class Config:
        arbitrary_types_allowed = True


class SubAgentDeps(BaseModel):
    """
    Lightweight dependency set for subagents.

    Omitted fields enforce an isolation boundary:
    - No session_manager: subagent messages are not persisted
    - No console: output flows through ui_callback
    - No config: each subagent carries its own from construction
    """
    mode_manager: Any = None
    approval_manager: Any = None
    undo_manager: Any = None

    class Config:
        arbitrary_types_allowed = True
