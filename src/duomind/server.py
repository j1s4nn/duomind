"""FastAPI server with OpenAI-compatible endpoints.

Pipeline (dual-system): Jev classifies before, during, and after generation;
the local LLM only writes. The steering skill (``duomind.skill``) translates
Jev's decisions into plain imperative instructions the LLM obeys in
milliseconds.
"""

import json
import logging
import re
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, List, Optional

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, field_validator

from duomind.backends import LlamaCppBackend, OllamaBackend
from duomind.config import config
from duomind.decisions import (
    DecisionPoint,
    DecisionStage,
    get_decisions_for_stage,
    verbosity_label,
)
from duomind.jev_client import JevClient
from duomind.skill import DEFAULT_SYSTEM_PROMPT, build_steering_directive
from duomind.skills import SKILL_REGISTRY, get_skill_instructions, select_skill

logger = logging.getLogger(__name__)

# Ensure DuoMind log messages (token counts, speeds, decisions) reach the
# server log. Uvicorn configures only its own loggers; without this, our
# logger.info() lines below WARNING would be dropped.
_duomind_logger = logging.getLogger("duomind")
if not _duomind_logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    _duomind_logger.addHandler(_handler)
_duomind_logger.setLevel(logging.INFO)
_duomind_logger.propagate = False

# Global state
backend: Optional[Any] = None
jev_client: Optional[JevClient] = None
_jev_missing_key_logged = False


def _ensure_jev_client(cfg: Any) -> Optional[JevClient]:
    """Return a Jev client, (re)initializing it to match the current config.

    The benchmark (and ``duomind jev on``) toggle Jev by editing ``config.toml``.
    Re-initializing here -- instead of only at startup -- means those toggles
    take effect without a server restart.
    """
    global jev_client, _jev_missing_key_logged

    if not cfg.jev_enabled:
        jev_client = None
        return None

    if jev_client is not None and jev_client.enabled:
        return jev_client

    jev_key = config.get_jev_key()
    if not jev_key:
        if not _jev_missing_key_logged:
            logger.warning("Jev enabled but no API key found; using fallback")
            _jev_missing_key_logged = True
        jev_client = None
        return None

    jev_client = JevClient(
        api_key=jev_key,
        model=cfg.jev_model,
        base_url=cfg.jev_base_url,
        enabled=True,
        confidence_threshold=cfg.confidence_threshold,
    )
    logger.info("Jev client initialized")
    return jev_client


class Message(BaseModel):
    role: str
    content: Optional[str] = None

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
        if v is None:
            return ""
        return str(v)


class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[Message]
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = 512
    stream: Optional[bool] = False
    stop: Optional[List[str]] = None
    tools: Optional[List[Dict[str, Any]]] = None
    tool_choice: Optional[Any] = None


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[Dict[str, Any]]
    usage: Optional[Dict[str, int]] = None


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


async def shutdown():
    """Clean up on shutdown."""
    global backend
    if backend:
        await backend.stop()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Run startup/shutdown around the application lifecycle."""
    await startup()
    yield
    await shutdown()


app = FastAPI(title="DuoMind", version="0.2.0", lifespan=lifespan)


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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TOOL_CALL_RE = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL)


def _approx_tokens(text: str) -> int:
    """Rough token estimate (4 chars/token)."""
    return len(text) // 4


_MAX_STATE_GENERATED_CHARS = 2000


def _compact_jev_state(state: Dict[str, Any], generated: Optional[str] = None) -> Dict[str, Any]:
    """Build a minimal Jev state to keep input-token cost low.

    Jev bills input tokens, so we send only the prompt for PRE decisions and a
    truncated tail of the generated text for MID/POST decisions -- never the
    full message history or the entire answer.
    """
    prompt = state.get("prompt", "") if isinstance(state, dict) else ""
    if generated is None:
        return {"prompt": prompt}
    tail = generated[-_MAX_STATE_GENERATED_CHARS:] if generated else ""
    return {"prompt": prompt, "generated": tail}


def _duomind_headers(
    jev_on: bool,
    decisions: int,
    jev_tokens: int,
    jev_seconds: float,
    llm_seconds: float,
) -> Dict[str, str]:
    """Headers reporting Jev/LLM usage so benchmarks can compare modes honestly."""
    return {
        "X-DuoMind-Jev": "on" if jev_on else "off",
        "X-DuoMind-Decisions": str(decisions),
        "X-DuoMind-Jev-Tokens": str(int(jev_tokens)),
        "X-DuoMind-Jev-Seconds": f"{jev_seconds:.3f}",
        "X-DuoMind-Llm-Seconds": f"{llm_seconds:.3f}",
    }


def _json_response(payload: ChatCompletionResponse, headers: Dict[str, str]) -> JSONResponse:
    """Serialize a chat completion response with the DuoMind usage headers."""
    return JSONResponse(content=payload.model_dump(), headers=headers)


def _log_performance(
    jev_on: bool,
    decision_count: int,
    prompt_tokens: int,
    completion_tokens: int,
    llm_seconds: float,
    jev_tokens: int,
    jev_seconds: float,
    total_seconds: float,
) -> None:
    """Log token counts and speed for the LLM and Jev for one request."""
    llm_tok_s = completion_tokens / llm_seconds if llm_seconds > 0 else 0.0
    jev_tok_s = jev_tokens / jev_seconds if jev_seconds > 0 else 0.0
    logger.info(
        "PERF jev=%s decisions=%d prompt_tokens=%d completion_tokens=%d "
        "llm=%.2fs %.1f tok/s jev_tokens=%d jev=%.3fs %.1f tok/s total=%.2fs",
        "on" if jev_on else "off",
        decision_count,
        prompt_tokens,
        completion_tokens,
        llm_seconds,
        llm_tok_s,
        jev_tokens,
        jev_seconds,
        jev_tok_s,
        total_seconds,
    )


def _extract_tool_call(text: str) -> Optional[Dict[str, Any]]:
    """Parse a <tool_call>...</tool_call> JSON block from model output."""
    match = _TOOL_CALL_RE.search(text)
    if not match:
        return None
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or "name" not in payload:
        return None
    arguments = payload.get("arguments", {})
    if isinstance(arguments, dict):
        arguments = json.dumps(arguments)
    return {"name": str(payload["name"]), "arguments": str(arguments)}


# Agent front-ends (e.g. coding agents) send full JSON schemas for every tool,
# which can exceed the model's context window on their own. Cap the tool block
# and each schema so the prompt can always fit; the model only needs names,
# descriptions, and a rough idea of each argument, not the complete schema.
_MAX_TOOL_BLOCK_CHARS = 12_000
_MAX_TOOL_SCHEMA_CHARS = 2_000


def _tool_prompt(
    tools: Optional[List[Dict[str, Any]]],
    max_chars: int = _MAX_TOOL_BLOCK_CHARS,
) -> str:
    """Describe available tools and the exact tool-call format.

    The block is capped at ``max_chars`` and each argument schema at
    ``_MAX_TOOL_SCHEMA_CHARS`` so a large tool list cannot overflow the
    context window.
    """
    if not tools:
        return ""
    header = [
        "You have access to tools. To use one, reply with EXACTLY this format "
        "and nothing else:",
        "",
        "<tool_call>",
        '{"name": "<tool_name>", "arguments": { ... }}',
        "</tool_call>",
        "",
        "Available tools:",
    ]
    lines = list(header)
    budget = max_chars - len("\n".join(lines))

    for tool in tools:
        fn = tool.get("function", {})
        name = fn.get("name", "unknown")
        desc = fn.get("description", "")
        params = fn.get("parameters", {})
        line = f"- {name}: {desc}"
        if params:
            schema = json.dumps(params)
            if len(schema) > _MAX_TOOL_SCHEMA_CHARS:
                schema = schema[:_MAX_TOOL_SCHEMA_CHARS] + "..."
            line += f"\n  arguments schema: {schema}"
        if len(line) + 1 > budget:
            lines.append("- (remaining tools omitted)")
            break
        lines.append(line)
        budget -= len(line) + 1
    return "\n".join(lines)


def _tool_choice_required(tool_choice: Any) -> Optional[str]:
    """Return a forced function name, or a sentinel for 'required'."""
    if tool_choice is None or tool_choice == "auto":
        return None
    if tool_choice == "required":
        return "__required__"
    if isinstance(tool_choice, dict):
        fn = tool_choice.get("function", {})
        if isinstance(fn, dict) and fn.get("name"):
            return str(fn["name"])
        if tool_choice.get("type") == "function":
            return "__required__"
    return None


def _short_reply(prompt: str) -> Optional[str]:
    """Return a canned reply for greetings/thanks, or None.

    Returns None when the message cannot be answered locally, so the caller
    routes it to the LLM instead of stubbing it with "Understood.".
    """
    p = prompt.strip().lower()
    if any(g in p for g in ["hello", " hi", "hey", "good morning", "good afternoon", "good evening"]):
        return "Hello! How can I help you today?"
    if any(g in p for g in ["thanks", "thank you"]):
        return "You're welcome!"
    return None


def _trim_messages_to_context(
    messages: List[Message],
    context_size: int,
    response_max_tokens: int,
    overhead_tokens: int = 0,
) -> List[Message]:
    """Drop the oldest messages so the encoded prompt fits the context window.

    The local model has a fixed context (``config.context_size``). Agent
    front-ends routinely send tens of thousands of tokens of system prompt and
    history, which overflows the window and makes the backend return nothing
    (or a 400). We keep the system message and the most recent messages --
    including the current request -- and drop the oldest, reserving room for
    the fixed system/steering/tool prompt (``overhead_tokens``) that
    ``_build_llm_messages`` prepends, plus the generated response.
    """
    if not messages:
        return messages

    # Reserve tokens for the response plus the fixed system/steering/tool
    # prompt prepended after trimming. 4 chars/token matches _approx_tokens.
    reserve_tokens = response_max_tokens + overhead_tokens
    budget_chars = max(1024, context_size - reserve_tokens) * 4

    system = messages[0] if messages[0].role == "system" else None
    tail = messages[1:] if system else messages

    if not tail:
        return messages

    last = tail[-1]
    recent: List[Message] = [last]
    total = len(last.content or "")

    for msg in reversed(tail[:-1]):
        size = len(msg.content or "")
        if total + size > budget_chars:
            break
        recent.append(msg)
        total += size
    recent.reverse()

    if system:
        remaining = budget_chars - total
        sys_content = system.content or ""
        if remaining > 0:
            if len(sys_content) > remaining:
                sys_content = sys_content[:remaining]
            return [Message(role="system", content=sys_content)] + recent

    return recent


def _resolve_skill(pre_decisions: Dict[str, Dict[str, Any]], state: Dict[str, Any], jev_active: bool) -> str:
    """Pick the active skill from Jev's decision or local keyword matching."""
    if jev_active:
        name = pre_decisions.get("skill", {}).get("value", "general")
    else:
        name = select_skill(state)
    if name not in SKILL_REGISTRY:
        return "general"
    return str(name)


def _build_system_content(
    steering_directive: str,
    tools: Optional[List[Dict[str, Any]]],
    tool_choice: Any,
    system_prompt: Optional[str],
    skill_name: str = "general",
) -> str:
    """Build the full system prompt (steering skill, active skill, directive, tools)."""
    skill = system_prompt or DEFAULT_SYSTEM_PROMPT

    skill_instructions = get_skill_instructions(skill_name)
    if skill_instructions:
        skill = f"{skill}\n\n[Active skill: {skill_name}]\n{skill_instructions}"

    if steering_directive:
        skill = f"{skill}\n\nSteering directive: {steering_directive}"

    forced = _tool_choice_required(tool_choice)
    tool_block = _tool_prompt(tools)
    if tool_block:
        skill = f"{skill}\n\n{tool_block}"
        if forced == "__required__":
            skill = (
                f"{skill}\n\nYou MUST call one of the available tools now. "
                "Reply only with the tool-call format."
            )
        elif forced:
            skill = (
                f"{skill}\n\nYou MUST call the tool named \"{forced}\" now. "
                "Reply only with the tool-call format."
            )

    return skill


def _build_llm_messages(
    messages: List[Message],
    steering_directive: str,
    tools: Optional[List[Dict[str, Any]]],
    tool_choice: Any,
    system_prompt: Optional[str],
    skill_name: str = "general",
) -> List[Dict[str, str]]:
    """Assemble messages with the steering skill, active skill, directive, and tools."""
    skill = _build_system_content(
        steering_directive, tools, tool_choice, system_prompt, skill_name
    )
    out: List[Dict[str, str]] = [{"role": "system", "content": skill}]
    for msg in messages:
        out.append({"role": msg.role, "content": msg.content or ""})
    return out


async def _generate_segmented(
    prompt: str,
    request: ChatCompletionRequest,
    mid_decision_points: Dict[str, DecisionPoint],
    state: Dict[str, Any],
    jev: Optional[JevClient] = None,
) -> tuple[str, int, float, int]:
    """Generate text in segments, running Jev MID decisions between each."""
    cfg = config.load()
    max_tokens = request.max_tokens or 512
    max_checkpoints = max(cfg.max_mid_checkpoints, 1)
    segment_size = max(cfg.mid_segment_tokens, 32)
    temperature = request.temperature or 0.7

    generated = ""
    mid_decision_count = 0
    jev_seconds = 0.0
    jev_tokens = 0

    for _ in range(max_checkpoints):
        remaining = max_tokens - _approx_tokens(generated)
        if remaining <= 0:
            break
        seg_tokens = min(segment_size, remaining)

        segment = ""
        async for chunk in backend.generate(
            prompt=prompt + generated,
            max_tokens=seg_tokens,
            temperature=temperature,
            stop=request.stop,
            stream=False,
        ):
            segment += chunk

        if not segment.strip():
            break

        generated += segment

        if _approx_tokens(generated) >= max_tokens:
            break

        if jev and cfg.jev_enabled:
            mid_state = _compact_jev_state(state, generated)
            _t = time.time()
            mid_results = jev.ask_batch(mid_state, mid_decision_points)
            jev_seconds += time.time() - _t
            jev_tokens += _approx_tokens(json.dumps(mid_state))
            mid_decision_count += len(mid_results)
            logger.info(f"MID decisions: {mid_results}")

            if mid_results.get("should_stop", {}).get("value", False):
                break
            if not mid_results.get("on_track", {}).get("value", True):
                break

    return generated, mid_decision_count, jev_seconds, jev_tokens


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

    last_content = request.messages[-1].content if request.messages else ""
    state = {"prompt": last_content}

    request_start = time.time()
    jev_header = "off"
    decision_count = 0
    jev_seconds = 0.0
    jev_tokens = 0
    llm_seconds = 0.0
    pre_decisions: Dict[str, Dict[str, Any]] = {}

    active_jev = _ensure_jev_client(cfg)
    if active_jev:
        pre_decision_points = get_decisions_for_stage(DecisionStage.PRE)
        pre_state = _compact_jev_state(state)
        _t = time.time()
        pre_decisions = active_jev.ask_batch(pre_state, pre_decision_points)
        jev_seconds += time.time() - _t
        jev_tokens += _approx_tokens(json.dumps(pre_state))
        jev_header = "on"
        decision_count = len(pre_decisions)
        logger.info(f"PRE decisions: {pre_decisions}")

    # --- Route on PRE decisions -------------------------------------------
    needs_gen = pre_decisions.get("needs_generation", {}).get("value", True)
    safety_ok = pre_decisions.get("safety", {}).get("value", True)

    if not safety_ok:
        content = "I can't help with that."
        _log_performance(
            jev_header == "on", decision_count, 0, _approx_tokens(content),
            0.0, jev_tokens, jev_seconds, time.time() - request_start,
        )
        return _json_response(
            ChatCompletionResponse(
                id=f"chatcmpl-{uuid.uuid4().hex[:12]}",
                created=int(time.time()),
                model=request.model,
                choices=[
                    {"index": 0, "message": {"role": "assistant", "content": content},
                     "finish_reason": "stop"}
                ],
            ),
            _duomind_headers(jev_header == "on", decision_count, jev_tokens, jev_seconds, llm_seconds),
        )

    # Only short-circuit for greetings/thanks we can answer locally. Anything
    # else -- including factual questions like "What is the capital of France?"
    # -- must go to the LLM, even when Jev flags it as "no generation needed".
    # (Jev treats simple lookups as no-generation, but DuoMind has no lookup
    # source; only the LLM can produce the answer.)
    short_reply = _short_reply(last_content)
    if not needs_gen and short_reply is not None:
        _log_performance(
            jev_header == "on", decision_count, 0, _approx_tokens(short_reply),
            0.0, jev_tokens, jev_seconds, time.time() - request_start,
        )
        return _json_response(
            ChatCompletionResponse(
                id=f"chatcmpl-{uuid.uuid4().hex[:12]}",
                created=int(time.time()),
                model=request.model,
                choices=[
                    {"index": 0,
                     "message": {"role": "assistant", "content": short_reply},
                     "finish_reason": "stop"}
                ],
            ),
            _duomind_headers(jev_header == "on", decision_count, jev_tokens, jev_seconds, llm_seconds),
        )

    verbosity = verbosity_label(pre_decisions.get("verbosity", {}).get("value", 1))
    response_format = pre_decisions.get("format", {}).get("value", "plain_text")
    needs_tool = pre_decisions.get("needs_tool", {}).get("value", False)

    # Tool calling: enable when the client supplied tools AND either Jev said
    # a tool is needed or the client forced tool_choice.
    tools = request.tools if cfg.tools_enabled else None
    forced = _tool_choice_required(request.tool_choice) if tools else None
    use_tool = bool(tools and (needs_tool or forced))

    # Adjust max_tokens from verbosity (must be known before trimming).
    verbosity_max_tokens = {"brief": 80, "normal": 512, "detailed": 1024}
    effective_max_tokens = request.max_tokens or verbosity_max_tokens.get(verbosity, 512)
    request.max_tokens = effective_max_tokens

    steering = build_steering_directive(
        verbosity=verbosity,
        response_format=response_format,
        use_tool=use_tool,
    )

    skill_name = _resolve_skill(pre_decisions, state, jev_header == "on")

    # Build the fixed system/steering/tool prompt first so we can reserve its
    # true size in the context budget. The tool list in particular can be very
    # large (agent front-ends send full JSON schemas), and it is prepended
    # after trimming, so it must be accounted for here.
    system_content = _build_system_content(
        steering, tools, request.tool_choice, cfg.system_prompt, skill_name
    )

    # Trim the conversation to fit the model's context window so the backend
    # does not reject the prompt (or return empty) and can still answer.
    messages = _trim_messages_to_context(
        request.messages,
        cfg.context_size,
        effective_max_tokens,
        _approx_tokens(system_content),
    )

    llm_messages = [{"role": "system", "content": system_content}] + [
        {"role": m.role, "content": m.content or ""} for m in messages
    ]
    prompt = await backend.encode_prompt(llm_messages)
    prompt_tokens = _approx_tokens(prompt)

    if request.stream:
        return StreamingResponse(
            stream_completion(
                prompt, request, tools, jev_header == "on", decision_count,
                prompt_tokens, jev_tokens, jev_seconds, request_start,
            ),
            media_type="text/event-stream",
            headers=_duomind_headers(jev_header == "on", decision_count, jev_tokens, jev_seconds, 0.0),
        )

    # --- Non-streaming generation (MID steering is optional) ---------------
    full_response = ""
    mid_count = 0

    llm_start = time.time()
    if cfg.mid_steering_enabled and not use_tool:
        mid_decision_points = get_decisions_for_stage(DecisionStage.MID)
        full_response, mid_count, mid_jev_seconds, mid_jev_tokens = await _generate_segmented(
            prompt, request, mid_decision_points, state, active_jev
        )
        decision_count += mid_count
        jev_seconds += mid_jev_seconds
        jev_tokens += mid_jev_tokens
    else:
        async for chunk in backend.generate(
            prompt=prompt,
            max_tokens=effective_max_tokens,
            temperature=request.temperature or 0.7,
            stop=request.stop,
            stream=False,
        ):
            full_response += chunk

    llm_seconds = time.time() - llm_start

    # Never hand the client a silently empty reply: if the model produced
    # nothing, fall back to a short message instead of an empty 200.
    if not full_response.strip():
        logger.warning("LLM returned an empty response; using fallback reply")
        full_response = "I couldn't produce a response for that request."

    # Tool-call detection
    if tools:
        tool_call = _extract_tool_call(full_response)
        if tool_call:
            completion_tokens = _approx_tokens(full_response)
            _log_performance(
                jev_header == "on", decision_count, prompt_tokens, completion_tokens,
                llm_seconds, jev_tokens, jev_seconds, time.time() - request_start,
            )
            return _json_response(
                ChatCompletionResponse(
                    id=f"chatcmpl-{uuid.uuid4().hex[:12]}",
                    created=int(time.time()),
                    model=request.model,
                    choices=[
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": f"call_{uuid.uuid4().hex[:12]}",
                                        "type": "function",
                                        "function": {
                                            "name": tool_call["name"],
                                            "arguments": tool_call["arguments"],
                                        },
                                    }
                                ],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ],
                    usage={
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "total_tokens": prompt_tokens + completion_tokens,
                    },
                ),
                _duomind_headers(jev_header == "on", decision_count, jev_tokens, jev_seconds, llm_seconds),
            )

    # --- POST stage decisions (optional) ------------------------------------
    post_count = 0
    if active_jev and cfg.jev_enabled and cfg.post_steering_enabled and not use_tool:
        post_state = _compact_jev_state(state, full_response)
        post_decision_points = get_decisions_for_stage(DecisionStage.POST)
        _t = time.time()
        post_decisions = active_jev.ask_batch(post_state, post_decision_points)
        jev_seconds += time.time() - _t
        jev_tokens += _approx_tokens(json.dumps(post_state))
        post_count = len(post_decisions)
        decision_count += post_count
        logger.info(f"POST decisions: {post_decisions}")

        # Trim a too-verbose answer for a simple request.
        if post_decisions.get("too_verbose", {}).get("value", False):
            trimmed = _trim_to_first_sentences(full_response, 2)
            if trimmed and len(trimmed) < len(full_response):
                logger.info("Answer trimmed (too verbose)")
                full_response = trimmed

        # Retry once with a stronger conciseness directive if needed.
        if post_decisions.get("needs_retry", {}).get("value", False):
            retry_prompt = await backend.encode_prompt(
                _build_llm_messages(
                    request.messages,
                    build_steering_directive(verbosity="brief", response_format=response_format),
                    None,
                    None,
                    cfg.system_prompt,
                    skill_name=skill_name,
                )
            )
            retry_text = ""
            async for chunk in backend.generate(
                prompt=retry_prompt,
                max_tokens=effective_max_tokens,
                temperature=request.temperature or 0.7,
                stop=request.stop,
                stream=False,
            ):
                retry_text += chunk
            if retry_text.strip():
                full_response = retry_text

    llm_seconds = time.time() - llm_start
    completion_tokens = _approx_tokens(full_response)
    _log_performance(
        jev_header == "on", decision_count, prompt_tokens, completion_tokens,
        llm_seconds, jev_tokens, jev_seconds, time.time() - request_start,
    )

    return _json_response(
        ChatCompletionResponse(
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
            usage={
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        ),
        _duomind_headers(jev_header == "on", decision_count, jev_tokens, jev_seconds, llm_seconds),
    )


def _trim_to_first_sentences(text: str, limit: int) -> str:
    """Truncate to the first N sentences, keeping code blocks intact."""
    if limit <= 0:
        return text
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    if len(sentences) <= limit:
        return text
    return " ".join(sentences[:limit])


async def stream_completion(
    prompt: str,
    request: ChatCompletionRequest,
    tools: Optional[List[Dict[str, Any]]],
    jev_on: bool,
    decision_count: int,
    prompt_tokens: int,
    jev_tokens: int,
    jev_seconds: float,
    request_start: float,
) -> AsyncIterator[str]:
    """Stream completion chunks in SSE format, with tool-call detection."""
    request_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    accumulated = ""
    gen_start = time.time()

    async for chunk in backend.generate(
        prompt=prompt,
        max_tokens=request.max_tokens or 512,
        temperature=request.temperature or 0.7,
        stop=request.stop,
        stream=True,
    ):
        accumulated += chunk
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

    _log_performance(
        jev_on, decision_count, prompt_tokens, _approx_tokens(accumulated),
        time.time() - gen_start, jev_tokens, jev_seconds, time.time() - request_start,
    )

    # Detect a tool call in the accumulated output.
    if tools:
        tool_call = _extract_tool_call(accumulated)
        if tool_call:
            final_chunk = {
                "id": request_id,
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": request.model,
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": f"call_{uuid.uuid4().hex[:12]}",
                                    "type": "function",
                                    "function": {
                                        "name": tool_call["name"],
                                        "arguments": tool_call["arguments"],
                                    },
                                }
                            ]
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
            }
            yield f"data: {json.dumps(final_chunk)}\n\n"
            yield "data: [DONE]\n\n"
            return

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
