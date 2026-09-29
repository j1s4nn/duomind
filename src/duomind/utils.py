"""Utility functions for DuoMind."""

import hashlib
import io
import json
import logging
import sys
import tarfile
import zipfile
from pathlib import Path
from typing import List, Optional

import keyring
from huggingface_hub import hf_hub_download
from platformdirs import user_data_dir

logger = logging.getLogger(__name__)


def get_data_dir() -> Path:
    """Get DuoMind data directory in %LOCALAPPDATA%."""
    data_dir = Path(user_data_dir("duomind", appauthor=False))
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def get_config_path() -> Path:
    """Get config.toml path."""
    return get_data_dir() / "config.toml"


def get_models_dir() -> Path:
    """Get models directory."""
    models_dir = get_data_dir() / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    return models_dir


def get_binaries_dir() -> Path:
    """Get binaries directory."""
    binaries_dir = get_data_dir() / "binaries"
    binaries_dir.mkdir(parents=True, exist_ok=True)
    return binaries_dir


def get_cache_dir() -> Path:
    """Get cache directory."""
    cache_dir = get_data_dir() / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def get_logs_dir() -> Path:
    """Get logs directory."""
    logs_dir = get_data_dir() / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir


def get_pid_file() -> Path:
    """Get PID file path for the DuoMind server."""
    return get_data_dir() / "duomind.pid"


def get_llama_server_pid_file() -> Path:
    """Get PID file path for the llama-server process."""
    return get_data_dir() / "llama-server.pid"


def get_llama_server_binary() -> Path:
    """Get the platform-appropriate llama-server binary path."""
    name = "llama-server.exe" if sys.platform == "win32" else "llama-server"
    return get_binaries_dir() / name


def _llama_asset_keywords() -> List[str]:
    """Asset-name keywords for the current platform (best-first)."""
    if sys.platform == "win32":
        return ["win-cuda", "win-vulkan", "win-cpu", "win-arm64"]
    if sys.platform == "darwin":
        return ["macos-arm64", "macos-x64"]
    return ["ubuntu-x64", "linux-x64", "manylinux"]


def download_llama_server() -> Path:
    """Download and extract the llama-server binary for this platform.

    Uses the GitHub releases API (ggml-org/llama.cpp, falling back to
    ggerganov/llama.cpp). Raises RuntimeError with manual instructions on any
    failure so the CLI can guide the user.
    """
    import httpx

    binary = get_llama_server_binary()
    if binary.exists():
        return binary

    binaries_dir = get_binaries_dir()
    release = None

    for repo in ("ggml-org/llama.cpp", "ggerganov/llama.cpp"):
        api_url = f"https://api.github.com/repos/{repo}/releases/latest"
        try:
            resp = httpx.get(
                api_url,
                headers={"Accept": "application/vnd.github+json"},
                timeout=30.0,
                follow_redirects=True,
                trust_env=False,
            )
            resp.raise_for_status()
            release = resp.json()
            break
        except Exception:
            continue

    if not release:
        raise RuntimeError("Could not reach the llama.cpp GitHub releases API.")

    keywords = _llama_asset_keywords()
    assets = release.get("assets", [])
    candidates = [
        a for a in assets
        if any(k in a["name"].lower() for k in keywords)
        and (a["name"].lower().endswith(".zip") or a["name"].lower().endswith(".tar.gz"))
    ]
    if not candidates:
        # Broadest fallback: any archive asset.
        candidates = [
            a for a in assets
            if a["name"].lower().endswith(".zip") or a["name"].lower().endswith(".tar.gz")
        ]

    last_error: Optional[Exception] = None
    for asset in candidates:
        url = asset.get("browser_download_url")
        if not url:
            continue
        try:
            with httpx.stream(
                "GET", url, timeout=120.0, follow_redirects=True, trust_env=False
            ) as resp:
                resp.raise_for_status()
                chunks = []
                for chunk in resp.iter_bytes():
                    chunks.append(chunk)
            data = b"".join(chunks)
            _extract_llama_server(data, asset["name"], binaries_dir)
            if binary.exists():
                return binary
        except Exception as e:  # noqa: BLE001 - try next asset
            last_error = e
            continue

    raise RuntimeError(
        "Automated llama-server download failed"
        + (f": {last_error}" if last_error else "")
    )


def _extract_llama_server(data: bytes, asset_name: str, dest_dir: Path) -> None:
    """Extract the llama-server binary from a downloaded archive."""
    name = asset_name.lower()
    target = "llama-server.exe" if sys.platform == "win32" else "llama-server"

    if name.endswith(".tar.gz"):
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
            for member in tf.getmembers():
                if member.name.endswith(target):
                    f = tf.extractfile(member)
                    if f:
                        dest = dest_dir / Path(member.name).name
                        dest.write_bytes(f.read())
                        _make_executable(dest)
                        return
    else:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for info in zf.infolist():
                if info.filename.endswith(target):
                    dest = dest_dir / Path(info.filename).name
                    dest.write_bytes(zf.read(info))
                    _make_executable(dest)
                    return

    raise FileNotFoundError(f"{target} not found in {asset_name}")


def _make_executable(path: Path) -> None:
    """Mark a binary executable on POSIX systems."""
    if sys.platform != "win32":
        path.chmod(0o755)


def download_hf_file(
    repo_id: str, filename: str, dest_dir: Path, show_progress: bool = True
) -> Path:
    """
    Download file from Hugging Face with progress bar.

    Args:
        repo_id: HF repo like "bartowski/phi-4-GGUF"
        filename: File to download like "phi-4-Q4_K_M.gguf"
        dest_dir: Destination directory
        show_progress: Show rich progress bar

    Returns:
        Path to downloaded file
    """
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Use HF's resumable download
    if show_progress:
        # hf_hub_download has its own progress bar
        downloaded_path = hf_hub_download(
            repo_id=repo_id,
            filename=filename,
            cache_dir=str(dest_dir),
            local_dir=str(dest_dir),
            local_dir_use_symlinks=False,
        )
    else:
        downloaded_path = hf_hub_download(
            repo_id=repo_id,
            filename=filename,
            cache_dir=str(dest_dir),
            local_dir=str(dest_dir),
            local_dir_use_symlinks=False,
        )

    return Path(downloaded_path)


def save_jev_key(api_key: str) -> None:
    """Save Jev API key to system keyring."""
    try:
        keyring.set_password("duomind", "jev_api_key", api_key)
        logger.info("Jev API key saved to system keyring")
    except Exception as e:
        logger.warning(f"Failed to save to keyring: {e}")
        raise


def load_jev_key() -> Optional[str]:
    """Load Jev API key from system keyring."""
    try:
        return keyring.get_password("duomind", "jev_api_key")
    except Exception as e:
        logger.warning(f"Failed to load from keyring: {e}")
        return None


def delete_jev_key() -> None:
    """Delete Jev API key from system keyring."""
    try:
        keyring.delete_password("duomind", "jev_api_key")
        logger.info("Jev API key deleted from system keyring")
    except Exception:
        pass


def mask_key(key: str) -> str:
    """Mask API key for logging (show first 4 and last 4 chars)."""
    if not key or len(key) < 12:
        return "****"
    return f"{key[:4]}...{key[-4:]}"


def hash_state(state: dict) -> str:
    """Generate SHA256 hash of state for caching."""
    state_str = json.dumps(state, sort_keys=True)
    return hashlib.sha256(state_str.encode()).hexdigest()
