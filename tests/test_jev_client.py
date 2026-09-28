"""Test Jev client."""

import pytest
from unittest.mock import MagicMock, patch

from duomind.decisions import DECISION_REGISTRY, DecisionStage, get_decisions_for_stage
from duomind.jev_client import CircuitBreaker, JevClient


def test_circuit_breaker():
    """Test circuit breaker functionality."""
    breaker = CircuitBreaker(failure_threshold=3, timeout=1)

    # Initially closed
    assert breaker.state == "closed"
    assert breaker.can_attempt()

    # Record failures
    breaker.record_failure()
    assert breaker.can_attempt()

    breaker.record_failure()
    assert breaker.can_attempt()

    breaker.record_failure()
    # Should open after 3 failures
    assert breaker.state == "open"
    assert not breaker.can_attempt()

    # Record success should close
    breaker.record_success()
    assert breaker.state == "closed"


@patch("duomind.jev_client.TypeSafeClient")
def test_jev_client_disabled(mock_client_class):
    """Test Jev client when disabled."""
    client = JevClient(
        api_key="test-key",
        enabled=False,
        confidence_threshold=0.6
    )

    assert not client.enabled
    assert client.client is None

    # Should use fallback
    decisions = get_decisions_for_stage(DecisionStage.PRE)
    results = client.ask_batch({"prompt": "test"}, decisions)

    assert len(results) == len(decisions)
    for name, result in results.items():
        assert result["source"] == "fallback"


@patch("duomind.jev_client.TypeSafeClient")
def test_jev_client_caching(mock_client_class):
    """Test that caching works."""
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client

    # Mock response
    mock_response = MagicMock()
    mock_response.answers = {}
    mock_client.system_one.return_value = mock_response

    client = JevClient(
        api_key="test-key",
        enabled=True,
        confidence_threshold=0.6
    )

    state = {"prompt": "test"}
    decisions = {"needs_generation": DECISION_REGISTRY["needs_generation"]}

    # First call should hit Jev
    client.ask_batch(state, decisions)
    assert mock_client.system_one.call_count == 1

    # Second call with same state should hit cache
    client.ask_batch(state, decisions)
    assert mock_client.system_one.call_count == 1  # Still 1

    # Different state should hit Jev again
    client.ask_batch({"prompt": "different"}, decisions)
    assert mock_client.system_one.call_count == 2


def test_jev_client_stats():
    """Test stats tracking."""
    client = JevClient(
        api_key="test-key",
        enabled=False,  # Use fallback
        confidence_threshold=0.6
    )

    decisions = get_decisions_for_stage(DecisionStage.PRE)
    client.ask_batch({"prompt": "test"}, decisions)

    stats = client.get_stats()
    assert stats["total_calls"] == 1
    assert stats["fallback_calls"] == 1
    assert "cache_hit_rate" in stats
