# Performance Benchmark — Instructions

This folder contains a benchmark that runs the **same prompts twice** — once
with **Jev on** and once with **Jev off** — so you can measure the real
difference Jev makes for your model. Every run automatically saves the
statistics into `performance/results/`.

## What the statistics include

Each saved file `performance/results/benchmark_<timestamp>.json` records, for
every request and every mode:

- **Prompt** — the exact text sent to the model
- **Tokens** — `prompt`, `completion`, and `total` token counts
- **Speed** — `latency_seconds` and `tokens_per_second`
- **Jev** — whether Jev was on and how many decisions it made
- **Output** — the model's full response (for comparing quality)

A `summary` section aggregates averages per mode (Jev on vs off).

## Requirements

1. **DuoMind is installed** in your virtual environment:
   ```powershell
   .\.venv\Scripts\Activate.ps1
   pip install -e .
   ```

2. **The server is running** (started with Jev enabled, which is the default):
   ```powershell
   duomind start
   ```
   The benchmark toggles Jev by editing `config.toml`, which the running
   server reads on every request — no restart is needed.

## Usage

Run from the project root:

```powershell
python performance/benchmark.py
```

### Options

| Flag | Description | Default |
|------|-------------|---------|
| `--base-url URL` | DuoMind server address | `http://127.0.0.1:8000` |
| `--runs N` | Times to run each prompt per mode | `1` |
| `--output DIR` | Folder to save the statistics | `performance/results` |

Examples:

```powershell
# Default run (5 prompts, once per mode)
python performance/benchmark.py

# More samples for a stable average
python performance/benchmark.py --runs 3

# Custom server port
python performance/benchmark.py --base-url http://127.0.0.1:9000
```

## Output

The script prints a comparison table (average latency, tokens-per-second, and
token totals for Jev on vs off) and saves the full JSON statistics to:

```
performance/results/benchmark_<timestamp>.json
```

Each request also logs a `PERF` line in the server log
(`duomind logs`) with token counts and speed for both the LLM and Jev.

## Notes

- Jev is restored to **on** after the benchmark finishes (the safe default).
- Token counts use a rough `4 chars/token` estimate, matching the server's
  built-in `usage` reporting.
- If you started the server with Jev disabled, `duomind jev on` needs a server
  restart before Jev will actually be used; the benchmark assumes the server
  was started normally.
