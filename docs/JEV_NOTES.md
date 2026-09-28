# Jev Integration Notes

**Source**: Context7 documentation and TypeSafe SDK research (2026-09-28)

## Package and Installation

- **SDK Package**: `typesafe-sdk`
- **Installation**: `pip install typesafe-sdk` or `uv add typesafe-sdk`
- **Import**: `from typesafe_sdk import TypeSafeClient, Noul, Choice, Score`

## Authentication

- **API Key**: Required for all requests
- **Methods**:
  1. Environment variable: `TYPESAFE_API_KEY`
  2. Constructor parameter: `TypeSafeClient(api_key="your-key")`
- **Base URL**: Configurable via constructor, defaults to TypeSafe's production API
- **Key Storage**: DuoMind uses Windows Credential Manager via `keyring` library

## Three Question Types

### 1. Noul (Yes/No)

**Purpose**: Binary classification with probability

**Request**:
```python
Noul(
    instructions="Does this request require generating new text?",
    criteria={
        "true": "Asks for explanation, analysis, or creative content",
        "false": "Simple lookup or yes/no answer"
    }
)
```

**Response**:
- `answer.noul`: Float 0-1 (probability of "true")
- `answer.confidence`: Float 0-1 (confidence in the answer)
- Convert to bool: `answer.noul >= 0.5`

### 2. Choice (Pick One)

**Purpose**: Select one option from a list

**Request**:
```python
Choice(
    instructions="What is the primary intent of this request?",
    criteria={
        "question": "Asking for information or explanation",
        "instruction": "Directing to perform a task",
        "conversation": "Casual chat or greeting"
    }
)
```

**Response**:
- `answer.choice`: String (selected label from criteria keys)
- `answer.confidence`: Float 0-1
- `answer.probabilities`: Dict mapping each label to its probability

### 3. Score (Rating)

**Purpose**: Numeric rating on a scale

**Request**:
```python
Score(
    instructions="Rate the complexity of this request",
    criteria=[
        "Simple: One-sentence answer or trivial task",
        "Moderate: Paragraph explanation or standard task",
        "Complex: Detailed analysis or sophisticated implementation"
    ]
)
```

**Response**:
- `answer.score`: Float (the assigned score, e.g., 0, 1, 2 for 3 levels)
- `answer.confidence`: Float 0-1
- `answer.legend`: Dict mapping score values to their text descriptions
- `answer.probabilities`: Dict mapping score values to probabilities

## Batching

**All questions in one call**:

```python
response = client.system_one(
    state={
        "messages": [...],
        "prompt": "What is AI?"
    },
    questions={
        "needs_gen": Noul(instructions="Needs generation?"),
        "intent": Choice(instructions="What intent?", criteria={...}),
        "complexity": Score(instructions="How complex?", criteria=[...])
    }
)

# Access answers
needs_gen = response.answers["needs_gen"]
intent = response.answers["intent"]
complexity = response.answers["complexity"]

# Filtered by type
for name, answer in response.nouls.items():
    print(f"{name}: {answer.noul >= 0.5}")
```

## Pricing and Limits

- **Input tokens**: Metered (cheap but NOT free, ~$0.15/M tokens as of early 2026)
- **Output tokens**: Free
- **Latency**: 70-500ms typical
- **Early access**: Limits and pricing may change without notice
- **Rate limits**: Not documented, but SDK has built-in retry

## SDK Retry Policy

**Built-in retry handling**:

```python
RetryPolicy(
    max_retries=2,
    backoff_initial=0.5,      # 500ms first retry
    backoff_max=5.0,          # 5s max wait
    timeout=30.0,             # 30s total budget
    jitter=0.25               # ±25% randomization
)
```

**Retries on**:
- HTTP 408 (timeout), 429 (rate limit), 5xx (server error)
- Connection errors
- Timeouts

**Respects**: `Retry-After` header

**DuoMind adds**: Circuit breaker on top (3 failures → open → 30s timeout → half-open)

## Known Behavior and Design Constraints

### 1. No Rationale
- Jev returns only numbers (probabilities, confidence)
- No explanation of *why* it chose that answer
- Cannot debug "wrong" classifications by reading reasoning

### 2. Question and Negation
- Asking "Is X true?" and "Is X false?" may not sum to 1.0
- **Best practice**: Ask each decision ONE way, in the positive direction
- Example: Ask "Needs generation?" not "Doesn't need generation?"

### 3. Yes/No vs Choice Scores Not Comparable
- A 0.9 Noul probability ≠ a 0.9 confidence on a Choice
- Different question types use different internal calibration
- **Don't compare** across types

### 4. Contradictory Question and Criteria
- If `instructions` and `criteria` conflict, answer quality degrades
- **Write criteria as an extension of the question**, not a contradiction
- Bad: "Is this safe?" with criteria "unsafe content types"
- Good: "Is this safe?" with criteria "true = safe, false = unsafe"

### 5. Text in State Steers Answers
- Jev reads the `state` dict; text inside can influence classification
- **Pair with deterministic checks** (regex, keyword lists) for critical decisions
- Don't rely on Jev alone for safety filtering

### 6. Score Question Design
- Each level in `criteria` list is evaluated separately
- Avoid "worse than previous" or relative language
- Use concrete descriptions: "broken but workaround exists" > "moderately severe"
- **One dimension per Score**: Don't mix complexity and urgency in one question

## Model Parameter

- Default: `jev-latest` (tracks latest production model)
- Tutorial mentions: `jev-1.13` (specific version)
- Pass via constructor: `TypeSafeClient(model="jev-1.13")`
- DuoMind default: `jev-latest` (configurable in config.toml)

## Error Handling

**SDK throws exceptions**:
- `httpx.HTTPStatusError`: 4xx/5xx responses after retries exhausted
- `httpx.TimeoutException`: Request timed out
- `httpx.ConnectError`: Cannot connect to API

**DuoMind handling**:
1. Circuit breaker records failure
2. Falls back to local classifier
3. Logs error but never fails the request
4. After 3 failures in 60s, circuit opens (fallback only for 30s)

## Caching Strategy

**DuoMind implements**:
- SHA256 hash of `state` dict
- Cache key = `state_hash:question_names`
- SQLite storage in `%LOCALAPPDATA%\duomind\cache\jev_decisions.db`
- TTL: 1 hour
- Hit rate tracked in stats

**Why cache**:
- Jev input tokens are metered
- Identical state + questions = identical answer
- Reduces latency for repeated requests

## Confidence Gating

**Threshold** (default 0.6):
- `confidence >= threshold`: Use Jev answer
- `confidence < threshold`: Fall back to local classifier

**Per-decision thresholds** in `DECISION_REGISTRY`:
- Safety: 0.8 (require high confidence)
- Most others: 0.6 (balanced)
- Intent: 0.5 (accept lower confidence for multiple choice)

## Integration Points in DuoMind

1. **PRE stage** (before LLM generation):
   - All PRE decisions batched into one Jev call
   - Includes: needs_generation, needs_reasoning, intent, complexity, safety

2. **MID stage** (during generation, optional):
   - Up to `max_mid_checkpoints` calls (default 3)
   - Decisions: on_track, step_complete, should_stop, confidence_mid
   - Only if prompt is complex enough to warrant checkpoints

3. **POST stage** (after generation):
   - One batched call
   - Decisions: answer_complete, matches_request, needs_retry

## Observed Behavior

**From Context7 examples**:
- Jev handles ambiguous prompts well (distinguishes "write code" from "explain code")
- Good at intent classification (question vs instruction vs conversation)
- Confidence scores are well-calibrated (low confidence → actually uncertain)
- Fast enough for interactive use (< 500ms in examples)

## Official Resources

- **Product page**: https://typesafe.ai
- **Documentation**: https://docs.typesafe.ai
- **API Console**: https://console.typesafe.ai (get keys here)
- **SDK**: https://github.com/typesafehq/typesafe-python (if public)

## DuoMind-Specific Notes

- **Jev toggle**: `duomind jev on|off|status` persists to config
- **Stats endpoint**: `/v1/duomind/stats` shows Jev usage
- **Headers**: Every response includes `X-DuoMind-Jev: on|off` and `X-DuoMind-Decisions: N`
- **Logs**: Per-decision: name, value, confidence, source (jev|fallback|cache), latency
- **No prompt text logged** to avoid leaking user data

## Version Tracking

- **Context7 research date**: 2026-09-28
- **SDK version used**: `typesafe-sdk>=0.2.0` (in pyproject.toml)
- **Jev model**: `jev-latest` (configurable)
- **Future updates**: Check docs.typesafe.ai for API changes
