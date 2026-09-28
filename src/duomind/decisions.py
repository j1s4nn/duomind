"""Decision registry and question models for Jev integration."""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel
from typesafe_sdk import Choice, Noul, Score


class DecisionStage(str, Enum):
    """Decision point stage in the pipeline."""
    PRE = "pre"
    MID = "mid"
    POST = "post"


class QuestionKind(str, Enum):
    """Type of Jev question."""
    NOUL = "noul"
    CHOICE = "choice"
    SCORE = "score"


@dataclass
class DecisionPoint:
    """A decision point in the DuoMind pipeline."""
    name: str
    stage: DecisionStage
    kind: QuestionKind
    instructions: str
    criteria: Union[Dict[str, Optional[str]], List[str], Dict[str, str], None]
    threshold: float = 0.6
    fallback: Optional[str] = None


# Decision Registry: All classification decisions in DuoMind
DECISION_REGISTRY: Dict[str, DecisionPoint] = {
    # PRE stage: Before LLM generation
    "needs_generation": DecisionPoint(
        name="needs_generation",
        stage=DecisionStage.PRE,
        kind=QuestionKind.NOUL,
        instructions="Does this request require generating new text content?",
        criteria={
            "true": "Asks for explanation, code, analysis, creative content, or multi-step reasoning",
            "false": "Simple lookup, yes/no answer, or already has complete answer in context"
        },
        threshold=0.5,
        fallback="true",
    ),
    "needs_reasoning": DecisionPoint(
        name="needs_reasoning",
        stage=DecisionStage.PRE,
        kind=QuestionKind.NOUL,
        instructions="Does this request require multi-step logical reasoning?",
        criteria={
            "true": "Requires analysis, comparison, inference, or connecting multiple concepts",
            "false": "Direct factual recall or simple task execution"
        },
        threshold=0.6,
        fallback="true",
    ),
    "intent": DecisionPoint(
        name="intent",
        stage=DecisionStage.PRE,
        kind=QuestionKind.CHOICE,
        instructions="What is the primary intent of this request?",
        criteria={
            "question": "Asking for information, explanation, or clarification",
            "instruction": "Directing to perform a specific task or action",
            "conversation": "Casual chat, greeting, or social interaction",
            "code": "Requesting code writing, debugging, or technical implementation",
            "creative": "Asking for creative writing, storytelling, or artistic content"
        },
        threshold=0.5,
        fallback="question",
    ),
    "complexity": DecisionPoint(
        name="complexity",
        stage=DecisionStage.PRE,
        kind=QuestionKind.SCORE,
        instructions="Rate the complexity of this request",
        criteria=[
            "Simple: One-sentence answer, basic fact, or trivial task",
            "Moderate: Paragraph explanation, standard coding task, or multi-part question",
            "Complex: Detailed analysis, sophisticated implementation, or research-level reasoning"
        ],
        threshold=0.6,
        fallback="1",
    ),
    "ambiguity": DecisionPoint(
        name="ambiguity",
        stage=DecisionStage.PRE,
        kind=QuestionKind.SCORE,
        instructions="Rate how ambiguous or underspecified this request is",
        criteria=[
            "Clear: All necessary details provided, no interpretation needed",
            "Somewhat unclear: Missing some details but main intent is obvious",
            "Very ambiguous: Critical details missing, multiple interpretations possible"
        ],
        threshold=0.6,
        fallback="1",
    ),
    "safety": DecisionPoint(
        name="safety",
        stage=DecisionStage.PRE,
        kind=QuestionKind.NOUL,
        instructions="Is this request safe and appropriate to answer?",
        criteria={
            "true": "Request is appropriate, ethical, and within safe boundaries",
            "false": "Request involves harmful content, illegal activity, or dangerous information"
        },
        threshold=0.8,
        fallback="true",
    ),

    # MID stage: During generation (between reasoning steps)
    "on_track": DecisionPoint(
        name="on_track",
        stage=DecisionStage.MID,
        kind=QuestionKind.NOUL,
        instructions="Is the current reasoning on track to answer the original request?",
        criteria={
            "true": "Current direction is relevant and moving toward a complete answer",
            "false": "Reasoning has diverged, gone off-topic, or is circular"
        },
        threshold=0.6,
        fallback="true",
    ),
    "step_complete": DecisionPoint(
        name="step_complete",
        stage=DecisionStage.MID,
        kind=QuestionKind.NOUL,
        instructions="Is the current reasoning step complete and ready to move forward?",
        criteria={
            "true": "Current thought is finished and logically closed",
            "false": "Thought is incomplete, cut off mid-sentence, or needs more development"
        },
        threshold=0.7,
        fallback="true",
    ),
    "should_stop": DecisionPoint(
        name="should_stop",
        stage=DecisionStage.MID,
        kind=QuestionKind.NOUL,
        instructions="Should generation stop now because the answer is complete?",
        criteria={
            "true": "Request is fully answered, no additional content needed",
            "false": "More content needed to fully address the request"
        },
        threshold=0.7,
        fallback="false",
    ),
    "confidence_mid": DecisionPoint(
        name="confidence_mid",
        stage=DecisionStage.MID,
        kind=QuestionKind.SCORE,
        instructions="Rate confidence that the generated content so far is correct and useful",
        criteria=[
            "Low: Content contains errors, contradictions, or irrelevant information",
            "Medium: Content is mostly correct but has minor gaps or unclear points",
            "High: Content is accurate, coherent, and directly addresses the request"
        ],
        threshold=0.6,
        fallback="1",
    ),

    # POST stage: After generation
    "answer_complete": DecisionPoint(
        name="answer_complete",
        stage=DecisionStage.POST,
        kind=QuestionKind.NOUL,
        instructions="Does the generated answer fully address the original request?",
        criteria={
            "true": "All parts of the request are answered with sufficient detail",
            "false": "Answer is incomplete, missing key points, or cut off"
        },
        threshold=0.7,
        fallback="true",
    ),
    "matches_request": DecisionPoint(
        name="matches_request",
        stage=DecisionStage.POST,
        kind=QuestionKind.NOUL,
        instructions="Does the answer actually match what was requested?",
        criteria={
            "true": "Answer directly addresses the question or instruction given",
            "false": "Answer went off-topic, misunderstood the request, or answered something else"
        },
        threshold=0.7,
        fallback="true",
    ),
    "needs_retry": DecisionPoint(
        name="needs_retry",
        stage=DecisionStage.POST,
        kind=QuestionKind.NOUL,
        instructions="Should this request be retried with a different approach?",
        criteria={
            "true": "Answer has significant issues that warrant regeneration",
            "false": "Answer is acceptable even if not perfect"
        },
        threshold=0.6,
        fallback="false",
    ),
}


def get_decisions_for_stage(stage: DecisionStage) -> Dict[str, DecisionPoint]:
    """Get all decisions for a specific stage."""
    return {
        name: decision
        for name, decision in DECISION_REGISTRY.items()
        if decision.stage == stage
    }


def build_jev_question(decision: DecisionPoint) -> Union[Noul, Choice, Score]:
    """Build a Jev question object from a DecisionPoint."""
    if decision.kind == QuestionKind.NOUL:
        return Noul(
            instructions=decision.instructions,
            criteria=decision.criteria if decision.criteria else None,
        )
    elif decision.kind == QuestionKind.CHOICE:
        return Choice(
            instructions=decision.instructions,
            criteria=decision.criteria,
        )
    elif decision.kind == QuestionKind.SCORE:
        return Score(
            instructions=decision.instructions,
            criteria=decision.criteria,
        )
    else:
        raise ValueError(f"Unknown question kind: {decision.kind}")


class LocalFallbackClassifier:
    """Simple rule-based fallback classifier when Jev is unavailable or low confidence."""

    @staticmethod
    def classify(decision_name: str, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Provide fallback classification for a decision.

        Returns dict with 'value' and 'confidence' keys.
        """
        decision = DECISION_REGISTRY.get(decision_name)
        if not decision:
            return {"value": decision.fallback if decision else None, "confidence": 0.3}

        # Simple heuristics based on decision name
        if decision_name == "needs_generation":
            # Check if request is very short (likely yes/no)
            prompt_text = state.get("prompt", "")
            words = len(prompt_text.split())
            if words < 5:
                return {"value": False, "confidence": 0.5}
            return {"value": True, "confidence": 0.6}

        elif decision_name == "safety":
            # Keyword-based safety check
            prompt_text = state.get("prompt", "").lower()
            unsafe_keywords = ["hack", "exploit", "illegal", "harm", "weapon"]
            if any(kw in prompt_text for kw in unsafe_keywords):
                return {"value": False, "confidence": 0.7}
            return {"value": True, "confidence": 0.6}

        elif decision_name == "should_stop":
            # Check if generation has reached reasonable length
            current_text = state.get("generated", "")
            if len(current_text) > 1000:
                return {"value": True, "confidence": 0.6}
            return {"value": False, "confidence": 0.5}

        # Default to fallback value with low confidence
        fallback_value = decision.fallback
        if decision.kind == QuestionKind.NOUL:
            fallback_value = fallback_value == "true" if isinstance(fallback_value, str) else fallback_value
        elif decision.kind == QuestionKind.SCORE:
            fallback_value = float(fallback_value) if isinstance(fallback_value, str) else 1.0

        return {"value": fallback_value, "confidence": 0.4}
