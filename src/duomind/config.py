"""Configuration management for DuoMind."""

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

from typing import Optional

import tomli_w
from pydantic import BaseModel

from duomind.utils import get_config_path, load_jev_key


class DuoMindConfig(BaseModel):
    """DuoMind configuration model."""

    # Jev settings
    jev_enabled: bool = True
    jev_base_url: Optional[str] = None  # Use SDK default
    jev_model: str = "jev-latest"
    confidence_threshold: float = 0.6

    # LLM backend settings
    llm_backend: str = "llamacpp"  # llamacpp or ollama
    model_path: Optional[str] = None

    # Server settings
    host: str = "127.0.0.1"
    port: int = 8000
    api_key: Optional[str] = None  # Optional bearer token
    context_size: int = 8192  # llama.cpp context window size

    # Orchestration settings
    max_mid_checkpoints: int = 3
    mid_segment_tokens: int = 160
    mid_steering_enabled: bool = False
    post_steering_enabled: bool = False
    fallback_mode: str = "rules"  # rules or simple

    # Steering skill settings
    system_prompt: Optional[str] = None  # Override the default steering skill
    tools_enabled: bool = True  # Allow OpenAI-compatible tool calling


class Config:
    """Config manager with file persistence."""

    def __init__(self):
        self.path = get_config_path()
        self.config: Optional[DuoMindConfig] = None

    def load(self) -> DuoMindConfig:
        """Load config from file, create default if not exists."""
        if not self.path.exists():
            self.config = DuoMindConfig()
            return self.config

        try:
            with open(self.path, "rb") as f:
                data = tomllib.load(f)
            self.config = DuoMindConfig(**data)
            return self.config
        except Exception as e:
            raise RuntimeError(f"Failed to load config from {self.path}: {e}")

    def save(self, config: Optional[DuoMindConfig] = None) -> None:
        """Save config to file."""
        if config:
            self.config = config

        if not self.config:
            raise RuntimeError("No config to save")

        self.path.parent.mkdir(parents=True, exist_ok=True)

        # Filter out None values - TOML can't serialize them
        data = {k: v for k, v in self.config.model_dump().items() if v is not None}

        with open(self.path, "wb") as f:
            tomli_w.dump(data, f)

    def get_jev_key(self) -> Optional[str]:
        """Get Jev API key from keyring."""
        return load_jev_key()

    def update(self, **kwargs) -> None:
        """Update config fields and save."""
        if not self.config:
            self.load()

        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)

        self.save()


# Global config instance
config = Config()
