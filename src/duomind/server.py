"""FastAPI server with OpenAI-compatible endpoints."""

import json
import logging
import time
import uuid
from typing import Any, AsyncIterator, Dict, List, Optional

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator

from duomind.backends import LlamaCppBackend, OllamaBackend
from duomind.config import config
from duomind.decisions import DecisionStage, get_decisions_for_stage
from duomind.jev_client import JevClient

logger = logging.getLogger(__name__)

app = FastAPI(title="DuoMind", version="0.1.0")

# Global state
backend: Optional[Any] = None
jev_client: Optional[JevClient] = None


class Message(BaseModel):
    role: str
    content: str

    @field_validator("content", mode="before")
    @classmethod
    def _coerce_content(cls, v: Any) -> str:
        """Accept OpenAI multimodal content arrays and flatten them to text."""
        if isinstance(v, str):
            return v
        if isinstance(v, list):
            parts = []
            for item in v:
                if isinstance(item, dict):
                    if item.get("type") == "text" or "text" in item:
                        parts.append(str(item.get("text", "")))
            return "\n".join(parts)
        return str(v)


class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[Message]
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = 512
    stream: Optional[bool] = False
    stop: Optional[List[str]] = None


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[Dict[str, Any]]
    usage: Optional[Dict[str, int]] = None


@app.on_event("startup")
async def startup():
    """Initialize backend and Jev client on startup."""
    global backend, jev_client

    cfg = config.load()

    # Initialize Jev client
    jev_key = config.get_jev_key()
    if jev_key and cfg.jev_enabled:
        jev_client = JevClient(
            api_key=jev_key,
            model=cfg.jev_model,
            base_url=cfg.jev_base_url,
            enabled=cfg.jev_enabled,
            confidence_threshold=cfg.confidence_threshold,
        )
        logger.info("Jev client initialized")
    else:
        logger.warning("Jev client not initialized (disabled or no API key)")

    # Initialize backend
    if cfg.llm_backend == "llamacpp":
        if not cfg.model_path:
            raise RuntimeError("No model path configured. Run 'duomind setup' first.")
        backend = LlamaCppBackend(model_path=cfg.model_path, n_ctx=cfg.context_size)
        await backend.start()
        logger.info(f"llama.cpp backend started with model {cfg.model_path}")
    elif cfg.llm_backend == "ollama":
        if not cfg.model_path:
            raise RuntimeError("No Ollama model configured.")
        backend = OllamaBackend(model_name=cfg.model_path)
        await backend.start()
        logger.info(f"Ollama backend started with model {cfg.model_path}")
    else:
        raise RuntimeError(f"Unknown backend: {cfg.llm_backend}")


@app.on_event("shutdown")
async def shutdown():
    """Clean up on shutdown."""
    global backend
    if backend:
        await backend.stop()


@app.get("/health")
async def health():
    """Health check endpoint."""
    if not backend:
        raise HTTPException(status_code=503, detail="Backend not initialized")

    is_healthy = await backend.health()
    if not is_healthy:
        raise HTTPException(status_code=503, detail="Backend not healthy")

    return {"status": "healthy"}


@app.get("/v1/models")
async def list_models():
    """List available models (OpenAI-compatible)."""
    cfg = config.load()
    return {
        "object": "list",
        "data": [
            {
                "id": cfg.model_path or "unknown",
                "object": "model",
                "created": int(time.time()),
                "owned_by": "duomind",
            }
        ],
    }


@app.get("/v1/duomind/stats")
async def get_stats():
    """Get DuoMind-specific stats."""
    cfg = config.load()

    stats = {
        "jev_enabled": cfg.jev_enabled,
        "backend": cfg.llm_backend,
        "model": cfg.model_path,
    }

    if jev_client:
        stats["jev_stats"] = jev_client.get_stats()

    return stats


@app.post("/v1/chat/completions")
async def chat_completions(
    request: ChatCompletionRequest,
    authorization: Optional[str] = Header(None),
):
    """OpenAI-compatible chat completions endpoint."""
    if not backend:
        raise HTTPException(status_code=503, detail="Backend not initialized")

    cfg = config.load()

    # Check API key if configured
    if cfg.api_key:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing or invalid authorization")
        token = authorization[7:]
        if token != cfg.api_key:
            raise HTTPException(status_code=401, detail="Invalid API key")

    # Build state for Jev
    state = {
        "messages": [msg.model_dump() for msg in request.messages],
        "prompt": request.messages[-1].content if request.messages else "",
    }

    # PRE stage decisions
    pre_decisions = {}
    jev_header = "off"
    decision_count = 0

    if jev_client and cfg.jev_enabled:
        pre_decision_points = get_decisions_for_stage(DecisionStage.PRE)
        pre_decisions = jev_client.ask_batch(state, pre_decision_points)
        jev_header = "on"
        decision_count = len(pre_decisions)

        logger.info(f"PRE decisions: {pre_decisions}")

        # Check if we need generation
        needs_gen = pre_decisions.get("needs_generation", {})
        if not needs_gen.get("value", True):
            # Simple response without LLM
            return ChatCompletionResponse(
                id=f"chatcmpl-{uuid.uuid4().hex[:12]}",
                created=int(time.time()),
                model=request.model,
                choices=[
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "I understand. No additional generation needed.",
                        },
                        "finish_reason": "stop",
                    }
                ],
            )

    # Encode messages to prompt
    prompt = await backend.encode_prompt([msg.model_dump() for msg in request.messages])

    # Generate
    if request.stream:
        return StreamingResponse(
            stream_completion(
                prompt,
                request,
                jev_header,
                decision_count,
            ),
            media_type="text/event-stream",
            headers={
                "X-DuoMind-Jev": jev_header,
                "X-DuoMind-Decisions": str(decision_count),
            },
        )
    else:
        # Non-streaming
        full_response = ""
        async for chunk in backend.generate(
            prompt=prompt,
            max_tokens=request.max_tokens or 512,
            temperature=request.temperature or 0.7,
            stop=request.stop,
            stream=False,
        ):
            full_response += chunk

        # POST stage decisions
        if jev_client and cfg.jev_enabled:
            post_state = {**state, "generated": full_response}
            post_decision_points = get_decisions_for_stage(DecisionStage.POST)
            post_decisions = jev_client.ask_batch(post_state, post_decision_points)
            decision_count += len(post_decisions)
            logger.info(f"POST decisions: {post_decisions}")

        response = ChatCompletionResponse(
            id=f"chatcmpl-{uuid.uuid4().hex[:12]}",
            created=int(time.time()),
            model=request.model,
            choices=[
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": full_response},
                    "finish_reason": "stop",
                }
            ],
        )

        return response


async def stream_completion(
    prompt: str,
    request: ChatCompletionRequest,
    jev_header: str,
    decision_count: int,
) -> AsyncIterator[str]:
    """Stream completion chunks in SSE format."""
    request_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"

    async for chunk in backend.generate(
        prompt=prompt,
        max_tokens=request.max_tokens or 512,
        temperature=request.temperature or 0.7,
        stop=request.stop,
        stream=True,
    ):
        chunk_data = {
            "id": request_id,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": request.model,
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": chunk},
                    "finish_reason": None,
                }
            ],
        }
        yield f"data: {json.dumps(chunk_data)}\n\n"

    # Final chunk
    final_chunk = {
        "id": request_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": request.model,
        "choices": [
            {
                "index": 0,
                "delta": {},
                "finish_reason": "stop",
            }
        ],
    }
    yield f"data: {json.dumps(final_chunk)}\n\n"
    yield "data: [DONE]\n\n"


if __name__ == "__main__":
    import uvicorn

    cfg = config.load()
    uvicorn.run(app, host=cfg.host, port=cfg.port)
