"""Benchmark DuoMind with Jev ON vs OFF and save statistics.

Runs the same set of prompts twice -- once with Jev enabled and once with
Jev disabled -- and writes per-request statistics (tokens, speed, prompt) to a
dedicated results folder.

The server re-reads ``config.toml`` on every request, so this script toggles
Jev by editing the config file (no restart needed as long as the server was
started with Jev enabled, which is the default).

Usage:
    python performance/benchmark.py
    python performance/benchmark.py --base-url http://127.0.0.1:8000
    python performance/benchmark.py --runs 3
    python performance/benchmark.py --output performance/results
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import httpx
from rich.console import Console
from rich.table import Table

from duomind.config import config as duomind_config

console = Console()

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "performance" / "results"

TEST_PROMPTS: List[Tuple[str, str]] = [
    ("simple_fact", "What is the capital of France?"),
    ("reasoning", "Explain the difference between supervised and unsupervised learning."),
    ("code", "Write a Python function that computes the first 10 Fibonacci numbers."),
    ("creative", "Write a short haiku about artificial intelligence."),
    ("explain", "Explain what a large language model is in two sentences."),
]


def _approx_tokens(text: str) -> int:
    """Rough token estimate (4 chars/token), matching the server."""
    return len(text) // 4


def set_jev(enabled: bool) -> None:
    """Toggle Jev in config.toml; the running server reads it on each request."""
    cfg = duomind_config.load()
    cfg.jev_enabled = enabled
    duomind_config.save(cfg)


def read_model_info() -> Dict[str, str]:
    """Read the configured model and backend from config.toml."""
    cfg = duomind_config.load()
    return {
        "model": cfg.model_path or "unknown",
        "backend": cfg.llm_backend,
    }


def send_request(base_url: str, prompt: str) -> Dict[str, Any]:
    """Send one chat-completion request and measure tokens + speed."""
    payload = {
        "model": "benchmark",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 512,
        "temperature": 0.7,
        "stream": False,
    }

    start = time.time()
    with httpx.Client(timeout=120.0, trust_env=False) as client:
        response = client.post(f"{base_url}/v1/chat/completions", json=payload)
    latency = time.time() - start

    if response.status_code != 200:
        return {
            "success": False,
            "prompt": prompt,
            "latency_seconds": round(latency, 3),
            "error": f"HTTP {response.status_code}",
        }

    data = response.json()
    output = data["choices"][0]["message"]["content"] or ""
    usage = data.get("usage") or {}

    prompt_tokens = int(usage.get("prompt_tokens", _approx_tokens(prompt)))
    completion_tokens = int(usage.get("completion_tokens", _approx_tokens(output)))
    total_tokens = prompt_tokens + completion_tokens

    def _header_float(name: str, default: float = 0.0) -> float:
        try:
            return float(response.headers.get(name, default))
        except (TypeError, ValueError):
            return default

    return {
        "success": True,
        "prompt": prompt,
        "output": output,
        "tokens": {
            "prompt": prompt_tokens,
            "completion": completion_tokens,
            "total": total_tokens,
        },
        "speed": {
            "latency_seconds": round(latency, 3),
            "tokens_per_second": round(completion_tokens / latency, 2) if latency > 0 else 0.0,
            "llm_seconds": round(_header_float("X-DuoMind-Llm-Seconds"), 3),
        },
        "jev": {
            "enabled": response.headers.get("X-DuoMind-Jev") == "on",
            "decisions": int(response.headers.get("X-DuoMind-Decisions", "0")),
            "tokens": int(response.headers.get("X-DuoMind-Jev-Tokens", "0")),
            "seconds": round(_header_float("X-DuoMind-Jev-Seconds"), 3),
        },
    }


def run_prompts(
    base_url: str, mode: str, prompts: List[Tuple[str, str]], runs: int
) -> List[Dict[str, Any]]:
    """Run every prompt ``runs`` times in the given mode."""
    results: List[Dict[str, Any]] = []
    console.print(f"\n[bold cyan]Running with Jev {mode}...[/bold cyan]")

    for run in range(1, runs + 1):
        for idx, (prompt_id, prompt) in enumerate(prompts, 1):
            console.print(f"  run {run}/{runs} [{idx}/{len(prompts)}] {prompt_id}...", end=" ")
            result = send_request(base_url, prompt)
            result["mode"] = "jev_on" if mode == "on" else "jev_off"
            result["prompt_id"] = prompt_id
            result["run"] = run

            if result["success"]:
                console.print(
                    f"[green]OK[/green] {result['speed']['tokens_per_second']} tok/s"
                )
            else:
                console.print(f"[red]FAIL[/red] {result.get('error')}")
            results.append(result)

    return results


def summarize(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute aggregate stats per mode."""
    summary: Dict[str, Any] = {}
    for mode in ("jev_on", "jev_off"):
        group = [r for r in results if r["mode"] == mode and r["success"]]
        if not group:
            summary[mode] = {}
            continue

        latencies = [r["speed"]["latency_seconds"] for r in group]
        speeds = [r["speed"]["tokens_per_second"] for r in group]
        llm_seconds = [r["speed"].get("llm_seconds", 0.0) for r in group]
        jev_seconds = [r["jev"].get("seconds", 0.0) for r in group]
        total_completion = sum(r["tokens"]["completion"] for r in group)
        total_llm_seconds = sum(llm_seconds)
        summary[mode] = {
            "requests": len(group),
            "avg_latency_seconds": round(sum(latencies) / len(latencies), 3),
            "avg_tokens_per_second": round(sum(speeds) / len(speeds), 2),
            "avg_llm_seconds": round(sum(llm_seconds) / len(llm_seconds), 3),
            "avg_jev_seconds": round(sum(jev_seconds) / len(jev_seconds), 3),
            "llm_tokens_per_second": round(total_completion / total_llm_seconds, 2) if total_llm_seconds > 0 else 0.0,
            "total_completion_tokens": total_completion,
            "total_prompt_tokens": sum(r["tokens"]["prompt"] for r in group),
            "total_jev_tokens": sum(r["jev"].get("tokens", 0) for r in group),
        }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark DuoMind Jev ON vs OFF")
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="DuoMind base URL (default: http://127.0.0.1:8000)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Folder to save statistics (default: performance/results)",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=1,
        help="Number of times to run each prompt per mode (default: 1)",
    )
    args = parser.parse_args()

    console.print("[bold cyan]DuoMind Performance Benchmark[/bold cyan]")
    console.print(f"Base URL: {args.base_url}")

    try:
        with httpx.Client(timeout=5.0, trust_env=False) as client:
            response = client.get(f"{args.base_url}/health")
            if response.status_code != 200:
                console.print("[red]Server not healthy. Start it with 'duomind start'.[/red]")
                return 1
    except Exception as e:  # noqa: BLE001
        console.print(f"[red]Cannot connect to server: {e}[/red]")
        return 1

    model_info = read_model_info()
    console.print(f"Model: {model_info['model']}  Backend: {model_info['backend']}")

    # Jev ON
    set_jev(True)
    time.sleep(0.2)
    on_results = run_prompts(args.base_url, "on", TEST_PROMPTS, args.runs)

    # Jev OFF
    set_jev(False)
    time.sleep(0.2)
    off_results = run_prompts(args.base_url, "off", TEST_PROMPTS, args.runs)

    # Restore Jev ON (the safe default)
    set_jev(True)

    results = on_results + off_results
    summary = summarize(results)

    table = Table(title="Jev ON vs OFF", show_header=True, header_style="bold cyan")
    table.add_column("Mode")
    table.add_column("Requests", justify="right")
    table.add_column("Avg latency (s)", justify="right")
    table.add_column("Avg speed (tok/s)", justify="right")
    table.add_column("LLM tok/s", justify="right")
    table.add_column("Jev (s)", justify="right")
    table.add_column("Completion tokens", justify="right")
    for mode in ("jev_on", "jev_off"):
        s = summary.get(mode) or {}
        table.add_row(
            mode,
            str(s.get("requests", 0)),
            str(s.get("avg_latency_seconds", "")),
            str(s.get("avg_tokens_per_second", "")),
            str(s.get("llm_tokens_per_second", "")),
            str(s.get("avg_jev_seconds", "")),
            str(s.get("total_completion_tokens", "")),
        )
    console.print(table)

    # Save statistics to the dedicated results folder.
    args.output.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = args.output / f"benchmark_{timestamp}.json"
    payload = {
        "benchmark_id": f"benchmark_{timestamp}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "base_url": args.base_url,
        "model": model_info["model"],
        "backend": model_info["backend"],
        "runs": args.runs,
        "results": results,
        "summary": summary,
    }
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    console.print(f"\n[green]Statistics saved to {out_path}[/green]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
