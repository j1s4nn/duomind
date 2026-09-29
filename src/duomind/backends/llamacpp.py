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
import psutil

from duomind.backends.base import LLMBackend
from duomind.utils import get_llama_server_binary, get_llama_server_pid_file

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
        binary_path = get_llama_server_binary()
        if not binary_path.exists():
            raise FileNotFoundError(
                f"llama-server not found at {binary_path}. Run 'duomind setup' first."
            )

        # Clean up any orphaned llama-server before starting a fresh one
        self._kill_orphans()

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
            # Run in background without a console window
            create_no_window = 0x08000000
            create_new_process_group = 0x00000200
            self.process = subprocess.Popen(
                cmd,
                creationflags=create_no_window | create_new_process_group,
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
        pid_file = get_llama_server_pid_file()
        pid_file.write_text(str(self.process.pid))

        # Wait for server to be ready
        await self._wait_for_ready(timeout=300)
        logger.info(f"llama-server ready (PID {self.process.pid})")

    async def stop(self) -> None:
        """Stop llama-server process."""
        pid_file = get_llama_server_pid_file()

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
            async with httpx.AsyncClient(trust_env=False) as client:
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
            "stop": self._merge_stop(stop),
            "stream": stream,
            "cache_prompt": True,  # Enable prompt caching
        }

        async with httpx.AsyncClient(timeout=120.0, trust_env=False) as client:
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

        Qwen/Phi models use the ChatML template (``<|im_start|>`` /
        ``<|im_end|>``). Using the real special tokens -- instead of a plain
        "System:/User:/Assistant:" label -- lets the model emit its EOS token
        and stop instead of generating until ``n_predict``.
        """
        if self._is_chatml():
            parts = []
            for msg in messages:
                role = msg.get("role", "user")
                content = msg.get("content", "") or ""
                parts.append(f"<|im_start|>{role}\n{content}<|im_end|>")
            parts.append("<|im_start|>assistant\n")
            return "\n".join(parts)

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
            elif role == "tool":
                prompt_parts.append(f"Tool result: {content}")

        prompt_parts.append("Assistant:")

        return "\n\n".join(prompt_parts)

    def _is_chatml(self) -> bool:
        """Return True if the model uses the ChatML template (Qwen/Phi)."""
        name = str(self.model_path).lower()
        return "qwen" in name or "phi" in name

    def _default_stop_tokens(self) -> list[str]:
        """Stop tokens for the current model family."""
        if self._is_chatml():
            return ["<|im_end|>", "<|endoftext|>", "<|im_start|>"]
        return []

    def _merge_stop(self, stop: Optional[list[str]]) -> list[str]:
        """Merge caller-provided stop strings with the model's defaults."""
        merged = list(stop) if stop else []
        for token in self._default_stop_tokens():
            if token not in merged:
                merged.append(token)
        return merged

    def _kill_orphans(self) -> None:
        """Kill any lingering llama-server processes to avoid port conflicts."""
        for proc in psutil.process_iter(["name", "pid"]):
            try:
                name = (proc.info.get("name") or "").lower()
                if name.startswith("llama-server"):
                    logger.warning(f"Killing orphaned llama-server (PID {proc.info['pid']})")
                    proc.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

    async def _wait_for_ready(self, timeout: int = 300):
        """Wait for llama-server to be ready."""
        start = asyncio.get_event_loop().time()
        while True:
            if await self.health():
                return

            if asyncio.get_event_loop().time() - start > timeout:
                raise TimeoutError("llama-server did not start in time")

            await asyncio.sleep(0.5)
