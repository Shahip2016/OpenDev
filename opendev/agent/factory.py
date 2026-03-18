"""
Agent factory — single entry point for agent construction (Section 2.2.1).

Both TUI and Web UI invoke the same create_agents() method, ensuring
identical setup regardless of frontend. Three phases in strict order:
  Phase 1 (Skills)   → discover skill definitions, register SkillLoader
  Phase 2 (Subagents) → create SubAgentManager, register builtin + custom agents
  Phase 3 (Main agent) → construct MainAgent with full tool access
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from opendev.agent.main_agent import MainAgent
from opendev.agent.subagent import SubAgentManager
from opendev.config import AppConfig
from opendev.context.memory import MemoryManager
from opendev.skills.loader import SkillLoader


@dataclass
class AgentSuite:
    """
    Bundle returned by AgentFactory.create_agents().

    Contains the main agent, SubAgentManager, and SkillLoader.
    """
    main_agent: MainAgent
    subagent_manager: SubAgentManager
    skill_loader: SkillLoader


class AgentFactory:
    """
    Single entry point for agent construction.

    The ordering constraint is essential:
      Phase 2 must complete before Phase 3 because spawn_subagent tool
      description is dynamically built from the set of registered agents.
    """

    def __init__(
        self,
        config: AppConfig,
        tool_registry: Any = None,
        mode_manager: Any = None,
    ):
        self._config = config
        self._tool_registry = tool_registry
        self._mode_manager = mode_manager
        self._memory_manager = MemoryManager()

    def create_agents(self) -> AgentSuite:
        """
        Execute the three-phase agent construction pipeline.

        Returns an AgentSuite bundling all constructed components.
        """
        # Phase 1: Skills — discover from three directories
        skill_loader = SkillLoader(
            builtin_dir="opendev/skills/builtin",
            user_dir=f"{self._config.user_config_dir}/skills",
            project_dir=".opendev/skills",
        )
        skill_loader.discover()

        if self._tool_registry:
            self._tool_registry.register_skill_loader(skill_loader)

        # Phase 2: Subagents — register builtin + custom agents
        subagent_manager = SubAgentManager(
            config=self._config,
            tool_registry=self._tool_registry,
            mode_manager=self._mode_manager,
        )
        subagent_manager.register_defaults()

        if self._tool_registry:
            self._tool_registry.set_subagent_manager(subagent_manager)

        # Phase 3: Main agent — full access to all tools
        main_agent = MainAgent(
            config=self._config,
            tool_registry=self._tool_registry,
            mode_manager=self._mode_manager,
            memory_manager=self._memory_manager,
            allowed_tools=None,  # Full access
        )

        return AgentSuite(
            main_agent=main_agent,
            subagent_manager=subagent_manager,
            skill_loader=skill_loader,
        )
