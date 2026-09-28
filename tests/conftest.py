"""Test fixtures for DuoMind."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from pathlib import Path

from duomind.backends.base import LLMBackend
from duomind.jev_client import JevClient


class MockBackend(LLMBackend):
    """Mock LLM backend for testing."""

    def __init__(self):
        self.started = False

    async def start(self):
        self.started = True

    async def stop(self):
        self.started = False

    async def health(self) -> bool:
        return self.started

    async def generate(self, prompt, max_tokens=512, temperature=0.7, stop=None, stream=False):
        if stream:
            for chunk in ["This ", "is ", "a ", "test"]:
                yield chunk
        else:
            yield "This is a test response."

    async def encode_prompt(self, messages):
        parts = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            parts.append(f"{role.title()}: {content}")
        parts.append("Assistant:")
        return "\n\n".join(parts)


@pytest.fixture
def mock_backend():
    """Provide a mock backend."""
    return MockBackend()


@pytest.fixture
def mock_jev_client():
    """Provide a mock Jev client."""
    client = MagicMock(spec=JevClient)
    client.enabled = True
    client.ask_batch = MagicMock(return_value={
        "needs_generation": {"value": True, "confidence": 0.9, "source": "jev"},
        "needs_reasoning": {"value": True, "confidence": 0.8, "source": "jev"},
        "safety": {"value": True, "confidence": 0.95, "source": "jev"},
    })
    client.get_stats = MagicMock(return_value={
        "total_calls": 10,
        "cache_hits": 2,
        "jev_calls": 8,
        "fallback_calls": 0,
    })
    return client


@pytest.fixture
def sample_chat_request():
    """Sample chat completion request."""
    return {
        "model": "test-model",
        "messages": [
            {"role": "user", "content": "What is 2+2?"}
        ],
        "temperature": 0.7,
        "max_tokens": 100,
        "stream": False
    }
