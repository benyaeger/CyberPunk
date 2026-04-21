"""Integration health checks.

Every external integration CyberPunk depends on (LLM backend, observability,
future cloud services) must register a probe here so ``cyberpunk health``
can report its status in one place.

Adding a new integration:

1. Write a ``check_<name>(config)`` function that returns ``HealthResult``.
   Catch broad exceptions and surface a human-readable ``message`` — this
   command exists precisely to diagnose misconfiguration, so it must never
   raise.
2. Append a ``HealthCheck`` entry to :data:`CHECKS`.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cyberpunk.core.config import CyberPunkConfig


@dataclass(frozen=True)
class HealthResult:
    ok: bool
    message: str


@dataclass(frozen=True)
class HealthCheck:
    name: str
    check: Callable[["CyberPunkConfig"], HealthResult]


def check_ollama(config: CyberPunkConfig) -> HealthResult:
    """Verify Ollama is reachable and the configured model is pulled."""
    from cyberpunk.agent.llm import health_check

    ok, msg = health_check(config)
    return HealthResult(ok=ok, message=msg)


def check_langfuse(config: CyberPunkConfig) -> HealthResult:
    """Verify Langfuse credentials are present and authenticate successfully.

    Skipped (ok=True) when no keys are configured — Langfuse is optional,
    the agent runs fully offline without it.
    """
    public = os.getenv("LANGFUSE_PUBLIC_KEY")
    secret = os.getenv("LANGFUSE_SECRET_KEY")
    host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")

    if not (public and secret):
        return HealthResult(ok=True, message="Not configured (optional) — tracing disabled")

    try:
        from langfuse import get_client
    except ImportError as e:
        return HealthResult(ok=False, message=f"langfuse SDK not installed: {e}")

    try:
        client = get_client()
        auth = client.auth_check()
    except Exception as e:
        return HealthResult(ok=False, message=f"{type(e).__name__}: {e}")

    if auth:
        return HealthResult(ok=True, message=f"Authenticated at {host}")
    return HealthResult(ok=False, message=f"Auth failed at {host} — check keys")


CHECKS: list[HealthCheck] = [
    HealthCheck(name="ollama", check=check_ollama),
    HealthCheck(name="langfuse", check=check_langfuse),
]


def run_all(config: CyberPunkConfig) -> list[tuple[str, HealthResult]]:
    """Run every registered check, swallowing exceptions into failed results."""
    results: list[tuple[str, HealthResult]] = []
    for entry in CHECKS:
        try:
            result = entry.check(config)
        except Exception as e:
            result = HealthResult(ok=False, message=f"check crashed: {type(e).__name__}: {e}")
        results.append((entry.name, result))
    return results
