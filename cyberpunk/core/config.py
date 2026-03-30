"""Configuration loader with YAML files, env var overrides, and Pydantic validation."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class LLMConfig(BaseModel):
    provider: str = "ollama"
    model: str = "qwen2.5:7b"
    base_url: str = "http://localhost:11434"
    temperature: float = 0.1
    max_tokens: int = 4096
    timeout: int = 300


class ScanningConfig(BaseModel):
    target_subnet: str | None = None
    excluded_hosts: list[str] = Field(default_factory=list)
    max_concurrent_probes: int = 50
    probe_timeout: int = 3


class OutputConfig(BaseModel):
    format: str = "rich"
    verbosity: str = "normal"


class SafetyConfig(BaseModel):
    log_all_actions: bool = True
    audit_log_path: str = "~/.cyberpunk/audit.log"
    max_agent_iterations: int = 15


class DatabaseConfig(BaseModel):
    path: str = "~/.cyberpunk/network_map.db"


class CyberPunkConfig(BaseModel):
    llm: LLMConfig = Field(default_factory=LLMConfig)
    scanning: ScanningConfig = Field(default_factory=ScanningConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    safety: SafetyConfig = Field(default_factory=SafetyConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge override into base."""
    merged = dict(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML file, returning empty dict if missing or invalid."""
    if not path.exists():
        return {}
    with open(path) as f:
        data = yaml.safe_load(f)
    return data if isinstance(data, dict) else {}


def load_config(config_path: str | None = None) -> CyberPunkConfig:
    """Load config with priority: defaults < project < user < explicit < env vars.

    Args:
        config_path: Optional explicit config file path (from --config flag).

    Returns:
        Validated CyberPunkConfig.
    """
    # Start with empty (Pydantic defaults fill in)
    merged: dict[str, Any] = {}

    # Project-level defaults
    project_config = Path(__file__).parent.parent.parent / "configs" / "default_config.yaml"
    merged = _deep_merge(merged, _load_yaml(project_config))

    # User-level config
    user_config = Path.home() / ".cyberpunk" / "config.yaml"
    merged = _deep_merge(merged, _load_yaml(user_config))

    # Explicit --config flag
    if config_path:
        merged = _deep_merge(merged, _load_yaml(Path(config_path)))

    # Environment variable overrides
    if env_model := os.environ.get("CYBERPUNK_MODEL"):
        merged.setdefault("llm", {})["model"] = env_model
    if env_url := os.environ.get("CYBERPUNK_OLLAMA_URL"):
        merged.setdefault("llm", {})["base_url"] = env_url

    return CyberPunkConfig(**merged)
