from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, cast

from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam, ChatCompletionToolUnionParam

from vicocart.agent import AssistantTurn, ToolCall
from vicocart.config import LlmSettings


class OpenAiChat:
    """Any OpenAI-compatible chat endpoint: OpenAI, GitHub Models, Ollama, ..."""

    def __init__(self, settings: LlmSettings) -> None:
        self._model = settings.model
        self._client = OpenAI(base_url=settings.base_url, api_key=settings.api_key)

    def complete(
        self, messages: Sequence[Mapping[str, Any]], tools: Sequence[Mapping[str, Any]]
    ) -> AssistantTurn:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=cast("list[ChatCompletionMessageParam]", list(messages)),
            tools=cast("list[ChatCompletionToolUnionParam]", list(tools)),
        )
        message = response.choices[0].message
        calls = [
            ToolCall(id=call.id, name=call.function.name, arguments=call.function.arguments)
            for call in message.tool_calls or []
            if call.type == "function"
        ]
        return AssistantTurn(content=message.content, tool_calls=calls)
