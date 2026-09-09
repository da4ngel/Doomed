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
    openai_api_key: str | None = None
    gemini_api_key: str | None = None
    aws_region: str = "us-east-1"
    aws_profile: str | None = None

    # --- model routing: two tiers only, per ADR-001 ----------------------
    llm_model_synthesis: str = "deepseek/deepseek-chat"
    llm_model_vision: str = "qwen/qwen2.5-vl-72b-instruct:free"

    # --- stores ----------------------------------------------------------
    qdrant_path: Path = REPO_ROOT / "data" / "index" / "qdrant"
    qdrant_url: str | None = None
    #: Which Qdrant collection to read and write. Configurable so an experiment can
    #: build a second index without destroying the one the API is serving - the chunk
    #: size sweep needs three indexes and must not cost us the working one.
    qdrant_collection: str = "ashen_chunks"
    cache_db: Path = REPO_ROOT / "data" / "cache" / "llm_cache.sqlite"
    trace_db: Path = REPO_ROOT / "data" / "cache" / "traces.sqlite"
    index_dir: Path = REPO_ROOT / "data" / "index"
    assets_dir: Path = REPO_ROOT / "data" / "assets"

    # --- embeddings: local-first, no Voyage key required -----------------
    embed_backend: Literal["local", "bedrock"] = "local"
    embed_model_local: str = "BAAI/bge-small-en-v1.5"
    rerank_model_local: str = "Xenova/ms-marco-MiniLM-L-6-v2"

    # --- budgets (A3 stop rules) -----------------------------------------
    # The UI submits six steps normally and twelve only when Deep Semantic Search is
    # selected. Keeping the server ceiling at twelve makes that opt-in meaningful while
    # ChatRequest.budget remains the per-request guard.
    max_steps: int = Field(default=12, ge=1)
    # Sized from a measured 20-question run, not guessed. A single-lookup 1A question
    # finishes in ~5s and one LLM call; a multi-hop 1B question runs A2/A3 three times
    # over and merges 16-30 chunks, and was observed at 20-27s. The old 25s ceiling cut
    # those off mid-composition - "Investigation stopped: LLM deadline exceeded" - and
    # the old 60,000-token allowance ran out on the same questions. Both limits landed
    # on 1B and 1C, which are the spine and its contradiction loop, while 1A never
    # noticed. A budget that only fits the easy half of the corpus is mis-set.
    max_tokens_per_query: int = Field(default=200_000, ge=1)
    max_wall_ms: int = Field(default=90_000, ge=1)

    @property
    def corpus_root(self) -> Path:
        return CORPUS_ROOT

    def configured_providers(self) -> list[str]:
        """Which providers have credentials — names only, never values."""
        present = []
        if self.openrouter_api_key:
            present.append("openrouter")
        if self.openai_api_key:
            present.append("openai")
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
