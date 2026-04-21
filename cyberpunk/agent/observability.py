"""Langfuse observability wiring.

Loads Langfuse credentials from the environment (``.env`` supported) and
builds a LangChain ``CallbackHandler`` that streams every LLM call, tool
invocation, and graph transition to Langfuse. Tracing is disabled silently
when keys are missing so the agent still runs fully offline.

Short-lived CLIs must call :func:`flush_langfuse` before exit — otherwise
in-flight spans are dropped by the background worker when the process dies.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from dotenv import load_dotenv

if TYPE_CHECKING:
    from langchain_core.callbacks import BaseCallbackHandler

_env_loaded = False
_client: Any | None = None


def _ensure_env_loaded() -> None:
    global _env_loaded
    if not _env_loaded:
        # ``load_dotenv`` must run before importing ``langfuse`` so the
        # singleton client picks up credentials on first access.
        load_dotenv()
        _env_loaded = True


def build_langfuse_handler() -> BaseCallbackHandler | None:
    """Return a Langfuse callback handler, or ``None`` if not configured.

    Requires ``LANGFUSE_PUBLIC_KEY`` and ``LANGFUSE_SECRET_KEY`` in the
    environment (or a ``.env`` file at the project root). ``LANGFUSE_HOST``
    is optional and defaults to Langfuse Cloud EU.
    """
    _ensure_env_loaded()

    if not (os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY")):
        return None

    # Import lazily so the package stays optional at runtime.
    from langfuse import get_client
    from langfuse.langchain import CallbackHandler

    global _client
    _client = get_client()
    return CallbackHandler()


def flush_langfuse() -> None:
    """Flush pending Langfuse events. Call before process exit."""
    if _client is not None:
        _client.flush()
