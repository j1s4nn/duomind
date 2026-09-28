"""DuoMind CLI with user-friendly commands."""

import json
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import Optional

import psutil
import questionary
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from duomind.config import config
from duomind.utils import (
    delete_jev_key,
    download_hf_file,
    get_binaries_dir,
    get_data_dir,
    get_logs_dir,
    get_models_dir,
    get_pid_file,
    load_jev_key,
    mask_key,
    save_jev_key,
)

app = typer.Typer(help="DuoMind - Local AI with Jev classification")
console = Console()


@app.command()
def setup():
    """Interactive setup wizard for first-time users."""
    console.print(Panel.fit(
        "[bold cyan]Welcome to DuoMind![/bold cyan]\n\n"
        "DuoMind pairs a local AI model with TypeSafe AI's Jev for smarter responses.\n"
        "Let's get you set up in 9 easy steps.",
        border_style="cyan"
    ))

    # Step 1: Welcome (done above)

    # Step 2: Hardware check
    console.print("\n[bold]Step 2 of 9: Hardware Check[/bold]")

    # GPU check
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            gpu_info = result.stdout.strip().split(",")
            gpu_name = gpu_info[0].strip()
            vram_mb = int(gpu_info[1].strip().split()[0])
            vram_gb = vram_mb / 1024
            console.print(f"✓ GPU detected: {gpu_name} with {vram_gb:.1f}GB VRAM")

            if vram_gb < 2:
                console.print("[red]⚠ WARNING: Less than 2GB VRAM. Models may not fit.[/red]")
        else:
            console.print("[yellow]⚠ No NVIDIA GPU detected. Will use CPU (slow).[/yellow]")
    except Exception:
        console.print("[yellow]⚠ Could not detect GPU. Will use CPU (slow).[/yellow]")

    # RAM check
    ram_gb = psutil.virtual_memory().total / (1024**3)
    console.print(f"✓ System RAM: {ram_gb:.1f}GB")
    if ram_gb < 8:
        console.print("[red]⚠ WARNING: Less than 8GB RAM. Performance may be poor.[/red]")

    # Disk check
    disk = shutil.disk_usage(get_data_dir().parent)
    free_gb = disk.free / (1024**3)
    console.print(f"✓ Free disk space: {free_gb:.1f}GB")
    if free_gb < 25:
        console.print("[red]⚠ WARNING: Less than 25GB free. May not fit multiple models.[/red]")

    # Step 3: Privacy notice
    console.print("\n[bold]Step 3 of 9: Privacy Notice[/bold]")
    console.print(
        "[yellow]IMPORTANT:[/yellow] DuoMind sends your prompts to TypeSafe AI's Jev service\n"
        "for classification. This data leaves your computer and goes to TypeSafe's servers.\n"
        "Your local AI model stays fully local.\n"
    )

    accept_privacy = questionary.confirm(
        "Do you understand and accept this?",
        default=False
    ).ask()

    if not accept_privacy:
        console.print("[red]Setup cancelled. DuoMind requires Jev to function.[/red]")
        sys.exit(1)

    # Step 4: Connect to Jev
    console.print("\n[bold]Step 4 of 9: Connect to Jev[/bold]")
    console.print(
        "Jev is TypeSafe AI's classification service. It's very fast and cheap.\n"
        "You need a Jev API key to continue.\n"
    )

    console.print("📚 Learn more: https://typesafe.ai")
    console.print("📖 Documentation: https://docs.typesafe.ai")
    console.print("🔑 Get API key: https://console.typesafe.ai")

    if questionary.confirm("Open these links in your browser?").ask():
        webbrowser.open("https://typesafe.ai")
        webbrowser.open("https://docs.typesafe.ai")
        webbrowser.open("https://console.typesafe.ai")

    jev_key = questionary.password("Enter your Jev API key:").ask()
    if not jev_key:
        console.print("[red]Setup cancelled. API key required.[/red]")
        sys.exit(1)

    # Test connection
    console.print("Testing Jev connection...")
    try:
        from typesafe_sdk import TypeSafeClient, Noul

        client = TypeSafeClient(api_key=jev_key)
        response = client.system_one(
            state={"test": "connection"},
            questions={"test": Noul(instructions="Is this a test?")}
        )
        console.print("[green]✓ Jev connection successful![/green]")

        # Save key
        save_jev_key(jev_key)

        # Save config
        cfg = config.load()
        cfg.jev_enabled = True
        config.save(cfg)

    except Exception as e:
        console.print(f"[red]✗ Jev connection failed: {e}[/red]")
        console.print("Please check your API key and try again.")
        sys.exit(1)

    # Step 5: Model selection
    console.print("\n[bold]Step 5 of 9: Choose Your AI Model[/bold]")
    console.print(
        "DuoMind works with small local models. Pick one that fits your GPU:\n"
    )

    # Load models.json
    models_json_path = Path(__file__).parent / "models.json"
    with open(models_json_path) as f:
        available_models = json.load(f)

    # Create table
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("#", style="dim")
    table.add_column("Name")
    table.add_column("Size")
    table.add_column("VRAM")
    table.add_column("Best For")
    table.add_column("Fit?")

    for idx, model in enumerate(available_models, 1):
        fit_status = "✓" if vram_gb >= model["min_vram_gb"] else "[red]✗[/red]"
        table.add_row(
            str(idx),
            model["name"],
            f"{model['size_gb']:.1f}GB",
            f"{model['min_vram_gb']:.1f}GB",
            model["best_for"][:40],
            fit_status
        )

    console.print(table)

    model_choice = questionary.select(
        "Choose a model:",
        choices=[f"{i}. {m['name']}" for i, m in enumerate(available_models, 1)]
        + ["Custom (paste Hugging Face URL)"]
    ).ask()

    if model_choice.startswith("Custom"):
        console.print("[yellow]Custom model selection not implemented yet. Using model 1.[/yellow]")
        selected_model = available_models[0]
    else:
        model_idx = int(model_choice.split(".")[0]) - 1
        selected_model = available_models[model_idx]

    # Step 6: Download llama-server
    console.print("\n[bold]Step 6 of 9: Download llama-server[/bold]")
    console.print("Downloading llama.cpp inference engine...")

    # For now, tell user to download manually
    console.print(
        "[yellow]⚠ Automated download not implemented yet.[/yellow]\n"
        "Please download llama-server.exe manually:\n"
        "1. Go to: https://github.com/ggerganov/llama.cpp/releases\n"
        "2. Download the Windows CUDA build (llama-*-bin-win-cuda*.zip)\n"
        f"3. Extract llama-server.exe to: {get_binaries_dir()}\n"
    )

    if not questionary.confirm("Have you placed llama-server.exe in the directory?").ask():
        console.print("[red]Setup cannot continue without llama-server.exe[/red]")
        sys.exit(1)

    # Step 7: Download model
    console.print("\n[bold]Step 7 of 9: Download AI Model[/bold]")
    console.print(f"Downloading {selected_model['name']} ({selected_model['size_gb']:.1f}GB)...")
    console.print("This may take several minutes depending on your internet speed.\n")

    try:
        model_path = download_hf_file(
            repo_id=selected_model["hf_repo"],
            filename=selected_model["filename"],
            dest_dir=get_models_dir(),
            show_progress=True
        )
        console.print(f"[green]✓ Model downloaded to {model_path}[/green]")

        # Save model path to config
        cfg.model_path = str(model_path)
        config.save(cfg)

    except Exception as e:
        console.print(f"[red]✗ Download failed: {e}[/red]")
        sys.exit(1)

    # Step 8: Start server
    console.print("\n[bold]Step 8 of 9: Start DuoMind Server[/bold]")
    console.print("Starting server for self-test...")

    # Start would happen here, but we'll skip for now
    console.print("[yellow]⚠ Auto-start not implemented. Use 'duomind start' manually.[/yellow]")

    # Step 9: Final instructions
    console.print("\n[bold green]Step 9 of 9: Setup Complete! 🎉[/bold green]\n")

    console.print(Panel(
        f"[bold]Your DuoMind server is ready![/bold]\n\n"
        f"Base URL: http://127.0.0.1:{cfg.port}/v1\n"
        f"Model: {selected_model['name']}\n"
        f"Jev: Enabled\n\n"
        f"[bold cyan]To start DuoMind:[/bold cyan]\n"
        f"  duomind start\n\n"
        f"[bold cyan]For Cline/Kilo Code:[/bold cyan]\n"
        f"  API Provider: OpenAI Compatible\n"
        f"  Base URL: http://127.0.0.1:{cfg.port}/v1\n"
        f"  API Key: (leave blank)\n"
        f"  Model: {selected_model['id']}\n",
        border_style="green"
    ))


@app.command()
def start():
    """Start DuoMind server in background."""
    console.print("Starting DuoMind server...")
    console.print("[red]Not implemented yet. Use: python -m uvicorn duomind.server:app[/red]")


@app.command()
def stop():
    """Stop DuoMind server."""
    pid_file = get_pid_file()

    if not pid_file.exists():
        console.print("[yellow]Server is not running (no PID file)[/yellow]")
        return

    try:
        pid = int(pid_file.read_text())
        process = psutil.Process(pid)
        process.terminate()
        process.wait(timeout=5)
        pid_file.unlink()
        console.print("[green]✓ Server stopped[/green]")
    except psutil.NoSuchProcess:
        pid_file.unlink()
        console.print("[yellow]Server was not running (stale PID file removed)[/yellow]")
    except Exception as e:
        console.print(f"[red]Failed to stop server: {e}[/red]")


@app.command()
def status():
    """Show DuoMind status."""
    cfg = config.load()

    table = Table(show_header=False)
    table.add_column("Setting", style="cyan")
    table.add_column("Value")

    table.add_row("Backend", cfg.llm_backend)
    table.add_row("Model", cfg.model_path or "Not configured")
    table.add_row("Jev", "Enabled" if cfg.jev_enabled else "Disabled")

    jev_key = load_jev_key()
    if jev_key:
        table.add_row("Jev API Key", mask_key(jev_key))

    table.add_row("Host", f"{cfg.host}:{cfg.port}")

    pid_file = get_pid_file()
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text())
            if psutil.pid_exists(pid):
                table.add_row("Server", f"[green]Running (PID {pid})[/green]")
            else:
                table.add_row("Server", "[red]Not running (stale PID)[/red]")
        except Exception:
            table.add_row("Server", "[yellow]Unknown[/yellow]")
    else:
        table.add_row("Server", "[red]Not running[/red]")

    console.print(table)


@app.command()
def logs():
    """Show server logs."""
    log_file = get_logs_dir() / "server.log"
    if not log_file.exists():
        console.print("[yellow]No logs found[/yellow]")
        return

    console.print(log_file.read_text())


@app.command()
def doctor():
    """Run diagnostics."""
    console.print("[bold]Running diagnostics...[/bold]\n")

    checks = []

    # GPU check
    try:
        result = subprocess.run(
            ["nvidia-smi"], capture_output=True, timeout=5
        )
        checks.append(("GPU", result.returncode == 0))
    except Exception:
        checks.append(("GPU", False))

    # Jev connectivity
    jev_key = load_jev_key()
    if jev_key:
        try:
            from typesafe_sdk import TypeSafeClient, Noul
            client = TypeSafeClient(api_key=jev_key)
            client.system_one(
                state={"test": "health"},
                questions={"test": Noul(instructions="Is this a test?")}
            )
            checks.append(("Jev Connection", True))
        except Exception:
            checks.append(("Jev Connection", False))
    else:
        checks.append(("Jev API Key", False))

    # Display results
    for name, passed in checks:
        status = "[green]✓[/green]" if passed else "[red]✗[/red]"
        console.print(f"{status} {name}")


@app.command()
def uninstall():
    """Remove all DuoMind data."""
    data_dir = get_data_dir()

    console.print(f"[red]This will delete:[/red]\n{data_dir}\n")

    if questionary.confirm("Are you sure?", default=False).ask():
        shutil.rmtree(data_dir, ignore_errors=True)
        delete_jev_key()
        console.print("[green]✓ DuoMind uninstalled[/green]")


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context):
    """DuoMind CLI - run without arguments for menu."""
    if ctx.invoked_subcommand is None:
        choice = questionary.select(
            "What would you like to do?",
            choices=[
                "Setup DuoMind (first time)",
                "Start server",
                "Stop server",
                "Check status",
                "View logs",
                "Run diagnostics",
                "Uninstall",
                "Exit"
            ]
        ).ask()

        if choice == "Setup DuoMind (first time)":
            setup()
        elif choice == "Start server":
            start()
        elif choice == "Stop server":
            stop()
        elif choice == "Check status":
            status()
        elif choice == "View logs":
            logs()
        elif choice == "Run diagnostics":
            doctor()
        elif choice == "Uninstall":
            uninstall()


if __name__ == "__main__":
    app()
