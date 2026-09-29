"""Benchmark script to compare Jev ON vs OFF.

Toggles Jev by editing ``config.toml`` (the running server reads it on every
request), so no restart or manual toggling is needed -- matching the behavior
of ``performance/benchmark.py``.
"""

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Dict, List

import httpx
from rich.console import Console
from rich.table import Table

from duomind.config import config as duomind_config

console = Console()

# Test prompts covering different scenarios.
TEST_PROMPTS = [
    {"id": "simple_fact", "prompt": "What is the capital of France?", "expected_short": True},
    {
        "id": "complex_reasoning",
        "prompt": "Explain the difference between supervised and unsupervised learning, with examples.",
        "expected_short": False,
    },
    {
        "id": "code_request",
        "prompt": "Write a Python function to calculate fibonacci numbers recursively.",
        "expected_short": False,
    },
    {"id": "ambiguous", "prompt": "Tell me about Python.", "expected_short": False},
    {"id": "creative", "prompt": "Write a haiku about artificial intelligence.", "expected_short": True},
]


def set_jev(enabled: bool) -> None:
    """Toggle Jev in config.toml; the running server reads it on each request."""
    cfg = duomind_config.load()
    cfg.jev_enabled = enabled
    duomind_config.save(cfg)


def _approx_tokens(text: str) -> int:
    """Rough token estimate (4 chars/token), matching the server."""
    return len(text) // 4


def _header_float(headers, name: str, default: float = 0.0) -> float:
    try:
        return float(headers.get(name, default))
    except (TypeError, ValueError):
        return default


async def send_request(base_url: str, prompt: str) -> Dict:
    """Send a chat completion request and measure tokens + speed."""
    start = time.time()
    async with httpx.AsyncClient(timeout=120.0, trust_env=False) as client:
        response = await client.post(
            f"{base_url}/v1/chat/completions",
            json={
                "model": "benchmark",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 512,
                "temperature": 0.7,
                "stream": False,
            },
        )
    latency = time.time() - start

    if response.status_code != 200:
        return {"success": False, "error": f"HTTP {response.status_code}", "latency": latency}

    data = response.json()
    content = data["choices"][0]["message"]["content"] or ""
    usage = data.get("usage") or {}

    prompt_tokens = int(usage.get("prompt_tokens", _approx_tokens(prompt)))
    completion_tokens = int(usage.get("completion_tokens", _approx_tokens(content)))

    return {
        "success": True,
        "content": content,
        "latency": round(latency, 3),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "jev_enabled": response.headers.get("X-DuoMind-Jev", "unknown"),
        "decision_count": int(response.headers.get("X-DuoMind-Decisions", "0")),
        "jev_tokens": int(response.headers.get("X-DuoMind-Jev-Tokens", "0")),
        "jev_seconds": round(_header_float(response.headers, "X-DuoMind-Jev-Seconds"), 3),
        "llm_seconds": round(_header_float(response.headers, "X-DuoMind-Llm-Seconds"), 3),
    }


async def run_benchmark(base_url: str, jev_mode: str) -> List[Dict]:
    """Run all test prompts and collect results."""
    results = []

    console.print(f"\n[bold cyan]Running benchmark with Jev {jev_mode}...[/bold cyan]")

    for idx, test in enumerate(TEST_PROMPTS, 1):
        console.print(f"  [{idx}/{len(TEST_PROMPTS)}] {test['id']}...", end=" ")

        try:
            result = await send_request(base_url, test["prompt"])

            if result["success"]:
                short_ok = not test["expected_short"] or result["completion_tokens"] <= 120
                flag = "" if short_ok else " [yellow]⚠ expected short, got long[/yellow]"
                console.print(
                    f"[green]OK[/green] {result['latency']:.2f}s / {result['completion_tokens']} tok{flag}"
                )
                results.append(
                    {
                        "test_id": test["id"],
                        "mode": jev_mode,
                        "expected_short": test["expected_short"],
                        **result,
                    }
                )
            else:
                console.print(f"[red]FAIL[/red] {result['error']}")

        except Exception as e:  # noqa: BLE001
            console.print(f"[red]FAIL[/red] {e}")

    return results


def compare_results(on_results: List[Dict], off_results: List[Dict]) -> None:
    """Compare Jev ON vs OFF results."""
    console.print("\n[bold]Comparison: Jev ON vs OFF[/bold]\n")

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Test")
    table.add_column("ON latency (s)", justify="right")
    table.add_column("OFF latency (s)", justify="right")
    table.add_column("ON tokens", justify="right")
    table.add_column("OFF tokens", justify="right")
    table.add_column("Decisions", justify="right")

    for on_res in on_results:
        test_id = on_res["test_id"]
        off_res = next((r for r in off_results if r["test_id"] == test_id), None)

        if not off_res:
            continue

        table.add_row(
            test_id,
            f"{on_res['latency']:.2f}",
            f"{off_res['latency']:.2f}",
            str(on_res["completion_tokens"]),
            str(off_res["completion_tokens"]),
            str(on_res.get("decision_count", 0)),
        )

    console.print(table)

    if not on_results or not off_results:
        return

    on_avg_latency = sum(r["latency"] for r in on_results) / len(on_results)
    off_avg_latency = sum(r["latency"] for r in off_results) / len(off_results)
    on_total_tokens = sum(r["completion_tokens"] for r in on_results)
    off_total_tokens = sum(r["completion_tokens"] for r in off_results)
    on_llm_seconds = sum(r["llm_seconds"] for r in on_results)
    off_llm_seconds = sum(r["llm_seconds"] for r in off_results)
    on_jev_seconds = sum(r["jev_seconds"] for r in on_results)

    console.print("\n[bold]Summary:[/bold]")
    console.print(f"  Average latency  (ON):  {on_avg_latency:.2f}s   (OFF): {off_avg_latency:.2f}s")
    console.print(f"  Completion tokens (ON):  {on_total_tokens}   (OFF): {off_total_tokens}")
    console.print(
        f"  LLM speed        (ON):  {on_total_tokens / on_llm_seconds:.1f} tok/s"
        if on_llm_seconds > 0
        else "  LLM speed        (ON):  n/a"
    )
    console.print(
        f"  LLM speed        (OFF): {off_total_tokens / off_llm_seconds:.1f} tok/s"
        if off_llm_seconds > 0
        else "  LLM speed        (OFF): n/a"
    )
    console.print(f"  Jev overhead     (ON):  {on_jev_seconds:.2f}s total")

    if on_avg_latency > off_avg_latency:
        console.print(
            f"\n[yellow]Jev adds ~{on_avg_latency - off_avg_latency:.2f}s latency per request "
            "(classification round-trip). LLM generation speed is unchanged.[/yellow]"
        )
    else:
        console.print("\n[green]Jev does not add significant latency[/green]")


async def main():
    parser = argparse.ArgumentParser(description="Benchmark Jev ON vs OFF")
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="DuoMind base URL (default: http://127.0.0.1:8000)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Save results to JSON file",
    )

    args = parser.parse_args()

    console.print("[bold cyan]DuoMind Benchmark[/bold cyan]")
    console.print(f"Base URL: {args.base_url}")

    # Check server health
    try:
        async with httpx.AsyncClient(timeout=5.0, trust_env=False) as client:
            response = await client.get(f"{args.base_url}/health")
            if response.status_code != 200:
                console.print("[red]Server not healthy. Start it with 'duomind start'.[/red]")
                return
        console.print("[green]Server healthy[/green]")
    except Exception as e:  # noqa: BLE001
        console.print(f"[red]Cannot connect to server: {e}[/red]")
        return

    # Run with Jev ON
    set_jev(True)
    await asyncio.sleep(0.2)
    on_results = await run_benchmark(args.base_url, "on")

    # Run with Jev OFF
    set_jev(False)
    await asyncio.sleep(0.2)
    off_results = await run_benchmark(args.base_url, "off")

    # Restore Jev ON (the safe default)
    set_jev(True)

    if on_results and off_results:
        compare_results(on_results, off_results)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(
                {"on": on_results, "off": off_results},
                f,
                indent=2,
            )
        console.print(f"\n[green]Results saved to {args.output}[/green]")


if __name__ == "__main__":
    asyncio.run(main())
