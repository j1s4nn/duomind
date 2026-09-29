"""Test decision registry."""


from duomind.decisions import (
    DECISION_REGISTRY,
    DecisionStage,
    LocalFallbackClassifier,
    build_jev_question,
    get_decisions_for_stage,
    verbosity_label,
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


def test_expanded_registry_has_new_points():
    """New steering decisions are registered across all stages."""
    for name in ("verbosity", "format", "needs_tool", "too_verbose", "correct_format"):
        assert name in DECISION_REGISTRY, f"{name} missing"

    pre = get_decisions_for_stage(DecisionStage.PRE)
    mid = get_decisions_for_stage(DecisionStage.MID)
    post = get_decisions_for_stage(DecisionStage.POST)

    assert "needs_tool" in pre
    assert "should_stop" in mid
    assert "too_verbose" in post


def test_verbosity_label_mapping():
    """Verbosity Score values map to steering labels."""
    assert verbosity_label(0) == "brief"
    assert verbosity_label(1) == "normal"
    assert verbosity_label(2) == "detailed"
    assert verbosity_label(None) == "normal"
