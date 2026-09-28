"""llama.cpp backend implementation."""

import asyncio
import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import AsyncIterator, Dict, Optional

import httpx

from duomind.backends.base import LLMBackend
from duomind.utils import get_binaries_dir, get_pid_file

logger = logging.getLogger(__name__)


class LlamaCppBackend(LLMBackend):
    """llama.cpp backend using llama-server."""

    def __init__(
        self,
        model_path: Path,
        host: str = "127.0.0.1",
        port: int = 8080,
        n_ctx: int = 4096,
        n_gpu_layers: int = -1,  # -1 = all layers on GPU
    ):
        self.model_path = model_path
        self.host = host
        self.port = port
        self.n_ctx = n_ctx
        self.n_gpu_layers = n_gpu_layers
        self.process: Optional[subprocess.Popen] = None
        self.base_url = f"http://{host}:{port}"

    async def start(self) -> None:
        """Start llama-server process."""
        if self.process:
            logger.warning("llama-server already running")
            return

        # Find llama-server binary
        binary_path = get_binaries_dir() / "llama-server.exe"
        if not binary_path.exists():
            raise FileNotFoundError(
                f"llama-server not found at {binary_path}. Run 'duomind setup' first."
            )

        # Build command
        cmd = [
            str(binary_path),
            "-m", str(self.model_path),
            "--host", self.host,
            "--port", str(self.port),
            "-c", str(self.n_ctx),
            "-ngl", str(self.n_gpu_layers),
            "--log-disable",  # Disable verbose logging
        ]

        logger.info(f"Starting llama-server: {' '.join(cmd)}")

        # Start process (detached on Windows)
        if sys.platform == "win32":
            # Detached process on Windows
            DETACHED_PROCESS = 0x00000008
            CREATE_NEW_PROCESS_GROUP = 0x00000200
            self.process = subprocess.Popen(
                cmd,
                creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )

        # Write PID file
        pid_file = get_pid_file()
        pid_file.write_text(str(self.process.pid))

        # Wait for server to be ready
        await self._wait_for_ready(timeout=30)
        logger.info(f"llama-server ready (PID {self.process.pid})")

    async def stop(self) -> None:
        """Stop llama-server process."""
        pid_file = get_pid_file()

        if self.process:
            logger.info(f"Stopping llama-server (PID {self.process.pid})")
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.process = None

        # Also try to kill by PID file
        if pid_file.exists():
            try:
                pid = int(pid_file.read_text())
                if sys.platform == "win32":
                    os.system(f"taskkill /F /PID {pid} >nul 2>&1")
                else:
                    os.kill(pid, 15)  # SIGTERM
            except Exception:
                pass
            pid_file.unlink()

    async def health(self) -> bool:
        """Check if llama-server is responding."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self.base_url}/health", timeout=2.0)
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
        """Generate text using llama.cpp."""
        payload = {
            "prompt": prompt,
            "n_predict": max_tokens,
            "temperature": temperature,
            "stop": stop or [],
            "stream": stream,
            "cache_prompt": True,  # Enable prompt caching
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            if stream:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/completion",
                    json=payload,
                ) as response:
                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            data_str = line[6:]
                            if data_str == "[DONE]":
                                break
                            try:
                                data = json.loads(data_str)
                                content = data.get("content", "")
                                if content:
                                    yield content
                            except json.JSONDecodeError:
                                continue
            else:
                response = await client.post(
                    f"{self.base_url}/completion",
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
                yield data.get("content", "")

    async def encode_prompt(self, messages: list[Dict]) -> str:
        """
        Encode chat messages into a prompt string.

        Uses a simple format:
        System: {system}
        User: {user}
        Assistant: {assistant}
        """
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

        # Add final assistant prompt
        prompt_parts.append("Assistant:")

        return "\n\n".join(prompt_parts)

    async def _wait_for_ready(self, timeout: int = 30):
        """Wait for llama-server to be ready."""
        start = asyncio.get_event_loop().time()
        while True:
            if await self.health():
                return

            if asyncio.get_event_loop().time() - start > timeout:
                raise TimeoutError("llama-server did not start in time")

            await asyncio.sleep(0.5)
