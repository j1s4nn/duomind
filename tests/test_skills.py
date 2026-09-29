"""Test the skill registry and its selection logic."""

from duomind.decisions import (
    DECISION_REGISTRY,
    DecisionStage,
    LocalFallbackClassifier,
)
from duomind.skills import (
    SKILL_REGISTRY,
    get_skill,
    get_skill_instructions,
    list_skill_names,
    select_skill,
)


def test_registry_has_expected_skills():
    """All core skills are registered."""
    for name in ("webdev", "coding", "debug", "git", "webfetch", "general"):
        assert name in SKILL_REGISTRY, f"{name} missing from skill registry"


def test_skill_decision_point_exists():
    """The skill decision is registered in the PRE stage."""
    assert "skill" in DECISION_REGISTRY
    skill = DECISION_REGISTRY["skill"]
    assert skill.stage == DecisionStage.PRE
    assert skill.fallback == "general"


def test_select_skill_website_from_url():
    """A "build a website that looks like this URL" request matches webdev."""
    state = {
        "prompt": "Create a project with code and the website must look like "
        "this https://example.com"
    }
    assert select_skill(state) == "webdev"


def test_select_skill_debug():
    """A bug report matches the debug skill."""
    assert select_skill({"prompt": "There is a bug: TypeError in my script"}) == "debug"


def test_select_skill_git():
    """A git request matches the git skill."""
    assert select_skill({"prompt": "commit my changes and push to github"}) == "git"


def test_select_skill_webfetch():
    """A fetch request matches the webfetch skill."""
    assert select_skill({"prompt": "fetch https://docs.python.org and summarize it"}) == "webfetch"


def test_select_skill_coding():
    """A coding request matches the coding skill."""
    assert select_skill({"prompt": "write a python function that sorts a list"}) == "coding"


def test_select_skill_general():
    """Unknown or empty prompts fall back to general."""
    assert select_skill({"prompt": ""}) == "general"
    assert select_skill({"prompt": "hello"}) == "general"


def test_get_skill_instructions():
    """Instructions are present for specialized skills and empty for general."""
    assert get_skill_instructions("webdev")
    assert get_skill_instructions("debug")
    assert get_skill_instructions("general") == ""
    assert get_skill_instructions("does-not-exist") == ""


def test_get_skill_fallback():
    """Unknown skill names resolve to the general skill."""
    assert get_skill("does-not-exist").name == "general"


def test_list_skill_names_order():
    """Skill names are listed in priority order with general last."""
    names = list_skill_names()
    assert names[-1] == "general"
    assert len(names) == len(SKILL_REGISTRY)


def test_fallback_classifier_skill():
    """The local fallback classifier returns a valid skill value."""
    classifier = LocalFallbackClassifier()
    result = classifier.classify(
        "skill", {"prompt": "build a website that looks like https://x.com"}
    )
    assert result["value"] == "webdev"
    assert "confidence" in result


def test_skill_criteria_matches_registry():
    """The skill decision's criteria keys match the skill registry."""
    criteria = DECISION_REGISTRY["skill"].criteria
    assert set(criteria.keys()) == set(SKILL_REGISTRY.keys())
