"""Utility functions for DuoMind."""

import hashlib
import logging
from pathlib import Path
from typing import Optional

import keyring
from huggingface_hub import hf_hub_download
from platformdirs import user_data_dir
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)

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
    """Get PID file path."""
    return get_data_dir() / "duomind.pid"


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
    import json
    state_str = json.dumps(state, sort_keys=True)
    return hashlib.sha256(state_str.encode()).hexdigest()
