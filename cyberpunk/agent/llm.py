"""ChatOllama factory and Ollama health check for the agent."""

from __future__ import annotations

from typing import TYPE_CHECKING

import ollama
from langchain_ollama import ChatOllama

if TYPE_CHECKING:
    from cyberpunk.core.config import CyberPunkConfig


def build_chat_model(config: CyberPunkConfig) -> ChatOllama:
    """Construct a ``ChatOllama`` from the user's config.

    The returned model is **not** bound to any tools. Binding happens in
    ``cyberpunk.agent.graph.build_graph`` so the tool list can be
    stealth-filtered per run without recreating the base model.

    Args:
        config: The loaded CyberPunk configuration.

    Returns:
        A ``ChatOllama`` instance. Streaming is enabled so token events reach
        the status display through LangChain's callback system.
    """
    return ChatOllama(
        model=config.llm.model,
        base_url=config.llm.base_url,
        temperature=config.llm.temperature,
        # ``ChatOllama`` proxies ``num_predict`` via ``num_predict=...``
        num_predict=config.llm.max_tokens,
        # ``client_kwargs`` feeds the underlying ollama client's timeout.
        client_kwargs={"timeout": config.llm.timeout},
    )


def health_check(config: CyberPunkConfig) -> tuple[bool, str]:
    """Verify that Ollama is reachable and the configured model is pulled.

    We bypass LangChain here and talk to the ``ollama`` SDK directly because
    we want a cheap, non-streaming probe that can produce a friendly "run
    ``ollama pull X``" hint rather than surfacing a raw HTTP error to the
    user.

    Args:
        config: The loaded CyberPunk configuration.

    Returns:
        ``(ok, message)``. ``ok=True`` means the model is usable; ``message``
        is a human-readable status string to print in verbose mode or as an
        error in non-verbose mode.
    """
    client = ollama.Client(host=config.llm.base_url, timeout=config.llm.timeout)
    try:
        models = client.list()
    except Exception as e:
        return False, f"Cannot connect to Ollama: {e}"

    available: list[str] = [m.model for m in models.models if m.model]
    if config.llm.model in available:
        return True, f"Ollama ready, model '{config.llm.model}' available"

    # Try a looser match in case the user typed ``gemma4`` and Ollama has it
    # tagged as ``gemma4:e4b``.
    base_name = config.llm.model.split(":")[0]
    for name in available:
        if name.startswith(base_name):
            return True, (
                f"Ollama ready, model '{name}' available (requested '{config.llm.model}')"
            )

    return False, (
        f"Ollama running but model '{config.llm.model}' not found. "
        f"Available: {', '.join(available) or 'none'}. "
        f"Run: ollama pull {config.llm.model}"
    )
