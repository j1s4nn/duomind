# Design Decisions

**Project**: DuoMind  
**Date**: 2026-09-28  
**Author**: Claude Code (automated build)

---

## 1. VRAM Constraint: 6GB Not 12GB

**Context**: Original prompt assumed RTX 3060 with 12GB VRAM. Actual GPU is 6GB variant (laptop).

**Decision**: Adjusted model selection to 2-4B parameter models instead of 8-14B.

**Rationale**:
- 2-4B models with Q4_K_M quantization use ~2-3GB VRAM
- Leaves ~3GB for context window and KV cache
- 8-14B models would not fit even with quantization

**Models chosen**:
1. Phi-4 Mini 3.8B (if exists)
2. Qwen2.5 3B Instruct
3. Qwen2.5-Coder 3B
4. Gemma 2 2B
5. Llama 3.2 3B

**Verification status**: Model repos and filenames could not be verified via WebFetch (Hugging Face blocked). Must verify during actual download or manually.

---

## 2. llama.cpp Distribution: Prebuilt Binaries

**Context**: Original prompt specified "prebuilt llama.cpp binaries, no compilation by users."

**Decision**: Download official llama-server.exe from GitHub releases.

**Rationale**:
- Avoids llama-cpp-python which requires C++ compilation
- Windows users (target audience) often lack build tools
- Prebuilt binaries work out-of-the-box

**Alternative considered**: llama-cpp-python wheels  
**Rejected because**: Still requires CUDA toolkit for GPU support; binary is simpler

**Implementation note**: Setup wizard currently tells user to download manually. Automated download to be added in future version (requires verifying GitHub release API access).

---

## 3. Jev Question Naming: "Noul" Not "Null"

**Context**: Author called yes/no questions "null" but SDK uses "Noul".

**Decision**: Use SDK's terminology throughout codebase.

**Mapping**:
- Author's "choice" = SDK's `Choice` ✓
- Author's "null" = SDK's `Noul` (yes/no probability)
- Author's "score" = SDK's `Score` ✓

**Rationale**: Match official SDK to avoid confusion. Document mapping in README glossary.

---

## 4. Decision Registry: PRE/MID/POST Stages

**Context**: Author specified decision points but not exact stage breakdown.

**Decision**: 
- **PRE**: 9 decisions (needs_generation, needs_reasoning, intent, complexity, ambiguity, safety, verbosity, format, needs_tool)
- **MID**: 4 decisions (on_track, step_complete, should_stop, confidence_mid)
- **POST**: 5 decisions (answer_complete, matches_request, needs_retry, too_verbose, correct_format)

**Rationale**:
- PRE: Gate generation, route simple requests, and steer verbosity/format/tool use
- MID: Steer generation at checkpoints (configurable, max 3 by default)
- POST: Validate output quality and trim verbose or mis-formatted answers

**MID checkpoint trigger**: Only for requests where PRE.complexity >= 1 (moderate or complex). Simple requests skip MID.

---

## 5. Circuit Breaker: 3 Failures in 60s

**Context**: Author requested "circuit breaker" but didn't specify thresholds.

**Decision**: 
- Failure threshold: 3
- Window: 60 seconds
- Open timeout: 30 seconds
- State transitions: closed → open (after 3) → half_open (after 30s) → closed (on success)

**Rationale**: Balances responsiveness (don't fail permanently) with protection (don't hammer Jev if it's down).

**Fallback**: Local rule-based classifier when circuit is open.

---

## 6. Confidence Threshold: Default 0.6

**Context**: Author said "confidence gating" but didn't specify default.

**Decision**: Global default 0.6, overridable per decision.

**Per-decision overrides**:
- Safety: 0.8 (require high confidence for safety checks)
- Intent: 0.5 (multiple choice is easier, lower threshold OK)
- should_stop: 0.7 (important to not cut off generation prematurely)

**Rationale**: 0.6 is "more likely than not" but allows fallback when Jev is uncertain. Higher for critical decisions.

---

## 7. Cache TTL: 1 Hour

**Context**: Author requested caching but didn't specify TTL.

**Decision**: 1 hour (3600 seconds).

**Rationale**:
- Short enough that stale decisions don't linger
- Long enough to benefit repeated similar requests (e.g., testing)
- Jev input tokens are metered, cache reduces cost

**Cache invalidation**: Automatic on TTL expiry. No manual invalidation API (could add later).

---

## 8. Data Directory: %LOCALAPPDATA%\duomind

**Context**: Author noted repo is in OneDrive and warned about syncing models.

**Decision**: All non-source files go in `%LOCALAPPDATA%\duomind`:
- `config.toml`
- `models/` (GGUFs)
- `binaries/` (llama-server.exe)
- `cache/` (SQLite)
- `logs/`
- `duomind.pid`

**Rationale**: 
- Avoids syncing gigabytes to OneDrive
- Standard Windows location for app data (via `platformdirs`)
- Survives repo deletion (user can delete repo, keep config/models)

**Trade-off**: Separates data from code. Acceptable for this use case.

---

## 9. No Tool Calling Validation

**Context**: OpenAI /v1/chat/completions supports tool calls. Small models may not.

**Decision**: Pass tool calls through without validation. Relay request to backend as-is.

**Rationale**:
- Most 3-4B models don't support tool calling reliably
- DuoMind's value is classification, not tool routing
- If user's client sends tools, let the model handle it (will likely ignore or fail)

**Future**: Could add tool-calling-capable models (Phi-4 claims support) and validate format.

---

## 10. Streaming: SSE Format

**Context**: OpenAI uses Server-Sent Events (SSE) for streaming.

**Decision**: Implement SSE streaming with `data: {json}\n\n` format, ending with `data: [DONE]\n\n`.

**Rationale**: Standard format expected by OpenAI-compatible clients (Cline, Kilo Code).

**Implementation**: FastAPI's `StreamingResponse` with async generator.

---

## 11. Auth: Optional Bearer Token

**Context**: Local server, but may want to restrict access.

**Decision**: Optional `api_key` in config.toml. If set, require `Authorization: Bearer <key>` header.

**Rationale**:
- Default: no auth (bind 127.0.0.1, assume trusted local environment)
- Optional: protect if user exposes port or runs on shared machine

**Not implemented**: OAuth, JWT, or multi-user auth. Overkill for local tool.

---

## 12. Model Switching: Restart llama-server

**Context**: User may want to switch models without full re-setup.

**Decision**: `duomind models switch` stops llama-server, updates config.toml with new model path, restarts llama-server.

**Jev state**: Unchanged (Jev is independent of LLM).

**Rationale**: llama-server loads model on startup, can't hot-swap. Restart is necessary.

---

## 13. Jev ON/OFF: Runtime Toggle

**Context**: Author wanted to compare Jev ON vs OFF.

**Decision**: `duomind jev on|off` updates config.toml and takes effect immediately (no restart needed).

**Implementation**: Server checks `config.jev_enabled` on each request. JevClient initialized at startup but `enabled` flag checked per call.

**Benchmark**: `scripts/benchmark.py` runs same prompts with Jev on and off, compares results.

---

## 14. Segmented Generation: Wired

**Context**: Author requested "MID checkpoints" where generation pauses, Jev classifies, resumes.

**Decision**: Segmented generation is implemented for non-streaming requests.

**How it works**:
1. Split `max_tokens` into segments of `mid_segment_tokens` (default 160).
2. Generate one segment, then run MID decisions (on_track, step_complete, should_stop, confidence_mid).
3. Stop early if `should_stop` is true or `on_track` is false; otherwise continue to the next segment.
4. Repeat up to `max_mid_checkpoints` (default 3) times.

**Trigger**: Only for requests where PRE.complexity >= 1 (moderate or complex). Simple requests and tool-call requests skip MID.

**Streaming**: MID steering is non-streaming only; streaming requests use PRE gating plus the injected steering skill.

---

## 15. Test Coverage: Mocked Jev and Backend

**Context**: Tests must pass without real API keys or GPU.

**Decision**: 
- Mock TypeSafeClient with unittest.mock
- Mock backend with in-memory completion responses
- Test decision logic, caching, circuit breaker, confidence gating

**What's NOT tested**:
- Real Jev API calls (would require key and cost money)
- Real llama-server (would require GPU and model download)
- Cline/Kilo Code integration (manual testing required)

---

## 16. Error Logging: No Prompt Text by Default

**Context**: Privacy-sensitive prompts may contain user data.

**Decision**: Log decision name, value, confidence, source, latency. Do NOT log `state` or prompt text by default.

**Override**: Debug mode (future) could enable full logging.

**Rationale**: User's data goes to Jev (accepted), but shouldn't leak into local logs readable by others.

---

## 17. LaTeX Figure: Optional Dependency

**Context**: Non-coders may not have MiKTeX.

**Decision**: 
- Check `pdflatex --version` before building
- If not found, skip gracefully with message
- Commit PNG to repo so README works without MiKTeX

**Rationale**: Figure is nice-to-have, not critical. Don't block build on LaTeX.

**Implementation**: `scripts/build_figure.py` checks MiKTeX, renders if available, otherwise skips.

---

## 18. Models.json: 5 Models for 6GB VRAM

**Context**: Original prompt suggested Phi-4 3.8B, Qwen 8B, Gemma 12B. Too large for 6GB.

**Decision**: Curated list of 2-4B models, all with Q4_K_M quantization:
1. Phi-4 Mini 3.8B (if exists) - general purpose
2. Qwen2.5 3B Instruct - multilingual, long context
3. Qwen2.5-Coder 3B - code-focused
4. Gemma 2 2B - smallest, fastest
5. Llama 3.2 3B - long context, Meta quality

**Verification**: Must check Hugging Face repos exist before finalizing list.

---

## 19. No Performance Claims

**Context**: Author said "no performance claims without measurement."

**Decision**: README includes "Honest Limits" section:
- No proof Jev improves small models until benchmarked
- Models this small will make mistakes
- Jev adds latency (70-500ms)
- Early access software, expect rough edges

**Rationale**: Manage expectations. DuoMind is an experiment, not a production-ready product.

---

## 20. Unofficial Project Notice

**Context**: Uses TypeSafe's Jev but not affiliated.

**Decision**: Add to README and LICENSE:
> "Unofficial community project. Not affiliated with or endorsed by TypeSafe AI."

**Rationale**: Avoid confusion. Make it clear this is not an official TypeSafe product.

---

## 21. Windows-First, Cross-Platform Secondary

**Context**: Author's machine is Windows 11, target user is non-technical Windows user.

**Decision**: Optimize for Windows, keep code portable where cheap.

**Windows-specific**:
- Path handling via `pathlib` (works everywhere)
- Process management: `DETACHED_PROCESS` on Windows, `start_new_session` on POSIX
- GPU detection: `nvidia-smi` (works on Linux too)

**Not tested**: macOS, Linux. May work but no guarantees.

---

## 22. Default Steering Skill

**Context**: Jev returns raw scores that small models cannot interpret. The LLM needs plain, imperative instructions.

**Decision**: A default system prompt (`src/duomind/skill.py`) is injected into every request. It encodes concrete rules (match length to intent, plain text by default, call tools when listed, never refuse what tools allow). PRE decisions (verbosity, format, needs_tool) are translated into a short "steering directive" appended to that skill.

**Rationale**: The LLM obeys a short imperative instruction in milliseconds without needing to reason about Jev's numeric output. Model-agnostic.

## 23. Tool Calling (files, folders, projects, web)

**Context**: Cline and Kilo Code create files and fetch the web by sending tool definitions and expecting a `tool_calls` response.

**Decision**: Implement the OpenAI-compatible tool-calling protocol:
- Accept `tools` and `tool_choice` in `/v1/chat/completions`.
- Describe available tools and the exact `<tool_call>{...}</tool_call>` format in the prompt.
- Parse the model's tool call and return `finish_reason: "tool_calls"` with a well-formed `tool_calls` array (streaming included).
- Use the PRE `needs_tool` decision to decide when a tool is required.

**Rationale**: The client executes the tool and returns the result; the server only needs to emit the correct protocol. This is what fixes "I cannot create files/folders/projects/fetch the web."

---

## 24. Skills: Task Workflows Injected into the Prompt

**Context**: A 3B model told "create a project where the website looks like this URL" often replies "I can't do this" because it cannot improvise the multi-step plan (fetch the URL, scaffold files, run git). The steering skill tells it *how* to behave, but not *what workflow* to follow for a given task.

**Decision**: Add a skill registry (`src/duomind/skills.py`) with a named workflow per task type:
- `webdev` — build a website, including "recreate this URL" (fetch first, then scaffold files)
- `coding` — write/implement/refactor code
- `debug` — fix bugs, errors, tracebacks
- `git` — status, diff, commit, pull, push, branch, merge
- `webfetch` — fetch and answer about a URL
- `general` — no specialized workflow (empty instructions)

**Selection**: A new PRE `skill` CHOICE decision lets Jev pick the best skill; its criteria are derived from the registry so there is one source of truth. When Jev is off or low-confidence, a local keyword matcher (`select_skill`) scores each skill by trigger-word hits and picks the winner.

**Injection**: The chosen skill's instructions are injected into the system prompt as `[Active skill: <name>]` before the steering directive and tool list. Each skill's instructions give the model the exact step-by-step workflow and explicitly forbid "I can't do this" when the required tools are available.

**Rationale**: Small models obey concrete, imperative workflows far more reliably than they improvise them. This turns "the model refuses" into "the model follows a recipe."

---

## Summary of Deviations from Original Prompt

1. **Model selection**: 2-4B instead of 8-14B (VRAM constraint)
2. **Terminology**: "Noul" instead of "null" (SDK naming)
3. **llama.cpp download**: Automated, cross-platform (Windows/Linux/macOS) via GitHub releases
4. **MID checkpoints**: Fully wired via segmented generation (non-streaming)
5. **Decision points**: 18 across PRE/MID/POST (was 13); now 19 with the PRE `skill` decision
6. **Cross-platform**: Windows, Linux, and macOS all supported
7. **Tool calling**: OpenAI-compatible function calling added
8. **Skills**: Task workflows (webdev, coding, debug, git, webfetch, general) selected by Jev and injected into the prompt

**Everything else**: Implemented as specified or with reasonable defaults where unspecified.
