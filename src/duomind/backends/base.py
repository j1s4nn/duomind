"""Backend interface for LLM inference."""

from abc import ABC, abstractmethod
from typing import AsyncIterator, Dict, Optional


class LLMBackend(ABC):
    """Abstract base class for LLM backends."""

    @abstractmethod
    async def start(self) -> None:
        """Start the backend service."""
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Stop the backend service."""
        pass

    @abstractmethod
    async def health(self) -> bool:
        """Check if backend is healthy."""
        pass

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        max_tokens: int = 512,
        temperature: float = 0.7,
        stop: Optional[list[str]] = None,
        stream: bool = False,
    ) -> AsyncIterator[str]:
        """
        Generate text from prompt.

        Args:
            prompt: Input prompt
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            stop: Stop sequences
            stream: Whether to stream tokens

        Yields:
            Generated text chunks if stream=True, else single response
        """
        pass

    @abstractmethod
    async def encode_prompt(self, messages: list[Dict]) -> str:
        """Encode chat messages into a prompt string."""
        pass
