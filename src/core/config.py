"""Central configuration.

WHY this exists: CLAUDE.md forbids hard-coded secrets and forbids printing them.
Routing every setting through one pydantic-settings object means there is exactly
one place a key can enter the process, and `safe_dump()` is the only sanctioned way
to log configuration — it never emits a secret value.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Corpus root. READ-ONLY — nothing in this project may write beneath it.
CORPUS_ROOT = REPO_ROOT / "data" / "corpus" / "Ashen_Era_Archive"


class Settings(BaseSettings):
    """Runtime settings, populated from the environment and `.env`."""

    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- providers -------------------------------------------------------
    openrouter_api_key: str | None = None
    gemini_api_key: str | None = None
    aws_region: str = "us-east-1"
    aws_profile: str | None = None

    # --- model routing: two tiers only, per ADR-001 ----------------------
    llm_model_synthesis: str = "deepseek/deepseek-chat"
    llm_model_cheap: str = "meta-llama/llama-3.3-70b-instruct:free"
    llm_model_vision: str = "qwen/qwen2.5-vl-72b-instruct:free"

    # --- stores ----------------------------------------------------------
    qdrant_path: Path = REPO_ROOT / "data" / "index" / "qdrant"
    qdrant_url: str | None = None
    cache_db: Path = REPO_ROOT / "data" / "cache" / "llm_cache.sqlite"
    trace_db: Path = REPO_ROOT / "data" / "cache" / "traces.sqlite"
    index_dir: Path = REPO_ROOT / "data" / "index"
    assets_dir: Path = REPO_ROOT / "data" / "assets"

    # --- embeddings: local-first, no Voyage key required -----------------
    embed_backend: Literal["local", "bedrock"] = "local"
    embed_model_local: str = "BAAI/bge-small-en-v1.5"
    rerank_model_local: str = "Xenova/ms-marco-MiniLM-L-6-v2"

    # --- budgets (A3 stop rules) -----------------------------------------
    max_steps: int = Field(default=6, ge=1)
    max_tokens_per_query: int = Field(default=60_000, ge=1)
    max_wall_ms: int = Field(default=25_000, ge=1)

    @property
    def corpus_root(self) -> Path:
        return CORPUS_ROOT

    def configured_providers(self) -> list[str]:
        """Which providers have credentials — names only, never values."""
        present = []
        if self.openrouter_api_key:
            present.append("openrouter")
        if self.gemini_api_key:
            present.append("gemini")
        if self.aws_profile or Path.home().joinpath(".aws", "credentials").exists():
            present.append("bedrock")
        return present

    def safe_dump(self) -> dict[str, object]:
        """Loggable view of the config. Secrets appear as booleans, never as values."""
        data = self.model_dump()
        for key in list(data):
            if key.endswith("_api_key"):
                data[key] = bool(data[key])
        data["configured_providers"] = self.configured_providers()
        return data


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
