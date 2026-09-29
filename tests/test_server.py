"""Test FastAPI server."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from duomind.server import app


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
        mock_config.load.return_value = mock_cfg

        mock_backend.health.return_value = True
        mock_backend.encode_prompt = AsyncMock(return_value="User: test\n\nAssistant:")
        mock_backend.generate.return_value.__aiter__.return_value = ["This is a test response."]

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

        # Correct key should proceed (will fail at backend but auth passes)
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "test",
                "messages": [{"role": "user", "content": "test"}]
            },
            headers={"Authorization": "Bearer secret"}
        )
        # May fail for other reasons but not 401
        assert response.status_code != 401
