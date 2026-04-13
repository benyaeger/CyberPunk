"""Ollama SDK wrapper: health check, tool calling, retries, streaming."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import ollama

from cyberpunk.models import AgentMessage, ToolCall


class OllamaClient:
    """Wrapper around the Ollama Python SDK for tool-calling conversations."""

    def __init__(
        self,
        model: str = "gemma4:e4b ",
        base_url: str = "http://localhost:11434",
        temperature: float = 0.1,
        max_tokens: int = 4096,
        timeout: int = 120,
        max_retries: int = 2,
    ) -> None:
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.max_retries = max_retries
        self._client = ollama.Client(host=base_url, timeout=timeout)

    def health_check(self) -> tuple[bool, str]:
        """Check if Ollama is running and the model is available.

        Returns:
            (ok, message) tuple.
        """
        try:
            models = self._client.list()
            available = [m.model for m in models.models]
            if self.model in available:
                return True, f"Ollama ready, model '{self.model}' available"
            # Check without tag
            base_name = self.model.split(":")[0]
            for name in available:
                if name.startswith(base_name):
                    return True, f"Ollama ready, model '{name}' available (requested '{self.model}')"
            return False, (
                f"Ollama running but model '{self.model}' not found. "
                f"Available: {', '.join(available) or 'none'}. "
                f"Run: ollama pull {self.model}"
            )
        except Exception as e:
            return False, f"Cannot connect to Ollama: {e}"

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        on_token: Callable[[str], None] | None = None,
    ) -> AgentMessage:
        """Send a chat request with optional tool definitions and streaming.

        Args:
            messages: Conversation history in Ollama message format.
            tools: Tool definitions in Ollama schema format.
            on_token: Optional callback invoked with each text token during streaming.

        Returns:
            AgentMessage with content and/or tool_calls.
        """
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                kwargs: dict[str, Any] = {
                    "model": self.model,
                    "messages": messages,
                    "options": {
                        "temperature": self.temperature,
                        "num_predict": self.max_tokens,
                    },
                    "stream": True,
                }
                if tools:
                    kwargs["tools"] = tools

                # Stream the response
                content_parts: list[str] = []
                tool_calls: list[ToolCall] = []
                eval_count: int | None = None
                prompt_eval_count: int | None = None

                for chunk in self._client.chat(**kwargs):
                    # Accumulate text content
                    token = chunk.message.content or ""
                    if token:
                        content_parts.append(token)
                        if on_token:
                            on_token(token)

                    # Collect tool calls (typically in the final chunk)
                    if chunk.message.tool_calls:
                        for tc in chunk.message.tool_calls:
                            tool_calls.append(
                                ToolCall(
                                    tool_name=tc.function.name,
                                    arguments=tc.function.arguments or {},
                                )
                            )

                    # Capture token counts from the final chunk
                    if hasattr(chunk, "eval_count") and chunk.eval_count:
                        eval_count = chunk.eval_count
                    if hasattr(chunk, "prompt_eval_count") and chunk.prompt_eval_count:
                        prompt_eval_count = chunk.prompt_eval_count

                return AgentMessage(
                    role="assistant",
                    content="".join(content_parts),
                    tool_calls=tool_calls,
                    eval_count=eval_count,
                    prompt_eval_count=prompt_eval_count,
                )

            except Exception as e:
                last_error = e
                if attempt < self.max_retries:
                    time.sleep(2 ** attempt)
                    continue
                raise

        raise RuntimeError(f"LLM request failed after {self.max_retries + 1} attempts: {last_error}")
