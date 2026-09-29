"""DuoMind CLI with user-friendly commands."""

import json
import os
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

from duomind.config import config
from duomind.utils import (
    delete_jev_key,
    download_hf_file,
    get_binaries_dir,
    get_data_dir,
    get_llama_server_pid_file,
    get_logs_dir,
    get_models_dir,
    get_pid_file,
    load_jev_key,
    mask_key,
    save_jev_key,
)

app = typer.Typer(help="DuoMind - Local AI with Jev classification")
console = Console(force_terminal=True, legacy_windows=False)

# Detect Git Bash / incompatible terminal
IS_GITBASH = os.environ.get("TERM") == "xterm-256color" and sys.platform == "win32"

CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_PROCESS_GROUP = 0x00000200


def ask_confirm(message: str, default: bool = True) -> bool:
    """Fallback confirm for Git Bash compatibility."""
    if IS_GITBASH:
        default_str = "Y/n" if default else "y/N"
        response = input(f"{message} [{default_str}]: ").strip().lower()
        if not response:
            return default
        return response in ("y", "yes")
    return questionary.confirm(message, default=default).ask()


def ask_password(message: str) -> str:
    """Fallback password for Git Bash compatibility."""
    if IS_GITBASH:
        import getpass
        return getpass.getpass(f"{message}: ")
    return questionary.password(message).ask()


def ask_select(message: str, choices: list[str]) -> str:
    """Fallback select for Git Bash compatibility."""
    if IS_GITBASH:
        console.print(f"\n{message}")
        for i, choice in enumerate(choices, 1):
            console.print(f"  {i}. {choice}")
        while True:
            response = input("Enter number: ").strip()
            try:
                idx = int(response) - 1
                if 0 <= idx < len(choices):
                    return choices[idx]
            except ValueError:
                pass
            console.print("[red]Invalid choice. Try again.[/red]")
    return questionary.select(message, choices=choices).ask()


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
            console.print(f"[green]OK[/green] GPU detected: {gpu_name} with {vram_gb:.1f}GB VRAM")

            if vram_gb < 2:
                console.print("[red]WARNING: Less than 2GB VRAM. Models may not fit.[/red]")
        else:
            console.print("[yellow]WARNING: No NVIDIA GPU detected. Will use CPU (slow).[/yellow]")
    except Exception:
        console.print("[yellow]WARNING: Could not detect GPU. Will use CPU (slow).[/yellow]")

    # RAM check
    ram_gb = psutil.virtual_memory().total / (1024**3)
    console.print(f"[green]OK[/green] System RAM: {ram_gb:.1f}GB")
    if ram_gb < 8:
        console.print("[red]WARNING: Less than 8GB RAM. Performance may be poor.[/red]")

    # Disk check
    disk = shutil.disk_usage(get_data_dir().parent)
    free_gb = disk.free / (1024**3)
    console.print(f"[green]OK[/green] Free disk space: {free_gb:.1f}GB")
    if free_gb < 25:
        console.print("[red]WARNING: Less than 25GB free. May not fit multiple models.[/red]")

    # Step 3: Privacy notice
    console.print("\n[bold]Step 3 of 9: Privacy Notice[/bold]")
    console.print(
        "[yellow]IMPORTANT:[/yellow] DuoMind sends your prompts to TypeSafe AI's Jev service\n"
        "for classification. This data leaves your computer and goes to TypeSafe's servers.\n"
        "Your local AI model stays fully local.\n"
    )

    accept_privacy = ask_confirm(
        "Do you understand and accept this?",
        default=False
    )

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

    if ask_confirm("Open these links in your browser?"):
        webbrowser.open("https://typesafe.ai")
        webbrowser.open("https://docs.typesafe.ai")
        webbrowser.open("https://console.typesafe.ai")

    jev_key = ask_password("Enter your Jev API key")
    if not jev_key:
        console.print("[red]Setup cancelled. API key required.[/red]")
        sys.exit(1)

    # Test connection
    console.print("Testing Jev connection...")
    try:
        from typesafe_sdk import Noul, TypeSafeClient

        client = TypeSafeClient(api_key=jev_key)
        client.system_one(
            state={"test": "connection"},
            questions={"test": Noul(instructions="Is this a test?")}
        )
        console.print("[green]OK[/green] Jev connection successful!")

        # Save key
        save_jev_key(jev_key)

        # Save config
        cfg = config.load()
        cfg.jev_enabled = True
        config.save(cfg)

    except Exception as e:
        console.print(f"[red]FAILED[/red] Jev connection failed: {e}")
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
        fit_status = "[green]OK[/green]" if vram_gb >= model["min_vram_gb"] else "[red]NO[/red]"
        table.add_row(
            str(idx),
            model["name"],
            f"{model['size_gb']:.1f}GB",
            f"{model['min_vram_gb']:.1f}GB",
            model["best_for"][:40],
            fit_status
        )

    console.print(table)

    model_choice = ask_select(
        "Choose a model:",
        [f"{i}. {m['name']}" for i, m in enumerate(available_models, 1)]
        + ["Custom (paste Hugging Face URL)"]
    )

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
        "[yellow]WARNING: Automated download not implemented yet.[/yellow]\n"
        "Please download llama-server.exe manually:\n"
        "1. Go to: https://github.com/ggerganov/llama.cpp/releases\n"
        "2. Download the Windows CUDA build (llama-*-bin-win-cuda*.zip)\n"
        f"3. Extract llama-server.exe to: {get_binaries_dir()}\n"
    )

    if not ask_confirm("Have you placed llama-server.exe in the directory?"):
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
        console.print(f"[green]OK[/green] Model downloaded to {model_path}")

        # Save model path to config
        cfg.model_path = str(model_path)
        config.save(cfg)

    except Exception as e:
        console.print(f"[red]FAILED[/red] Download failed: {e}")
        sys.exit(1)

    # Step 8: Start server
    console.print("\n[bold]Step 8 of 9: Start DuoMind Server[/bold]")
    console.print("Starting server for self-test...")

    # Start would happen here, but we'll skip for now
    console.print("[yellow]WARNING: Auto-start not implemented. Use 'duomind start' manually.[/yellow]")

    # Step 9: Final instructions
    console.print("\n[bold green]Step 9 of 9: Setup Complete![/bold green]\n")

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
    cfg = config.load()

    if not cfg.model_path:
        console.print("[red]No model configured. Run 'duomind setup' first.[/red]")
        sys.exit(1)

    if not Path(cfg.model_path).exists():
        console.print(f"[red]Model file not found: {cfg.model_path}[/red]")
        sys.exit(1)

    pid_file = get_pid_file()

    # Check if already running
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text())
            if psutil.pid_exists(pid):
                console.print(f"[yellow]Server already running (PID {pid})[/yellow]")
                return
        except (ValueError, OSError):
            pass
        pid_file.unlink(missing_ok=True)

    console.print("Starting DuoMind server...")

    log_file = get_logs_dir() / "server.log"

    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "duomind.server:app",
        "--host",
        cfg.host,
        "--port",
        str(cfg.port),
    ]

    log_handle = open(log_file, "a")

    if sys.platform == "win32":
        process = subprocess.Popen(
            cmd,
            creationflags=CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP,
            stdout=log_handle,
            stderr=log_handle,
        )
    else:
        process = subprocess.Popen(
            cmd,
            stdout=log_handle,
            stderr=log_handle,
            start_new_session=True,
        )

    log_handle.close()
    pid_file.write_text(str(process.pid))

    base_url = f"http://{cfg.host}:{cfg.port}"
    if not _wait_for_server(base_url, timeout=360, pid=process.pid):
        console.print("[red]Server failed to start. Check logs with 'duomind logs'.[/red]")
        sys.exit(1)

    console.print(f"[green]OK[/green] Server started (PID {process.pid})")
    console.print(f"Base URL: {base_url}/v1")
    console.print(f"Logs: {log_file}")


def _wait_for_server(base_url: str, timeout: int = 360, pid: Optional[int] = None) -> bool:
    """Poll the server health endpoint until it responds 200 or the process dies."""
    import time

    import httpx

    start = time.monotonic()
    while time.monotonic() - start < timeout:
        if pid is not None and not psutil.pid_exists(pid):
            return False

        try:
            response = httpx.get(f"{base_url}/health", timeout=1.0, trust_env=False)
            if response.status_code == 200:
                return True
        except Exception:
            pass

        time.sleep(0.5)

    return False


@app.command()
def stop():
    """Stop DuoMind server."""
    pid_file = get_pid_file()
    llama_pid_file = get_llama_server_pid_file()

    stopped = False

    # Stop DuoMind server
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text())
            process = psutil.Process(pid)
            process.terminate()
            try:
                process.wait(timeout=5)
            except psutil.TimeoutExpired:
                process.kill()
            stopped = True
        except psutil.NoSuchProcess:
            pass
        except Exception as e:
            console.print(f"[red]Failed to stop server: {e}[/red]")
        pid_file.unlink(missing_ok=True)

    # Stop llama-server (detached child process)
    if llama_pid_file.exists():
        try:
            pid = int(llama_pid_file.read_text())
            if psutil.pid_exists(pid):
                if sys.platform == "win32":
                    subprocess.run(
                        ["taskkill", "/F", "/PID", str(pid)],
                        capture_output=True,
                    )
                else:
                    try:
                        psutil.Process(pid).terminate()
                    except psutil.NoSuchProcess:
                        pass
                stopped = True
        except Exception as e:
            console.print(f"[red]Failed to stop llama-server: {e}[/red]")
        llama_pid_file.unlink(missing_ok=True)

    # Kill any orphaned llama-server processes not tracked by the PID file
    for proc in psutil.process_iter(["name", "pid"]):
        try:
            name = (proc.info.get("name") or "").lower()
            if name.startswith("llama-server"):
                if sys.platform == "win32":
                    subprocess.run(
                        ["taskkill", "/F", "/PID", str(proc.info["pid"])],
                        capture_output=True,
                    )
                else:
                    proc.terminate()
                stopped = True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if stopped:
        console.print("[green]OK[/green] Server stopped")
    else:
        console.print("[yellow]Server is not running (no PID files)[/yellow]")


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
            from typesafe_sdk import Noul, TypeSafeClient
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
        status = "[green]OK[/green]" if passed else "[red]FAIL[/red]"
        console.print(f"{status} {name}")


@app.command()
def uninstall():
    """Remove all DuoMind data."""
    data_dir = get_data_dir()

    console.print(f"[red]This will delete:[/red]\n{data_dir}\n")

    if ask_confirm("Are you sure?", default=False):
        shutil.rmtree(data_dir, ignore_errors=True)
        delete_jev_key()
        console.print("[green]OK[/green] DuoMind uninstalled")


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
