"""Build the DuoMind architecture diagram (PNG) with matplotlib.

Replaces the previous LaTeX build. Requires only matplotlib + numpy.

Usage:
    python scripts/build_figure.py

Output:
    docs/images/architecture.png
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "docs" / "images" / "architecture.png"

# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------
C_CLIENT = "#DBEAFE"; E_CLIENT = "#2563EB"   # blue: clients
C_SERVER = "#EDE9FE"; E_SERVER = "#6D28D9"   # purple: orchestrator
C_STAGE  = "#FEF3C7"; E_STAGE  = "#B45309"   # orange: PRE / POST gates
C_LLM    = "#CFFAFE"; E_LLM    = "#0E7490"   # cyan: System 2
C_JEV    = "#D1FAE5"; E_JEV    = "#047857"   # green: System 1
C_RESP   = "#ECFDF5"; E_RESP   = "#059669"   # teal: response
C_FB     = "#FEF9C3"; E_FB     = "#A16207"   # yellow: fallback

GRAY  = "#374151"
DARK  = "#111827"
MUTED = "#6B7280"
LIGHT = "#9CA3AF"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def node(ax, cx, cy, w, h, title, detail=None, *, fc="#FFFFFF", ec="#333333",
         ts=12.5, ds=9.5, tc=DARK, dc=GRAY, ls="-", lw=1.8, z=2, rounding=1.4):
    """Draw a rounded box with an optional bold title + detail line."""
    ax.add_patch(
        FancyBboxPatch(
            (cx - w / 2, cy - h / 2), w, h,
            boxstyle=f"round,pad=0.4,rounding_size={rounding}",
            fc=fc, ec=ec, lw=lw, linestyle=ls, zorder=z,
        )
    )
    if detail:
        ax.text(cx, cy + h * 0.21, title, ha="center", va="center",
                fontsize=ts, color=tc, weight="bold", zorder=z + 3)
        ax.text(cx, cy - h * 0.24, detail, ha="center", va="center",
                fontsize=ds, color=dc, zorder=z + 3, linespacing=1.35)
    else:
        ax.text(cx, cy, title, ha="center", va="center",
                fontsize=ts, color=tc, weight="bold", zorder=z + 3)


def arrow(ax, p1, p2, *, color=GRAY, lw=1.9, ls="-", rad=0.0, ms=16, z=1):
    """Draw an arrow between two points."""
    ax.add_patch(
        FancyArrowPatch(
            p1, p2, arrowstyle="-|>", mutation_scale=ms, lw=lw,
            color=color, linestyle=ls, zorder=z,
            connectionstyle=f"arc3,rad={rad}",
        )
    )


def note(ax, x, y, text, *, fs=9.5, color=MUTED, ha="center", va="center",
         z=6, weight="normal", rotation=0):
    ax.text(x, y, text, ha=ha, va=va, fontsize=fs, color=color, zorder=z,
            style="italic", weight=weight, rotation=rotation)


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------
def build_figure() -> bool:
    fig, ax = plt.subplots(figsize=(16, 11))
    ax.set_xlim(0, 160)
    ax.set_ylim(0, 110)
    ax.set_aspect("equal")
    ax.axis("off")
    fig.patch.set_facecolor("white")

    # -- top: clients -------------------------------------------------------
    node(ax, 80, 103, 46, 8, "Cline  \u00b7  Kilo Code  \u00b7  User",
         "OpenAI-compatible clients", fc=C_CLIENT, ec=E_CLIENT, ts=13)

    # -- server -------------------------------------------------------------
    node(ax, 80, 91, 46, 8, "DuoMind Server (FastAPI)",
         "orchestrator", fc=C_SERVER, ec=E_SERVER, ts=13)

    # -- PRE gate -----------------------------------------------------------
    node(ax, 80, 78, 54, 10, "PRE  \u2014  Jev classifies the request",
         "needs_generation \u00b7 needs_reasoning \u00b7 intent\n"
         "complexity \u00b7 ambiguity \u00b7 safety",
         fc=C_STAGE, ec=E_STAGE, ts=12.5)

    # -- reasoning loop container -------------------------------------------
    node(ax, 80, 54, 122, 30, "", fc="#F9FAFB", ec=LIGHT, ls=(0, (5, 4)),
         lw=1.6, z=1, rounding=2.2)
    ax.text(80, 67.6, "REASONING LOOP  \u2014  Jev classifies inside the LLM\u2019s reasoning",
            ha="center", va="center", fontsize=12.5, color=DARK, weight="bold", zorder=5)

    # LLM (System 2)
    node(ax, 42, 54, 32, 15, "Local LLM", "System 2\nllama.cpp / Ollama\nreasoning \u00b7 generation",
         fc=C_LLM, ec=E_LLM, ts=13, ds=8.6)
    # Jev (System 1)
    node(ax, 118, 54, 32, 15, "Jev", "System 1 \u00b7 MID checkpoints\non_track \u00b7 step_complete\nshould_stop \u00b7 confidence_mid",
         fc=C_JEV, ec=E_JEV, ts=13, ds=8.6)

    # the loop itself (LLM <-> Jev)
    arrow(ax, (58, 60), (102, 60), color=E_LLM, lw=2.2, rad=0.0)
    arrow(ax, (102, 48), (58, 48), color=E_JEV, lw=2.2, rad=0.0)
    note(ax, 80, 61.4, "reasoning step / text", color=E_LLM)
    note(ax, 80, 45.6, "steer / stop\non_track? step_complete? should_stop?",
         color=E_JEV, fs=8.6)

    # -- POST gate ----------------------------------------------------------
    node(ax, 80, 28, 54, 10, "POST  \u2014  Jev verifies the output",
         "answer_complete \u00b7 matches_request\nneeds_retry",
         fc=C_STAGE, ec=E_STAGE, ts=12.5)

    # -- response -----------------------------------------------------------
    node(ax, 80, 16, 42, 8, "Response",
         "X-DuoMind-Jev \u00b7 X-DuoMind-Decisions",
         fc=C_RESP, ec=E_RESP, ts=13)

    # -- main flow arrows ---------------------------------------------------
    arrow(ax, (80, 99), (80, 95))                       # client -> server
    arrow(ax, (80, 87), (80, 83))                       # server -> PRE
    note(ax, 118, 85.2, "state = {messages, prompt}", fs=9, color=MUTED)

    arrow(ax, (80, 73), (80, 69))                       # PRE -> loop
    note(ax, 88, 71.2, "generate", fs=9, color=MUTED)

    arrow(ax, (80, 39), (80, 33))                       # loop -> POST
    note(ax, 88, 36.2, "full text", fs=9, color=MUTED)

    arrow(ax, (80, 23), (80, 20))                       # POST -> response
    note(ax, 96, 21.6, "accept", fs=9, color=MUTED)

    # -- retry loop (dashed, right side) ------------------------------------
    arrow(ax, (107, 32), (139, 42), color=E_STAGE, ls=(0, (5, 4)),
          lw=1.6, rad=0.18)
    note(ax, 142, 37, "needs_retry\n\u2192 regenerate", fs=8.6,
         color=E_STAGE, ha="left")

    # -- footer: JevClient internals + fallback -----------------------------
    node(ax, 80, 6, 118, 7, "", fc="#F3F4F6", ec=LIGHT, ls="-", lw=1.2, z=1, rounding=1.2)
    ax.text(80, 6, "JevClient safety rails:  circuit breaker (3 failures \u2192 fallback)  \u00b7  "
                   "SQLite cache (1 h TTL)  \u00b7  confidence gate (threshold 0.6)  \u00b7  "
                   "rule-based local fallback",
            ha="center", va="center", fontsize=9.2, color=GRAY, zorder=5)

    # -- legend -------------------------------------------------------------
    node(ax, 22, 103, 34, 10, "", fc="white", ec=LIGHT, ls="-", lw=1.0, z=1, rounding=1.0)
    lx, ly0 = 22, 103
    for dy, color, lab in [
        (2.0, E_JEV, "System 1 \u00b7 Jev (classify)"),
        (0.0, E_LLM, "System 2 \u00b7 Local LLM (generate)"),
        (-2.0, E_STAGE, "Decision gate (PRE / MID / POST)"),
    ]:
        ax.add_patch(FancyBboxPatch((lx - 14, ly0 + dy - 0.7), 2.4, 1.4,
                                    boxstyle="round,pad=0.05,rounding_size=0.3",
                                    fc=color, ec=color, zorder=5))
        ax.text(lx - 11.5, ly0 + dy, lab, ha="left", va="center",
                fontsize=8.2, color=GRAY, zorder=5)

    # -- save ---------------------------------------------------------------
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=220, bbox_inches="tight", pad_inches=0.15,
                facecolor="white")
    plt.close(fig)
    print(f"OK  wrote {OUT}")
    return True


if __name__ == "__main__":
    sys.exit(0 if build_figure() else 1)
