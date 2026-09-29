# Design Decisions

**Project**: DuoMind  
**Date**: 2026-09-28  
**Author**: Claude Code (automated build)

---

## 1. VRAM Constraint: 6GB Primary, Optional 14B Model

**Context**: Original prompt assumed RTX 3060 with 12GB VRAM. Actual GPU is 6GB variant (laptop).

**Decision**: Primary model selection targets 2-4B models for 6GB VRAM, plus one optional 14B model (Phi-4) for machines with 10GB+ VRAM.

**Rationale**:
- 2-4B models with Q4_K_M quantization use ~2-3GB VRAM
- Leaves ~3GB for context window and KV cache
- Phi-4 14B (Q4_K_M, ~8.4GB) is listed first but the setup wizard's "Fit?" column flags it as not fitting on 6GB

**Models chosen**:
1. Phi-4 14B (optional, needs 10GB+ VRAM)
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
- **PRE**: 6 decisions (needs_generation, needs_reasoning, intent, complexity, ambiguity, safety)
- **MID**: 4 decisions (on_track, step_complete, should_stop, confidence_mid)
- **POST**: 3 decisions (answer_complete, matches_request, needs_retry)

**Rationale**:
- PRE: Gate generation and route simple requests
- MID: Steer generation at checkpoints (configurable, max 3 by default)
- POST: Validate output quality

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

**Current status**: The `duomind models` subcommand is not implemented yet. Switching models currently requires re-running `duomind setup` or editing `model_path` in `config.toml` manually.

---

## 13. Jev ON/OFF: Runtime Toggle

**Context**: Author wanted to compare Jev ON vs OFF.

**Decision**: `duomind jev on|off` updates config.toml and takes effect immediately (no restart needed).

**Implementation**: Server checks `config.jev_enabled` on each request. JevClient initialized at startup but `enabled` flag checked per call.

**Benchmark**: `scripts/benchmark.py` runs same prompts with Jev on and off, compares results.

**Current status**: The `duomind jev` subcommand is not implemented yet. Toggling Jev currently requires editing `jev_enabled` in `config.toml` and restarting the server.

---

## 14. Segmented Generation: Not Fully Implemented

**Context**: Author requested "MID checkpoints" where generation pauses, Jev classifies, resumes.

**Decision**: Skeleton in place but not fully functional in initial version.

**Rationale**: 
- llama.cpp `/completion` endpoint generates in one pass
- Implementing stop-sequences + resume + state tracking is complex
- Deferred to future version

**Current behavior**: MID decisions skipped. PRE and POST work fully.

**Future**: Add stop sequences at reasoning step markers (e.g., "Step N:"), batch MID decisions, resume generation.

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

## 18. Models.json: 5 Models (1 Large + 4 Small)

**Context**: Original prompt suggested Phi-4 3.8B, Qwen 8B, Gemma 12B. Too large for 6GB.

**Decision**: Curated list with Q4_K_M quantization — one large model and four 2-3B models:
1. Phi-4 14B - high quality, needs 10GB+ VRAM
2. Qwen2.5 3B Instruct - multilingual, long context
3. Qwen2.5-Coder 3B - code-focused
4. Gemma 2 2B - smallest, fastest
5. Llama 3.2 3B - long context, Meta quality

**Correction (Phi-4 Mini mislabel)**: The original `models.json` listed a "Phi-4 Mini (3.8B)" entry whose `hf_repo`/`filename` actually pointed to the full Phi-4 (14B, ~8.4GB). Selecting it on a 6GB machine downloaded the full model and crashed. The entry has been relabeled honestly as "Phi-4 (14B)" with correct size and VRAM requirements. A true Phi-4 Mini entry is not currently listed.

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
- Process management: `CREATE_NO_WINDOW` on Windows, `start_new_session` on POSIX
- GPU detection: `nvidia-smi` (works on Linux too)

**Not tested**: macOS, Linux. May work but no guarantees.

---

## Summary of Deviations from Original Prompt

1. **Model selection**: 2-4B primary plus an optional 14B (VRAM constraint)
2. **Terminology**: "Noul" instead of "null" (SDK naming)
3. **llama.cpp download**: Manual in setup wizard (automated download not implemented yet)
4. **MID checkpoints**: Skeleton only (segmented generation deferred)
5. **Default model count**: 5 (one 14B + four 2-3B)

**Everything else**: Implemented as specified or with reasonable defaults where unspecified.
