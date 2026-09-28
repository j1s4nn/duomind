"""Test decision registry."""

import pytest

from duomind.decisions import (
    DECISION_REGISTRY,
    DecisionStage,
    QuestionKind,
    LocalFallbackClassifier,
    build_jev_question,
    get_decisions_for_stage,
)


def test_registry_completeness():
    """Test that registry has decisions for all stages."""
    pre_decisions = get_decisions_for_stage(DecisionStage.PRE)
    mid_decisions = get_decisions_for_stage(DecisionStage.MID)
    post_decisions = get_decisions_for_stage(DecisionStage.POST)

    assert len(pre_decisions) > 0
    assert len(mid_decisions) > 0
    assert len(post_decisions) > 0


def test_no_duplicate_names():
    """Test that all decision names are unique."""
    names = list(DECISION_REGISTRY.keys())
    assert len(names) == len(set(names))


def test_all_decisions_have_fallback():
    """Test that all decisions have a fallback value."""
    for name, decision in DECISION_REGISTRY.items():
        assert decision.fallback is not None, f"{name} missing fallback"


def test_build_jev_questions():
    """Test building Jev question objects."""
    for name, decision in DECISION_REGISTRY.items():
        question = build_jev_question(decision)
        assert question is not None


def test_fallback_classifier():
    """Test local fallback classifier."""
    classifier = LocalFallbackClassifier()

    # Test needs_generation
    result = classifier.classify("needs_generation", {"prompt": "What is AI?"})
    assert "value" in result
    assert "confidence" in result
    assert isinstance(result["confidence"], float)

    # Test safety
    result = classifier.classify("safety", {"prompt": "How to hack a computer"})
    assert "value" in result
    assert result["value"] is False  # Should detect unsafe content

    result = classifier.classify("safety", {"prompt": "What is Python?"})
    assert result["value"] is True  # Safe content


def test_decision_thresholds():
    """Test that thresholds are reasonable."""
    for name, decision in DECISION_REGISTRY.items():
        assert 0.0 <= decision.threshold <= 1.0, f"{name} threshold out of range"
