"""Embeddings behind one interface, local by default.

WHY local-first (ADR-004): the master plan assumed Voyage, and we have no Voyage key.
The decisive property is that a judge reproduces retrieval from a clean clone with
**no credentials at all**.

COST, measured rather than guessed: a first benchmark on short strings suggested ~79
texts/sec, implying a 25-second full index. That number was wrong by two orders of
magnitude - real corpus chunks average ~1,950 characters, and single-process
throughput on those is **1.6 chunks/sec**, so the corpus takes ~20 minutes serially.
Hence `parallel=`. Benchmark on the actual payload, not on a convenient string.

WHY a protocol rather than a function: "local dense vs Bedrock dense" is an ablation row.
Swapping the embedder must be a config change, not an edit, or the comparison never gets
run honestly.

WHY the query and document prefixes: BGE is trained asymmetrically. Embedding a question
the same way as a passage measurably costs recall, and the fix is two words of prefix.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol

from src.core.config import Settings, get_settings

#: BGE-small was trained with this instruction on the query side only.
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


class Embedder(Protocol):
    name: str
    dimensions: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class LocalEmbedder:
    """fastembed + ONNX on CPU. No key, no network at query time, no per-call cost."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.name = self.settings.embed_model_local
        self._model = None
        self.dimensions = 384  # BAAI/bge-small-en-v1.5

    def _load(self):
        if self._model is None:
            # Keep the ONNX weights inside the project rather than the system temp
            # directory, which Windows clears - a judge should not be re-downloading the
            # model because their machine tidied up overnight.
            cache = self.settings.index_dir.parent / "models"
            cache.mkdir(parents=True, exist_ok=True)
            os.environ.setdefault("FASTEMBED_CACHE_PATH", str(cache))

            from fastembed import TextEmbedding

            self._model = TextEmbedding(self.name, cache_dir=str(cache))
        return self._model

    def embed_documents(self, texts: list[str], parallel: int | None = None) -> list[list[float]]:
        # Real corpus chunks are ~1,950 characters, not the short strings a naive
        # benchmark uses: measured single-process throughput is 1.6 chunks/sec, so the
        # full corpus takes ~20 minutes serially. Multiprocessing is the difference
        # between re-indexing being a coffee break and being a decision.
        return [list(map(float, v)) for v in self._load().embed(texts, parallel=parallel)]

    def embed_query(self, text: str) -> list[float]:
        return next(iter(self.embed_documents([QUERY_PREFIX + text])))


class BedrockEmbedder:
    """AWS Titan v2, the alternate ablation row. Requires credentials and model access."""

    def __init__(
        self,
        settings: Settings | None = None,
        model: str = "amazon.titan-embed-text-v2:0",
    ) -> None:
        self.settings = settings or get_settings()
        self.name = model
        self.dimensions = 1024
        self._client = None

    def _runtime(self):
        if self._client is None:
            import boto3

            session = boto3.Session(
                profile_name=self.settings.aws_profile or None,
                region_name=self.settings.aws_region,
            )
            self._client = session.client("bedrock-runtime")
        return self._client

    def _embed_one(self, text: str) -> list[float]:
        import json

        from src.core.retry import RetryPolicy, call_with_retry

        def call() -> list[float]:
            response = self._runtime().invoke_model(
                modelId=self.name,
                body=json.dumps({"inputText": text, "dimensions": self.dimensions}),
            )
            return json.loads(response["body"].read())["embedding"]

        return call_with_retry(call, policy=RetryPolicy(max_attempts=4), description="titan")

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed_one(text)


def get_embedder(settings: Settings | None = None) -> Embedder:
    settings = settings or get_settings()
    if settings.embed_backend == "bedrock":
        return BedrockEmbedder(settings)
    return LocalEmbedder(settings)


def model_cache_dir(settings: Settings | None = None) -> Path:
    settings = settings or get_settings()
    return settings.index_dir.parent / "models"
