"""Test doubles for the Anthropic client.

A minimal stand-in for ``AsyncAnthropic`` so agent tests never make a real (paid)
API call. It returns a preset sequence of responses shaped like the SDK's
``Message`` — enough ``.content`` / ``.stop_reason`` / ``.usage`` for our loops.

Not a test module itself (no ``test_`` prefix), so pytest won't collect it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FakeUsage:
    input_tokens: int = 10
    output_tokens: int = 5


@dataclass
class FakeTextBlock:
    text: str
    type: str = "text"


@dataclass
class FakeToolUseBlock:
    name: str
    input: dict[str, Any]
    id: str
    type: str = "tool_use"


@dataclass
class FakeResponse:
    content: list[Any]
    stop_reason: str
    usage: FakeUsage = field(default_factory=FakeUsage)
    # Populated for messages.parse() responses (structured outputs): the already
    # schema-validated model instance the real SDK exposes on ``parsed_output``.
    # ``None`` mimics a refusal/truncation where the API returns no parsed object.
    parsed_output: Any = None


class _FakeMessages:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self._responses = responses
        self.calls = 0

    async def create(self, **_: Any) -> FakeResponse:
        resp = self._responses[min(self.calls, len(self._responses) - 1)]
        self.calls += 1
        return resp

    async def parse(self, **_: Any) -> FakeResponse:
        # Same response sequence as create(); the real SDK's parse() shares the
        # Messages resource. Tests set ``parsed_output`` on the FakeResponse.
        return await self.create()


class FakeAnthropic:
    """Quacks like ``AsyncAnthropic`` for the parts our agents touch."""

    def __init__(self, responses: list[FakeResponse]) -> None:
        self.messages = _FakeMessages(responses)
