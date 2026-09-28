"""Benchmark script to compare Jev ON vs OFF."""

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Dict, List

import httpx
from rich.console import Console
from rich.table import Table

console = Console()

# Test prompts covering different scenarios
TEST_PROMPTS = [
    {
        "id": "simple_fact",
        "prompt": "What is the capital of France?",
        "expected_short": True,
    },
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
    {
        "id": "ambiguous",
        "prompt": "Tell me about Python.",
        "expected_short": False,
    },
    {
        "id": "creative",
        "prompt": "Write a haiku about artificial intelligence.",
        "expected_short": True,
    },
]


async def send_request(
    base_url: str, prompt: str, stream: bool = False
) -> Dict:
    """Send a chat completion request."""
    start = time.time()

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{base_url}/v1/chat/completions",
            json={
                "model": "test",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 512,
                "temperature": 0.7,
                "stream": stream,
            },
        )

        latency = time.time() - start

        if response.status_code != 200:
            return {
                "success": False,
                "error": f"HTTP {response.status_code}",
                "latency": latency,
            }

        data = response.json()
        content = data["choices"][0]["message"]["content"]
        jev_header = response.headers.get("X-DuoMind-Jev", "unknown")
        decisions_header = response.headers.get("X-DuoMind-Decisions", "0")

        return {
            "success": True,
            "content": content,
            "latency": latency,
            "jev_enabled": jev_header,
            "decision_count": int(decisions_header),
            "tokens": len(content.split()),  # Rough estimate
        }


async def run_benchmark(
    base_url: str, jev_mode: str, mock: bool = False
) -> List[Dict]:
    """Run all test prompts and collect results."""
    results = []

    console.print(f"\n[bold cyan]Running benchmark with Jev {jev_mode}...[/bold cyan]")

    for idx, test in enumerate(TEST_PROMPTS, 1):
        console.print(f"  [{idx}/{len(TEST_PROMPTS)}] {test['id']}...", end=" ")

        try:
            result = await send_request(base_url, test["prompt"])

            if result["success"]:
                console.print(f"[green]✓[/green] {result['latency']:.2f}s")
                results.append({
                    "test_id": test["id"],
                    "mode": jev_mode,
                    **result,
                })
            else:
                console.print(f"[red]✗ {result['error']}[/red]")

        except Exception as e:
            console.print(f"[red]✗ {e}[/red]")

    return results


def compare_results(on_results: List[Dict], off_results: List[Dict]) -> None:
    """Compare Jev ON vs OFF results."""
    console.print("\n[bold]Comparison: Jev ON vs OFF[/bold]\n")

    # Latency comparison
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Test")
    table.add_column("Jev ON (s)", justify="right")
    table.add_column("Jev OFF (s)", justify="right")
    table.add_column("Diff (s)", justify="right")
    table.add_column("Decisions", justify="right")

    for on_res in on_results:
        test_id = on_res["test_id"]
        off_res = next((r for r in off_results if r["test_id"] == test_id), None)

        if off_res:
            diff = on_res["latency"] - off_res["latency"]
            diff_str = f"+{diff:.2f}" if diff > 0 else f"{diff:.2f}"
            diff_color = "red" if diff > 0.5 else "yellow" if diff > 0.1 else "green"

            table.add_row(
                test_id,
                f"{on_res['latency']:.2f}",
                f"{off_res['latency']:.2f}",
                f"[{diff_color}]{diff_str}[/{diff_color}]",
                str(on_res.get("decision_count", 0)),
            )

    console.print(table)

    # Summary stats
    on_avg_latency = sum(r["latency"] for r in on_results) / len(on_results)
    off_avg_latency = sum(r["latency"] for r in off_results) / len(off_results)

    console.print(f"\n[bold]Summary:[/bold]")
    console.print(f"  Average latency (Jev ON):  {on_avg_latency:.2f}s")
    console.print(f"  Average latency (Jev OFF): {off_avg_latency:.2f}s")
    console.print(f"  Difference:                +{on_avg_latency - off_avg_latency:.2f}s")

    if on_avg_latency > off_avg_latency:
        console.print(
            f"\n[yellow]⚠ Jev adds ~{on_avg_latency - off_avg_latency:.2f}s latency per request[/yellow]"
        )
    else:
        console.print(f"\n[green]✓ Jev does not add significant latency[/green]")


async def main():
    parser = argparse.ArgumentParser(description="Benchmark Jev ON vs OFF")
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="DuoMind base URL (default: http://127.0.0.1:8000)",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Run in mock mode (no real Jev calls)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Save results to JSON file",
    )

    args = parser.parse_args()

    console.print("[bold cyan]DuoMind Benchmark[/bold cyan]")
    console.print(f"Base URL: {args.base_url}")
    console.print(f"Mock mode: {args.mock}")

    # Check server health
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{args.base_url}/health")
            if response.status_code != 200:
                console.print("[red]✗ Server not healthy[/red]")
                return
        console.print("[green]✓ Server healthy[/green]")
    except Exception as e:
        console.print(f"[red]✗ Cannot connect to server: {e}[/red]")
        return

    # Run with Jev ON
    on_results = await run_benchmark(args.base_url, "on", args.mock)

    # Toggle Jev OFF (would need CLI or API to toggle)
    console.print("\n[yellow]Note: You must manually toggle Jev OFF with 'duomind jev off'[/yellow]")
    input("Press Enter when Jev is OFF...")

    # Run with Jev OFF
    off_results = await run_benchmark(args.base_url, "off", args.mock)

    # Compare
    if on_results and off_results:
        compare_results(on_results, off_results)

    # Save results
    if args.output:
        with open(args.output, "w") as f:
            json.dump(
                {"on": on_results, "off": off_results},
                f,
                indent=2,
            )
        console.print(f"\n[green]✓ Results saved to {args.output}[/green]")


if __name__ == "__main__":
    asyncio.run(main())
