"""Jev client with caching, fallback, and circuit breaker."""

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, Optional

from typesafe_sdk import TypeSafeClient
from typesafe_sdk._core.retry import RetryPolicy

from duomind.decisions import (
    DECISION_REGISTRY,
    DecisionPoint,
    DecisionStage,
    LocalFallbackClassifier,
    QuestionKind,
    build_jev_question,
)
from duomind.utils import get_cache_dir, hash_state

logger = logging.getLogger(__name__)


class CircuitBreaker:
    """Circuit breaker for Jev API calls."""

    def __init__(self, failure_threshold: int = 3, timeout: int = 30):
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.failures = 0
        self.last_failure_time: Optional[float] = None
        self.state = "closed"  # closed, open, half_open

    def record_success(self):
        """Record successful call."""
        self.failures = 0
        self.state = "closed"

    def record_failure(self):
        """Record failed call."""
        self.failures += 1
        self.last_failure_time = time.time()

        if self.failures >= self.failure_threshold:
            self.state = "open"
            logger.warning(f"Circuit breaker OPEN after {self.failures} failures")

    def can_attempt(self) -> bool:
        """Check if we can attempt a call."""
        if self.state == "closed":
            return True

        if self.state == "open":
            # Check if timeout has elapsed
            if self.last_failure_time and (time.time() - self.last_failure_time) > self.timeout:
                self.state = "half_open"
                logger.info("Circuit breaker moving to HALF_OPEN")
                return True
            return False

        # half_open: allow one attempt
        return True


class JevCache:
    """SQLite-based cache for Jev decisions."""

    def __init__(self, cache_dir: Path, ttl: int = 3600):
        self.db_path = cache_dir / "jev_decisions.db"
        self.ttl = ttl
        self._init_db()

    def _init_db(self):
        """Initialize SQLite database."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS decisions (
                key TEXT PRIMARY KEY,
                response TEXT NOT NULL,
                timestamp REAL NOT NULL
            )
        """)
        conn.commit()
        conn.close()

    def get(self, state_hash: str, questions: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Get cached response if available and not expired."""
        # Create cache key from state hash + question names
        question_names = sorted(questions.keys())
        cache_key = f"{state_hash}:{':'.join(question_names)}"

        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute(
            "SELECT response, timestamp FROM decisions WHERE key = ?", (cache_key,)
        )
        row = cursor.fetchone()
        conn.close()

        if not row:
            return None

        response_json, timestamp = row
        if time.time() - timestamp > self.ttl:
            # Expired
            return None

        try:
            return json.loads(response_json)
        except json.JSONDecodeError:
            return None

    def set(self, state_hash: str, questions: Dict[str, Any], response: Dict[str, Any]):
        """Cache a response."""
        question_names = sorted(questions.keys())
        cache_key = f"{state_hash}:{':'.join(question_names)}"

        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT OR REPLACE INTO decisions (key, response, timestamp) VALUES (?, ?, ?)",
            (cache_key, json.dumps(response), time.time()),
        )
        conn.commit()
        conn.close()

    def clear_expired(self):
        """Clear expired entries."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("DELETE FROM decisions WHERE timestamp < ?", (time.time() - self.ttl,))
        conn.commit()
        conn.close()


class JevClient:
    """Wrapper around TypeSafe SDK with caching, fallback, and circuit breaker."""

    def __init__(
        self,
        api_key: str,
        model: str = "jev-latest",
        base_url: Optional[str] = None,
        enabled: bool = True,
        confidence_threshold: float = 0.6,
    ):
        self.enabled = enabled
        self.confidence_threshold = confidence_threshold
        self.cache = JevCache(get_cache_dir())
        self.circuit_breaker = CircuitBreaker()
        self.fallback_classifier = LocalFallbackClassifier()

        # Initialize TypeSafe client with retry policy
        retry_policy = RetryPolicy(
            max_retries=2,
            backoff_initial=0.5,
            backoff_max=5.0,
            timeout=30.0,
        )

        self.client = TypeSafeClient(
            api_key=api_key,
            model=model,
            base_url=base_url,
            retry=retry_policy,
        ) if enabled else None

        # Stats
        self.stats = {
            "total_calls": 0,
            "cache_hits": 0,
            "jev_calls": 0,
            "fallback_calls": 0,
            "circuit_breaker_trips": 0,
        }

    def ask_batch(
        self, state: Dict[str, Any], decisions: Dict[str, DecisionPoint]
    ) -> Dict[str, Dict[str, Any]]:
        """
        Ask multiple decisions in one batched call.

        Returns dict mapping decision name to result dict with:
        - 'value': The decision value (bool, str, float depending on type)
        - 'confidence': Confidence score 0-1
        - 'source': 'jev' | 'fallback' | 'cache'
        - 'latency_ms': Time taken
        """
        self.stats["total_calls"] += 1
        start_time = time.time()

        # Check cache
        state_hash = hash_state(state)
        cached = self.cache.get(state_hash, decisions)
        if cached:
            self.stats["cache_hits"] += 1
            logger.debug(f"Cache hit for {len(decisions)} decisions")
            return cached

        # Build Jev questions
        questions = {}
        for name, decision in decisions.items():
            questions[name] = build_jev_question(decision)

        # Check if Jev is enabled and circuit breaker allows
        if not self.enabled or not self.circuit_breaker.can_attempt():
            if not self.enabled:
                logger.debug("Jev disabled, using fallback")
            else:
                logger.warning("Circuit breaker open, using fallback")
                self.stats["circuit_breaker_trips"] += 1

            return self._fallback_batch(state, decisions, start_time)

        # Call Jev
        try:
            response = self.client.system_one(state=state, questions=questions)
            self.circuit_breaker.record_success()
            self.stats["jev_calls"] += 1

            # Process response
            results = {}
            for name, decision in decisions.items():
                answer = response.answers.get(name)
                if not answer:
                    # Missing answer, use fallback
                    fallback_result = self.fallback_classifier.classify(name, state)
                    results[name] = {
                        "value": fallback_result["value"],
                        "confidence": fallback_result["confidence"],
                        "source": "fallback",
                        "latency_ms": (time.time() - start_time) * 1000,
                    }
                    continue

                # Extract value and confidence based on question type
                if decision.kind == QuestionKind.NOUL:
                    value = answer.noul >= 0.5  # Convert probability to bool
                    confidence = answer.confidence
                elif decision.kind == QuestionKind.CHOICE:
                    value = answer.choice
                    confidence = answer.confidence
                elif decision.kind == QuestionKind.SCORE:
                    value = answer.score
                    confidence = answer.confidence
                else:
                    raise ValueError(f"Unknown question kind: {decision.kind}")

                # Check confidence threshold
                if confidence < self.confidence_threshold:
                    logger.debug(
                        f"Low confidence {confidence:.2f} for {name}, using fallback"
                    )
                    fallback_result = self.fallback_classifier.classify(name, state)
                    results[name] = {
                        "value": fallback_result["value"],
                        "confidence": fallback_result["confidence"],
                        "source": "fallback",
                        "latency_ms": (time.time() - start_time) * 1000,
                    }
                else:
                    results[name] = {
                        "value": value,
                        "confidence": confidence,
                        "source": "jev",
                        "latency_ms": (time.time() - start_time) * 1000,
                    }

                logger.debug(
                    f"Decision {name}: {results[name]['value']} "
                    f"(confidence={results[name]['confidence']:.2f}, "
                    f"source={results[name]['source']})"
                )

            # Cache results
            self.cache.set(state_hash, decisions, results)

            return results

        except Exception as e:
            logger.error(f"Jev call failed: {e}")
            self.circuit_breaker.record_failure()
            return self._fallback_batch(state, decisions, start_time)

    def _fallback_batch(
        self, state: Dict[str, Any], decisions: Dict[str, DecisionPoint], start_time: float
    ) -> Dict[str, Dict[str, Any]]:
        """Use fallback classifier for all decisions."""
        self.stats["fallback_calls"] += 1
        results = {}

        for name, decision in decisions.items():
            fallback_result = self.fallback_classifier.classify(name, state)
            results[name] = {
                "value": fallback_result["value"],
                "confidence": fallback_result["confidence"],
                "source": "fallback",
                "latency_ms": (time.time() - start_time) * 1000,
            }

        return results

    def get_stats(self) -> Dict[str, Any]:
        """Get usage statistics."""
        return {
            **self.stats,
            "cache_hit_rate": (
                self.stats["cache_hits"] / self.stats["total_calls"]
                if self.stats["total_calls"] > 0
                else 0.0
            ),
        }
