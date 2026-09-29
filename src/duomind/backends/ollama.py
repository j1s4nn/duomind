"""Ollama backend implementation (optional)."""

import json
import logging
from typing import AsyncIterator, Dict, Optional

import httpx

from duomind.backends.base import LLMBackend

logger = logging.getLogger(__name__)


class OllamaBackend(LLMBackend):
    """Ollama backend (user must have Ollama installed)."""

    def __init__(
        self,
        model_name: str,
        base_url: str = "http://localhost:11434",
    ):
        self.model_name = model_name
        self.base_url = base_url

    async def start(self) -> None:
        """Ollama is managed externally, just check if it's running."""
        if not await self.health():
            raise RuntimeError(
                "Ollama is not running. Please start Ollama first: https://ollama.ai"
            )
        logger.info(f"Connected to Ollama at {self.base_url}")

    async def stop(self) -> None:
        """Ollama is managed externally, nothing to stop."""
        pass

    async def health(self) -> bool:
        """Check if Ollama is responding."""
        try:
            async with httpx.AsyncClient(trust_env=False) as client:
                response = await client.get(f"{self.base_url}/api/tags", timeout=2.0)
                return response.status_code == 200
        except Exception:
            return False

    async def generate(
        self,
        prompt: str,
        max_tokens: int = 512,
        temperature: float = 0.7,
        stop: Optional[list[str]] = None,
        stream: bool = False,
    ) -> AsyncIterator[str]:
        """Generate text using Ollama."""
        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "stream": stream,
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
                "stop": stop or [],
            },
        }

        async with httpx.AsyncClient(timeout=120.0, trust_env=False) as client:
            if stream:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/api/generate",
                    json=payload,
                ) as response:
                    async for line in response.aiter_lines():
                        try:
                            data = json.loads(line)
                            content = data.get("response", "")
                            if content:
                                yield content
                            if data.get("done"):
                                break
                        except json.JSONDecodeError:
                            continue
            else:
                response = await client.post(
                    f"{self.base_url}/api/generate",
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
                yield data.get("response", "")

    async def encode_prompt(self, messages: list[Dict]) -> str:
        """Encode chat messages into a prompt string."""
        # Same format as llama.cpp
        prompt_parts = []

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "system":
                prompt_parts.append(f"System: {content}")
            elif role == "user":
                prompt_parts.append(f"User: {content}")
            elif role == "assistant":
                prompt_parts.append(f"Assistant: {content}")

        prompt_parts.append("Assistant:")

        return "\n\n".join(prompt_parts)
