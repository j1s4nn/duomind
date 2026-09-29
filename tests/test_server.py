"""Test FastAPI server."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from duomind.server import (
    Message,
    _MAX_TOOL_BLOCK_CHARS,
    _extract_tool_call,
    _tool_choice_required,
    _tool_prompt,
    _trim_messages_to_context,
    app,
)


@pytest.fixture
def client():
    """Test client."""
    return TestClient(app)


def test_health_endpoint_no_backend(client):
    """Test health endpoint when backend not initialized."""
    response = client.get("/health")
    assert response.status_code == 503


def test_models_endpoint(client):
    """Test models list endpoint."""
    with patch("duomind.server.config") as mock_config:
        mock_cfg = MagicMock()
        mock_cfg.model_path = "test-model"
        mock_config.load.return_value = mock_cfg

        response = client.get("/v1/models")
        assert response.status_code == 200
        data = response.json()
        assert "data" in data
        assert len(data["data"]) > 0


def test_stats_endpoint(client):
    """Test stats endpoint."""
    with patch("duomind.server.config") as mock_config:
        mock_cfg = MagicMock()
        mock_cfg.jev_enabled = True
        mock_cfg.llm_backend = "llamacpp"
        mock_cfg.model_path = "test-model"
        mock_config.load.return_value = mock_cfg

        response = client.get("/v1/duomind/stats")
        assert response.status_code == 200
        data = response.json()
        assert "jev_enabled" in data
        assert data["jev_enabled"] is True


def test_chat_completions_auth(client):
    """Test that auth is enforced when configured."""
    with patch("duomind.server.config") as mock_config, \
         patch("duomind.server.backend") as mock_backend:

        mock_cfg = MagicMock()
        mock_cfg.api_key = "secret"
        mock_cfg.jev_enabled = False
        mock_cfg.tools_enabled = True
        mock_cfg.max_mid_checkpoints = 3
        mock_cfg.mid_segment_tokens = 160
        mock_cfg.system_prompt = None
        mock_cfg.context_size = 8192
        mock_config.load.return_value = mock_cfg

        async def fake_generate(prompt, max_tokens=512, temperature=0.7, stop=None, stream=False):
            yield "ok"

        mock_backend.encode_prompt = AsyncMock(return_value="prompt")
        mock_backend.generate = fake_generate

        # No auth header
        response = client.post("/v1/chat/completions", json={
            "model": "test",
            "messages": [{"role": "user", "content": "test"}]
        })
        assert response.status_code == 401

        # Wrong key
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "test",
                "messages": [{"role": "user", "content": "test"}]
            },
            headers={"Authorization": "Bearer wrong"}
        )
        assert response.status_code == 401

        # Correct key proceeds past auth.
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "test",
                "messages": [{"role": "user", "content": "test"}]
            },
            headers={"Authorization": "Bearer secret"}
        )
        assert response.status_code == 200


def test_chat_completions_tool_calls(client):
    """Tool calls from the model are returned in OpenAI format."""
    with patch("duomind.server.config") as mock_config, \
         patch("duomind.server.backend") as mock_backend:

        mock_cfg = MagicMock()
        mock_cfg.api_key = None
        mock_cfg.jev_enabled = False
        mock_cfg.tools_enabled = True
        mock_cfg.max_mid_checkpoints = 3
        mock_cfg.mid_segment_tokens = 160
        mock_cfg.context_size = 8192
        mock_config.load.return_value = mock_cfg

        tool_call_json = (
            '<tool_call>{"name": "create_file", '
            '"arguments": {"path": "a.py", "content": "print(1)"}}</tool_call>'
        )

        async def fake_generate(prompt, max_tokens=512, temperature=0.7, stop=None, stream=False):
            yield tool_call_json

        mock_backend.encode_prompt = AsyncMock(return_value="prompt")
        mock_backend.generate = fake_generate

        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "test",
                "messages": [{"role": "user", "content": "Create a.py"}],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "create_file",
                            "description": "Create a file",
                            "parameters": {"type": "object"},
                        },
                    }
                ],
            },
        )
        assert response.status_code == 200
        data = response.json()
        choice = data["choices"][0]
        assert choice["finish_reason"] == "tool_calls"
        tool_calls = choice["message"]["tool_calls"]
        assert tool_calls[0]["function"]["name"] == "create_file"


def test_extract_tool_call():
    """Tool-call parser extracts valid JSON blocks."""
    text = '<tool_call>{"name": "fetch_web", "arguments": {"url": "https://x"}}</tool_call>'
    result = _extract_tool_call(text)
    assert result is not None
    assert result["name"] == "fetch_web"
    assert result["arguments"] == '{"url": "https://x"}'

    assert _extract_tool_call("no tool here") is None


def test_tool_choice_required():
    """Tool-choice coercion handles auto/required/named."""
    assert _tool_choice_required(None) is None
    assert _tool_choice_required("auto") is None
    assert _tool_choice_required("required") == "__required__"
    assert _tool_choice_required({"type": "function", "function": {"name": "create_file"}}) == "create_file"


def test_trim_messages_to_context_keeps_recent_and_system():
    """Oversized histories are trimmed but keep the system and last messages."""
    messages = [
        Message(role="system", content="S" * 100_000),
        Message(role="user", content="old history " * 10_000),
        Message(role="user", content="delete that file"),
    ]
    trimmed = _trim_messages_to_context(messages, context_size=8192, response_max_tokens=512)

    assert trimmed[-1].content == "delete that file"
    assert trimmed[0].role == "system"
    total = sum(len(m.content or "") for m in trimmed)
    # Budget = (8192 - 512) * 4 = 30720 chars.
    assert total <= 30720


def test_trim_messages_to_context_reserves_overhead():
    """Fixed system/tool overhead is reserved out of the context budget."""
    messages = [
        Message(role="system", content="S" * 100_000),
        Message(role="user", content="old history " * 10_000),
        Message(role="user", content="delete that file"),
    ]
    trimmed = _trim_messages_to_context(
        messages, context_size=8192, response_max_tokens=512, overhead_tokens=1000
    )
    total = sum(len(m.content or "") for m in trimmed)
    # Budget = (8192 - 512 - 1000) * 4 = 26720 chars.
    assert total <= 26720
    assert trimmed[-1].content == "delete that file"


def test_tool_prompt_caps_large_tool_list():
    """A large tool list is truncated so it cannot overflow the context."""
    tools = [
        {
            "type": "function",
            "function": {
                "name": f"tool_{i}",
                "description": "do things",
                "parameters": {
                    "type": "object",
                    "properties": {"data": {"type": "string", "description": "y" * 20_000}},
                },
            },
        }
        for i in range(50)
    ]
    block = _tool_prompt(tools)
    assert len(block) <= _MAX_TOOL_BLOCK_CHARS
    assert "tool_0" in block



def test_trim_messages_to_context_no_system():
    """A history with no system message still drops the oldest messages."""
    messages = [
        Message(role="user", content="old history " * 10_000),
        Message(role="user", content="delete that file"),
    ]
    trimmed = _trim_messages_to_context(messages, context_size=8192, response_max_tokens=512)

    assert trimmed[-1].content == "delete that file"
    assert len(trimmed) < len(messages)
