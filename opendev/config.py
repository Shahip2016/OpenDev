"""
Configuration management for OpenDev.

Implements a 4-tier configuration hierarchy:
  1. Built-in defaults  (hardcoded sensible values)
  2. Environment variables  (API keys, CI/CD overrides)
  3. User-global settings  (~/.opendev/settings.json)
  4. Project-local settings (<project>/.opendev/settings.json)

Each tier overrides the one above it. API keys are ONLY loaded from
environment variables to prevent accidental exposure in version control.
"""

from __future__ import annotations

import json
import os
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ApprovalLevel(str, Enum):
    """Runtime autonomy levels for tool execution approval."""
    MANUAL = "manual"       # Explicit approval for every tool call
    SEMI_AUTO = "semi-auto" # Auto-approve read-only, prompt for writes
    AUTO = "auto"           # Approve all operations


class ThinkingLevel(str, Enum):
    """Depth levels for the optional thinking phase."""
    OFF = "off"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"           # HIGH includes self-critique


class AgentMode(str, Enum):
    """Dual-mode operation: Normal (full access) vs Plan (read-only)."""
    NORMAL = "normal"
    PLAN = "plan"


# ---------------------------------------------------------------------------
# Model role configuration  (Section 2.2.5)
# ---------------------------------------------------------------------------

class ModelRoleConfig(BaseModel):
    """Configuration for a single model role binding."""
    provider: str = "openai"
    model: str = "gpt-4o"
    temperature: float = 0.0
    max_tokens: int = 4096


class ModelConfig(BaseModel):
    """
    Five workload-optimized model roles with fallback chains.

    • action   – primary execution model for tool-based reasoning
    • thinking – extended reasoning without tools (fallback: action)
    • critique – self-evaluation (fallback: thinking → action)
    • vision   – vision-language model (fallback: action if vision-capable)
    • compact  – fast summarization for context compaction (fallback: action)
    """
    action: ModelRoleConfig = Field(default_factory=ModelRoleConfig)
    thinking: Optional[ModelRoleConfig] = None
    critique: Optional[ModelRoleConfig] = None
    vision: Optional[ModelRoleConfig] = None
    compact: Optional[ModelRoleConfig] = None

    def resolve(self, role: str) -> ModelRoleConfig:
        """Resolve a model role with its fallback chain."""
        fallback_chains: Dict[str, List[str]] = {
            "action":   ["action"],
            "thinking": ["thinking", "action"],
            "critique": ["critique", "thinking", "action"],
            "vision":   ["vision", "action"],
            "compact":  ["compact", "action"],
        }
        for candidate in fallback_chains.get(role, ["action"]):
            cfg = getattr(self, candidate, None)
            if cfg is not None:
                return cfg
        return self.action


# ---------------------------------------------------------------------------
# Application configuration  (Section 2.5.3)
# ---------------------------------------------------------------------------

class AppConfig(BaseModel):
    """
    Central application configuration.

    Resolved through a 4-tier hierarchy:
      built-in defaults → env vars → user-global → project-local
    """
    # Model configuration
    models: ModelConfig = Field(default_factory=ModelConfig)

    # Session
    auto_save_interval: int = 5
    max_iterations: int = 100

    # Context engineering thresholds  (Section 2.3.6)
    compaction_warning_threshold: float = 0.70
    compaction_mask_threshold: float = 0.80
    compaction_prune_threshold: float = 0.85
    compaction_aggressive_threshold: float = 0.90
    compaction_full_threshold: float = 0.99

    # Thinking  (Section 2.2.6)
    thinking_level: ThinkingLevel = ThinkingLevel.OFF
    episodic_memory_regenerate_threshold: int = 5
    working_memory_window: int = 6

    # Safety  (Section 2.1)
    approval_level: ApprovalLevel = ApprovalLevel.SEMI_AUTO
    max_nudge_attempts: int = 3
    max_todo_nudges: int = 2
    doom_loop_window: int = 20
    doom_loop_threshold: int = 3

    # Tool limits
    max_concurrent_tools: int = 5
    max_output_chars: int = 30_000
    large_output_threshold: int = 8_000
    max_undo_history: int = 50
    max_subagent_recursion: int = 3

    # Timeouts
    command_idle_timeout: int = 60
    command_absolute_timeout: int = 600

    # Paths
    user_config_dir: str = Field(
        default_factory=lambda: str(Path.home() / ".opendev")
    )
    working_dir: str = Field(default_factory=lambda: os.getcwd())


# ---------------------------------------------------------------------------
# Configuration Manager
# ---------------------------------------------------------------------------

class ConfigManager:
    """
    Manages the 4-tier configuration hierarchy.

    Loading order (each tier overrides the previous):
      1. Built-in defaults   → AppConfig() with no arguments
      2. Environment variables → OPENDEV_* prefixed env vars
      3. User-global settings → ~/.opendev/settings.json
      4. Project-local settings → <project>/.opendev/settings.json

    API keys are ONLY loaded from environment variables.
    """

    ENV_PREFIX = "OPENDEV_"

    def __init__(
        self,
        working_dir: Optional[str] = None,
        user_config_dir: Optional[str] = None,
    ):
        self._working_dir = working_dir or os.getcwd()
        self._user_config_dir = user_config_dir or str(
            Path.home() / ".opendev"
        )
        self._config: Optional[AppConfig] = None

    # -- public API ---------------------------------------------------------

    @property
    def config(self) -> AppConfig:
        if self._config is None:
            self._config = self._load()
        return self._config

    def reload(self) -> AppConfig:
        """Force re-load of configuration from all tiers."""
        self._config = self._load()
        return self._config

    # -- internal -----------------------------------------------------------

    def _load(self) -> AppConfig:
        # Tier 1: built-in defaults
        merged: Dict[str, Any] = {}

        # Tier 2: environment variables (OPENDEV_* → lower-cased keys)
        env_overrides = self._collect_env_vars()
        merged.update(env_overrides)

        # Tier 3: user-global settings
        user_path = Path(self._user_config_dir) / "settings.json"
        user_data = self._load_json(user_path)
        # Strip any API keys found in config files (security measure)
        user_data = self._strip_api_keys(user_data)
        merged.update(user_data)

        # Tier 4: project-local settings
        project_path = Path(self._working_dir) / ".opendev" / "settings.json"
        project_data = self._load_json(project_path)
        project_data = self._strip_api_keys(project_data)
        merged.update(project_data)

        # Inject working dir
        merged["working_dir"] = self._working_dir
        merged["user_config_dir"] = self._user_config_dir

        return AppConfig(**merged)

    def _collect_env_vars(self) -> Dict[str, Any]:
        """Collect OPENDEV_* environment variables."""
        result: Dict[str, Any] = {}
        for key, value in os.environ.items():
            if key.startswith(self.ENV_PREFIX):
                config_key = key[len(self.ENV_PREFIX):].lower()
                result[config_key] = value
        return result

    @staticmethod
    def _load_json(path: Path) -> Dict[str, Any]:
        """Load a JSON file, returning empty dict on failure."""
        try:
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return data
        except (json.JSONDecodeError, OSError, PermissionError):
            pass
        return {}

    @staticmethod
    def _strip_api_keys(data: Dict[str, Any]) -> Dict[str, Any]:
        """Remove any API key fields from config data (security measure)."""
        sensitive_keys = {"api_key", "api_secret", "token", "secret"}
        return {
            k: v for k, v in data.items()
            if k.lower() not in sensitive_keys
        }

    # -- API key access (env-only) ------------------------------------------

    @staticmethod
    def get_api_key(provider: str) -> Optional[str]:
        """
        Retrieve an API key for the given provider.

        Keys are loaded ONLY from environment variables to prevent
        accidental exposure in version-controlled config files.
        """
        env_key = f"OPENDEV_{provider.upper()}_API_KEY"
        key = os.environ.get(env_key)
        if key:
            return key
        # Fallback to common env var names
        common_names = {
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "fireworks": "FIREWORKS_API_KEY",
        }
        fallback = common_names.get(provider.lower())
        if fallback:
            return os.environ.get(fallback)
        return None
