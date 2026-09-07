"""One LLM interface, three thin provider adapters, with a fallback chain.

WHY a fallback chain rather than a single provider: this project runs on free tiers
that rate-limit, and the demo is recorded live. If OpenRouter is throttled at 14:00 on
submission day, the run should degrade to Gemini or Bedrock and *say so* in the usage
record (`fallback_used`), not fail. The chain is two tiers deep by design - CLAUDE.md
forbids building a routing engine, and a list of providers tried in order is something
a team member can explain under questioning in one sentence.

WHY images are part of this module rather than a separate one: the vision call is the
single highest-value call in the system (roughly 55 of the 85 corpus images yield zero
OCR characters, so a VLM is the only path to those answers). It gets the same caching,
the same backoff and the same usage accounting as every text call, because the cost and
the 429 risk are identical.

Every call here goes through core.retry and core.cache. That is not a convention, it is
the CLAUDE.md rule with no sanctioned exception.
"""

from __future__ import annotations

import base64
import json
import logging
import mimetypes
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

import httpx

from src.core.cache import ResponseCache
from src.core.config import Settings, get_settings
from src.core.retry import CircuitBreaker, RetryPolicy, call_with_retry

log = logging.getLogger(__name__)

Role = Literal["system", "user", "assistant"]

#: Rough public per-million-token prices, USD. Only used to populate `cost_usd` in the
#: usage record so the report can quote a cost per query. Free models are 0.0.
_PRICES: dict[str, tuple[float, float]] = {
    "deepseek/deepseek-chat": (0.27, 1.10),
    "anthropic.claude-3-5-sonnet-20241022-v2:0": (3.00, 15.00),
    "gemini-2.5-flash": (0.30, 2.50),
}


@dataclass
class LLMResponse:
    text: str
    model: str
    provider: str
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    cost_usd: float = 0.0
    cached: bool = False
    fallback_used: bool = False
    raw: dict[str, Any] = field(default_factory=dict)

    def json_payload(self) -> Any:
        """Parse the response as JSON, tolerating a fenced code block around it.

        Structured extraction must not break the pipeline on one chatty response, so
        this repairs the common wrapper rather than raising.
        """
        text = self.text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
        start = min((i for i in (text.find("{"), text.find("[")) if i != -1), default=-1)
        if start > 0:
            text = text[start:]
        return json.loads(text)


def raise_with_body(response: httpx.Response) -> None:
    """raise_for_status, but keep the provider's explanation in the message.

    A bare "404 Not Found" for a chat endpoint is nearly useless - the body is what
    says "model not found", which is the difference between a five-minute fix and an
    hour of guessing at the wrong layer.
    """
    if response.is_error:
        detail = response.text[:400].replace("\n", " ")
        raise httpx.HTTPStatusError(
            f"{response.status_code} from {response.request.url}: {detail}",
            request=response.request,
            response=response,
        )


def _cost(model: str, tokens_in: int, tokens_out: int) -> float:
    price_in, price_out = _PRICES.get(model, (0.0, 0.0))
    return (tokens_in * price_in + tokens_out * price_out) / 1_000_000


def image_part(path: str | Path) -> dict[str, Any]:
    """Build a message part carrying an image, as a base64 data URI."""
    path = Path(path)
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    return {"type": "image", "mime": mime, "data": data}


def text_part(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}


class Provider(Protocol):
    name: str

    def available(self) -> bool: ...

    def complete(
        self, model: str, messages: list[dict[str, Any]], **params: Any
    ) -> LLMResponse: ...


class OpenRouterProvider:
    """OpenAI-compatible. One key covers both the vision and the synthesis tiers."""

    name = "openrouter"
    endpoint = "https://openrouter.ai/api/v1/chat/completions"

    def __init__(self, settings: Settings) -> None:
        self._key = settings.openrouter_api_key

    def available(self) -> bool:
        return bool(self._key)

    @staticmethod
    def _content(parts: list[dict[str, Any]]) -> Any:
        if len(parts) == 1 and parts[0]["type"] == "text":
            return parts[0]["text"]
        out: list[dict[str, Any]] = []
        for part in parts:
            if part["type"] == "text":
                out.append({"type": "text", "text": part["text"]})
            else:
                uri = f"data:{part['mime']};base64,{part['data']}"
                out.append({"type": "image_url", "image_url": {"url": uri}})
        return out

    def complete(self, model: str, messages: list[dict[str, Any]], **params: Any) -> LLMResponse:
        body = {
            "model": model,
            "messages": [
                {"role": m["role"], "content": self._content(m["parts"])} for m in messages
            ],
            "temperature": params.get("temperature", 0.0),
        }
        if params.get("max_tokens"):
            body["max_tokens"] = params["max_tokens"]
        if params.get("json_mode"):
            body["response_format"] = {"type": "json_object"}

        started = time.perf_counter()
        with httpx.Client(timeout=params.get("timeout", 120.0)) as client:
            response = client.post(
                self.endpoint,
                headers={
                    "Authorization": f"Bearer {self._key}",
                    "HTTP-Referer": "https://github.com/ashen-era-assistant",
                    "X-Title": "Ashen Era Archive Assistant",
                },
                json=body,
            )
            raise_with_body(response)
            data = response.json()

        usage = data.get("usage") or {}
        tokens_in = int(usage.get("prompt_tokens", 0))
        tokens_out = int(usage.get("completion_tokens", 0))
        return LLMResponse(
            text=data["choices"][0]["message"]["content"] or "",
            model=model,
            provider=self.name,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=int((time.perf_counter() - started) * 1000),
            cost_usd=_cost(model, tokens_in, tokens_out),
            raw=data,
        )


def _require_json_word(messages: list[dict[str, Any]]) -> None:
    """Ensure the literal word "json" appears, because OpenAI refuses without it.

        400: 'messages' must contain the word 'json' in some form, to use
             'response_format' of type 'json_object'.

    A prompt can show the exact JSON shape it wants - {"verdicts":[{"claim_id":...}]} -
    and still not contain the word, which is precisely what A6's entailment prompt did.
    Every entailment call 400'd, the verifier swallowed it as `entailment_skipped`, and
    every non-extractive claim was quietly downgraded to "Inference (not verified)". A
    verification step that silently stops verifying is worse than one that fails loudly.

    Only OpenAI enforces this, so only OpenAI's body is amended: rewriting the prompt for
    every provider would change their cache keys and make recorded runs irreproducible.
    """
    if any("json" in str(m.get("content", "")).lower() for m in messages):
        return
    note = "Respond with a single JSON object."
    for message in messages:
        if message.get("role") == "system" and isinstance(message.get("content"), str):
            message["content"] = f"{message['content']} {note}"
            return
    messages.insert(0, {"role": "system", "content": note})


class OpenAIProvider(OpenRouterProvider):
    """OpenAI direct. Same wire format as OpenRouter, different host and auth.

    Worth having alongside OpenRouter rather than only through it: when a free model
    is retired or throttled, a paid vision model on a separate account is the fallback
    that keeps the demo recording. 70 unique images is cents, not dollars.
    """

    name = "openai"
    endpoint = "https://api.openai.com/v1/chat/completions"

    def __init__(self, settings: Settings) -> None:
        self._key = settings.openai_api_key

    def complete(self, model: str, messages: list[dict[str, Any]], **params: Any) -> LLMResponse:
        body: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": m["role"], "content": self._content(m["parts"])} for m in messages
            ],
        }
        if params.get("max_tokens"):
            body["max_completion_tokens"] = params["max_tokens"]
        if params.get("json_mode"):
            body["response_format"] = {"type": "json_object"}
            _require_json_word(body["messages"])

        started = time.perf_counter()
        with httpx.Client(timeout=params.get("timeout", 120.0)) as client:
            response = client.post(
                self.endpoint,
                headers={"Authorization": f"Bearer {self._key}"},
                json=body,
            )
            raise_with_body(response)
            data = response.json()

        usage = data.get("usage") or {}
        tokens_in = int(usage.get("prompt_tokens", 0))
        tokens_out = int(usage.get("completion_tokens", 0))
        return LLMResponse(
            text=data["choices"][0]["message"]["content"] or "",
            model=model,
            provider=self.name,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=int((time.perf_counter() - started) * 1000),
            cost_usd=_cost(model, tokens_in, tokens_out),
            raw=data,
        )


class GeminiProvider:
    """Google AI Studio REST. Its free tier has a genuinely capable vision model."""

    name = "gemini"
    base = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(self, settings: Settings) -> None:
        self._key = settings.gemini_api_key

    def available(self) -> bool:
        return bool(self._key)

    def complete(self, model: str, messages: list[dict[str, Any]], **params: Any) -> LLMResponse:
        contents: list[dict[str, Any]] = []
        system: list[str] = []
        for message in messages:
            if message["role"] == "system":
                system.extend(p["text"] for p in message["parts"] if p["type"] == "text")
                continue
            parts: list[dict[str, Any]] = []
            for part in message["parts"]:
                if part["type"] == "text":
                    parts.append({"text": part["text"]})
                else:
                    parts.append({"inline_data": {"mime_type": part["mime"], "data": part["data"]}})
            role = "user" if message["role"] == "user" else "model"
            contents.append({"role": role, "parts": parts})

        body: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {"temperature": params.get("temperature", 0.0)},
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": "\n".join(system)}]}
        if params.get("json_mode"):
            body["generationConfig"]["responseMimeType"] = "application/json"

        started = time.perf_counter()
        with httpx.Client(timeout=params.get("timeout", 120.0)) as client:
            response = client.post(
                f"{self.base}/{model}:generateContent",
                headers={"x-goog-api-key": self._key or ""},
                json=body,
            )
            raise_with_body(response)
            data = response.json()

        candidates = data.get("candidates") or []
        text = ""
        if candidates:
            text = "".join(
                p.get("text", "") for p in candidates[0].get("content", {}).get("parts", [])
            )
        usage = data.get("usageMetadata") or {}
        tokens_in = int(usage.get("promptTokenCount", 0))
        tokens_out = int(usage.get("candidatesTokenCount", 0))
        return LLMResponse(
            text=text,
            model=model,
            provider=self.name,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=int((time.perf_counter() - started) * 1000),
            cost_usd=_cost(model, tokens_in, tokens_out),
            raw=data,
        )


class BedrockProvider:
    """AWS Bedrock via the Converse API, which is uniform across model families.

    Note for the README: Bedrock requires per-region model access to be enabled in the
    console before any call succeeds, which is a setup step a judge would otherwise hit
    as an opaque AccessDeniedException.
    """

    name = "bedrock"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: Any = None

    def available(self) -> bool:
        return "bedrock" in self._settings.configured_providers()

    def _runtime(self) -> Any:
        if self._client is None:
            import boto3  # imported lazily so the dep is optional at runtime

            session = boto3.Session(
                profile_name=self._settings.aws_profile or None,
                region_name=self._settings.aws_region,
            )
            self._client = session.client("bedrock-runtime")
        return self._client

    def complete(self, model: str, messages: list[dict[str, Any]], **params: Any) -> LLMResponse:
        system: list[dict[str, str]] = []
        converse: list[dict[str, Any]] = []
        for message in messages:
            if message["role"] == "system":
                system.extend({"text": p["text"]} for p in message["parts"] if p["type"] == "text")
                continue
            content: list[dict[str, Any]] = []
            for part in message["parts"]:
                if part["type"] == "text":
                    content.append({"text": part["text"]})
                else:
                    fmt = part["mime"].split("/")[-1]
                    content.append(
                        {
                            "image": {
                                "format": "jpeg" if fmt == "jpg" else fmt,
                                "source": {"bytes": base64.b64decode(part["data"])},
                            }
                        }
                    )
            converse.append({"role": message["role"], "content": content})

        started = time.perf_counter()
        response = self._runtime().converse(
            modelId=model,
            messages=converse,
            system=system or [],
            inferenceConfig={
                "temperature": params.get("temperature", 0.0),
                "maxTokens": params.get("max_tokens", 4096),
            },
        )
        usage = response.get("usage", {})
        tokens_in = int(usage.get("inputTokens", 0))
        tokens_out = int(usage.get("outputTokens", 0))
        text = "".join(block.get("text", "") for block in response["output"]["message"]["content"])
        return LLMResponse(
            text=text,
            model=model,
            provider=self.name,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=int((time.perf_counter() - started) * 1000),
            cost_usd=_cost(model, tokens_in, tokens_out),
            raw={"usage": usage},
        )


class NoProviderConfiguredError(RuntimeError):
    """Raised when no provider has credentials. Names the fix, not just the fault."""

    def __init__(self) -> None:
        super().__init__(
            "No LLM provider is configured. Copy .env.example to .env and set at least "
            "one of OPENROUTER_API_KEY, GEMINI_API_KEY, or AWS credentials for Bedrock."
        )


class LLMClient:
    """Facade over the providers: cache, then retry, then fallback, then usage."""

    def __init__(
        self,
        settings: Settings | None = None,
        cache: ResponseCache | None = None,
        providers: list[Provider] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.cache = cache or ResponseCache(self.settings.cache_db)
        self.providers: list[Provider] = providers or [
            OpenRouterProvider(self.settings),
            OpenAIProvider(self.settings),
            GeminiProvider(self.settings),
            BedrockProvider(self.settings),
        ]
        # Keyed by provider AND model. A breaker keyed on the provider alone means one
        # bad model id opens the circuit for every other model on that provider, which
        # silently disables the escalation ladder the fallback chain depends on.
        self._breakers: dict[tuple[str, str], CircuitBreaker] = {}
        self.usage: list[LLMResponse] = []

    def available_providers(self) -> list[str]:
        return [p.name for p in self.providers if p.available()]

    @staticmethod
    def _cache_prompt(messages: list[dict[str, Any]]) -> str:
        """Full message content, images included, so two different images never collide."""
        return json.dumps(messages, sort_keys=True)

    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        provider: str | None = None,
        use_cache: bool = True,
        **params: Any,
    ) -> LLMResponse:
        """Run one completion, falling back through providers on failure.

        `provider` pins a single provider. It is required whenever the model id is
        provider-specific: "gpt-4o-mini" is meaningful to OpenAI and a 404 on
        OpenRouter, which expects "openai/gpt-4o-mini". Fanning one id across every
        provider only makes sense for ids they genuinely share.
        """
        model = model or self.settings.llm_model_synthesis
        candidates = [p for p in self.providers if p.available()]
        if provider is not None:
            candidates = [p for p in candidates if p.name == provider]
            if not candidates:
                raise NoProviderConfiguredError
        if not candidates:
            raise NoProviderConfiguredError

        prompt = self._cache_prompt(messages)
        if use_cache:
            hit = self.cache.get_json(model, prompt, params)
            if hit is not None:
                response = LLMResponse(**hit)
                response.cached = True
                self.usage.append(response)
                return response

        last: Exception | None = None
        for index, provider in enumerate(candidates):
            try:
                breaker = self._breakers.setdefault(
                    (provider.name, model), CircuitBreaker(failure_threshold=3)
                )
                response = call_with_retry(
                    lambda p=provider: p.complete(model, messages, **params),
                    policy=RetryPolicy(max_attempts=4),
                    breaker=breaker,
                    description=f"{provider.name}:{model}",
                )
            except Exception as exc:  # noqa: BLE001 - try the next provider
                log.warning("provider %s failed: %s", provider.name, exc)
                last = exc
                continue

            response.fallback_used = index > 0
            if use_cache:
                payload = {k: v for k, v in response.__dict__.items() if k not in {"raw", "cached"}}
                self.cache.set_json(model, prompt, params, payload)
            self.usage.append(response)
            return response

        assert last is not None
        raise last

    def describe_image(
        self,
        image_path: str | Path,
        instruction: str,
        *,
        model: str | None = None,
        provider: str | None = None,
        **params: Any,
    ) -> LLMResponse:
        """One vision call. Cached on image bytes, so re-runs of ingestion are free."""
        messages = [{"role": "user", "parts": [text_part(instruction), image_part(image_path)]}]
        return self.complete(
            messages,
            model=model or self.settings.llm_model_vision,
            provider=provider,
            **params,
        )
