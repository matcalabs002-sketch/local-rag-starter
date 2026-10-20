"""AI provider adapters with no automatic paid-service fallback."""

from __future__ import annotations

import hashlib
import math
import threading
import time
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from .config import CHAT_MODEL, EMBED_MODEL, OLLAMA_URL, RagError, Settings

BATCH_SIZE = 16
MAX_MODEL_SECONDS = 180
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
SUPPORTED_MODELS = {
    "ollama": {"chat": (CHAT_MODEL,), "embedding": (EMBED_MODEL,)},
    "openai": {
        "chat": ("gpt-4o-mini", "gpt-4.1-mini"),
        "embedding": ("text-embedding-3-small",),
    },
    "anthropic": {"chat": ("claude-3-5-haiku-latest",), "embedding": ()},
}


@dataclass(frozen=True)
class ProviderCapabilities:
    provider: str
    task: str
    models: tuple[str, ...]
    local: bool
    connection_test_may_cost_money: bool


class _ConnectionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str


class _PriorityGate:
    """Let interactive work run between document embedding batches."""

    def __init__(self):
        self._condition = threading.Condition()
        self._active = False
        self._interactive_waiters = 0

    def run(self, callback, *, interactive: bool):
        with self._condition:
            if interactive:
                self._interactive_waiters += 1
            try:
                while self._active or (not interactive and self._interactive_waiters):
                    self._condition.wait()
                self._active = True
            finally:
                if interactive:
                    self._interactive_waiters -= 1
        try:
            return callback()
        finally:
            with self._condition:
                self._active = False
                self._condition.notify_all()


_OLLAMA_GATE = _PriorityGate()
_CLIENTS: dict[tuple[str, str], httpx.Client] = {}
_CLIENTS_LOCK = threading.Lock()


def _shared_client(provider: str, api_key: str = "", ollama_url: str = OLLAMA_URL) -> httpx.Client:
    digest = hashlib.sha256(api_key.encode()).hexdigest()[:12] if api_key else "local"
    cache_key = (provider + ":" + ollama_url if provider == "ollama" else provider, digest)
    with _CLIENTS_LOCK:
        if cache_key not in _CLIENTS:
            if provider == "ollama":
                _CLIENTS[cache_key] = httpx.Client(base_url=ollama_url, timeout=MAX_MODEL_SECONDS, trust_env=False)
            elif provider == "openai":
                _CLIENTS[cache_key] = httpx.Client(
                    base_url="https://api.openai.com/v1",
                    timeout=MAX_MODEL_SECONDS,
                    headers={"Authorization": f"Bearer {api_key}"},
                )
            elif provider == "anthropic":
                _CLIENTS[cache_key] = httpx.Client(
                    base_url="https://api.anthropic.com/v1",
                    timeout=MAX_MODEL_SECONDS,
                    headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
                )
            else:
                raise RagError(f"Unsupported AI provider: {provider}.")
        return _CLIENTS[cache_key]


def _post(client: httpx.Client, path: str, payload: dict[str, Any], provider: str) -> dict[str, Any]:
    for attempt in range(3):
        try:
            response = client.post(path, json=payload)
            if response.status_code in RETRYABLE_STATUS and attempt < 2:
                time.sleep(2**attempt)
                continue
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as error:
            if error.response.status_code in (401, 403):
                raise RagError(f"{provider.title()} rejected the saved credential. Check it in Settings.") from None
            if error.response.status_code == 429:
                raise RagError(
                    f"{provider.title()} is rate limited or has reached its usage limit. Try again later."
                ) from None
            raise RagError(
                f"{provider.title()} could not process this request. Check the selected model and try again."
            ) from None
        except (httpx.RequestError, ValueError):
            if attempt < 2:
                time.sleep(2**attempt)
                continue
            raise RagError(f"{provider.title()} did not respond. Check the connection and try again.") from None
    raise RagError(f"{provider.title()} request failed.")


class _Ollama:
    def __init__(self, client: httpx.Client, settings: Settings):
        self.client, self.settings = client, settings

    def health(self, required: tuple[str, ...]):
        try:
            result = self.client.get("/api/tags")
            result.raise_for_status()
            names = {model["name"] for model in result.json()["models"]}
            if any(model not in names for model in required):
                raise RagError(
                    "Required local models are missing. Pull the configured models using the Ollama commands in README.md."
                )
        except RagError:
            raise
        except Exception:
            raise RagError(
                "Ollama is unavailable. Start ollama serve at the configured OLLAMA_URL; see README.md."
            ) from None

    def embed(self, texts: list[str], *, query: bool) -> dict[str, Any]:
        prefix = "search_query: " if query else "search_document: "
        payload = {
            "model": self.settings.embedding_model,
            "input": [prefix + text for text in texts],
            "truncate": False,
            "keep_alive": self.settings.ollama_keep_alive,
        }
        return _OLLAMA_GATE.run(lambda: _post(self.client, "/api/embed", payload, "local AI"), interactive=query)

    def structured(self, messages: list[dict[str, str]], schema: type[BaseModel]):
        payload = {
            "model": self.settings.chat_model,
            "messages": messages,
            "format": schema.model_json_schema(),
            "stream": False,
            "think": False,
            "keep_alive": self.settings.ollama_keep_alive,
            "options": {"temperature": 0, "num_ctx": 8192, "num_predict": self.settings.max_answer_tokens},
        }
        data = _OLLAMA_GATE.run(lambda: _post(self.client, "/api/chat", payload, "local AI"), interactive=True)
        try:
            if data.get("done_reason") == "length":
                raise ValueError()
            return schema.model_validate_json(data["message"]["content"])
        except (ValidationError, ValueError, KeyError, TypeError):
            raise RagError("The AI returned an incomplete answer. Please try a shorter question.") from None


class _OpenAI:
    def __init__(self, client: httpx.Client, settings: Settings):
        self.client, self.settings = client, settings

    def embed(self, texts: list[str], *, query: bool) -> dict[str, Any]:
        del query
        return _post(
            self.client,
            "/embeddings",
            {
                "model": self.settings.embedding_model,
                "input": texts,
                "dimensions": self.settings.embedding_dimensions,
            },
            "OpenAI",
        )

    def structured(self, messages: list[dict[str, str]], schema: type[BaseModel]):
        data = _post(
            self.client,
            "/chat/completions",
            {
                "model": self.settings.chat_model,
                "messages": messages,
                "temperature": 0,
                "max_completion_tokens": self.settings.max_answer_tokens,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": schema.__name__.lower(),
                        "strict": True,
                        "schema": schema.model_json_schema(),
                    },
                },
            },
            "OpenAI",
        )
        try:
            return schema.model_validate_json(data["choices"][0]["message"]["content"])
        except (ValidationError, ValueError, KeyError, TypeError, IndexError):
            raise RagError("The AI returned an incomplete answer. Please try a shorter question.") from None


class _Anthropic:
    def __init__(self, client: httpx.Client, settings: Settings):
        self.client, self.settings = client, settings

    def structured(self, messages: list[dict[str, str]], schema: type[BaseModel]):
        system = "\n\n".join(item["content"] for item in messages if item["role"] == "system")
        conversation = [item for item in messages if item["role"] != "system"]
        data = _post(
            self.client,
            "/messages",
            {
                "model": self.settings.chat_model,
                "system": system,
                "messages": conversation,
                "temperature": 0,
                "max_tokens": self.settings.max_answer_tokens,
                "tools": [
                    {
                        "name": "return_result",
                        "description": "Return the validated result.",
                        "input_schema": schema.model_json_schema(),
                    }
                ],
                "tool_choice": {"type": "tool", "name": "return_result"},
            },
            "Anthropic",
        )
        try:
            value = next(
                item["input"]
                for item in data["content"]
                if item.get("type") == "tool_use" and item.get("name") == "return_result"
            )
            return schema.model_validate(value)
        except (StopIteration, ValidationError, ValueError, KeyError, TypeError):
            raise RagError("The AI returned an incomplete answer. Please try a shorter question.") from None


class Models:
    """Configured embedding and chat providers used by sync and chat."""

    def __init__(self, client=None, settings: Settings | None = None, clients: dict[str, httpx.Client] | None = None):
        if isinstance(client, Settings) and settings is None:
            settings, client = client, None
        self.settings = settings or Settings.load()
        self._validate_settings()
        supplied = clients or {}
        if client is not None:
            supplied = {"ollama": client, **supplied}
        self._clients = supplied
        self.embedding = self._adapter(self.settings.embedding_provider)
        self.chat = self._adapter(self.settings.chat_provider)

    def _validate_settings(self):
        selected = (
            (self.settings.embedding_provider, "embedding", self.settings.embedding_model),
            (self.settings.chat_provider, "chat", self.settings.chat_model),
        )
        for provider, task, model in selected:
            if model not in SUPPORTED_MODELS.get(provider, {}).get(task, ()):
                raise RagError(f"{model or 'The selected model'} is not a supported {provider} {task} model.")
        if not 1 <= self.settings.embedding_dimensions <= 3072:
            raise RagError("Embedding dimensions must be between 1 and 3,072.")
        if not 1_000 <= self.settings.max_context_chars <= 100_000:
            raise RagError("The context limit must be between 1,000 and 100,000 characters.")
        if not 64 <= self.settings.max_answer_tokens <= 4_096:
            raise RagError("The answer limit must be between 64 and 4,096 tokens.")
        if not self.settings.ollama_keep_alive or len(self.settings.ollama_keep_alive) > 12:
            raise RagError("Enter a valid Ollama warm period, such as 10m.")
        for provider in {self.settings.embedding_provider, self.settings.chat_provider}:
            if provider == "openai" and not self.settings.openai_api_key:
                raise RagError("Add an OpenAI API key in Settings before selecting OpenAI.")
            if provider == "anthropic" and not self.settings.anthropic_api_key:
                raise RagError("Add an Anthropic API key in Settings before selecting Anthropic.")

    def _adapter(self, provider: str):
        api_key = {"openai": self.settings.openai_api_key, "anthropic": self.settings.anthropic_api_key}.get(
            provider, ""
        )
        client = self._clients.get(provider) or _shared_client(provider, api_key, self.settings.ollama_url)
        if provider == "ollama":
            return _Ollama(client, self.settings)
        if provider == "openai":
            return _OpenAI(client, self.settings)
        if provider == "anthropic":
            return _Anthropic(client, self.settings)
        raise RagError(f"Unsupported AI provider: {provider}.")

    @staticmethod
    def capabilities() -> list[ProviderCapabilities]:
        return [
            ProviderCapabilities(provider, task, models, provider == "ollama", provider != "ollama")
            for provider, tasks in SUPPORTED_MODELS.items()
            for task, models in tasks.items()
            if models
        ]

    def health(self):
        if self.settings.embedding_provider == "ollama" or self.settings.chat_provider == "ollama":
            required = tuple(
                {
                    model
                    for provider, model in (
                        (self.settings.embedding_provider, self.settings.embedding_model),
                        (self.settings.chat_provider, self.settings.chat_model),
                    )
                    if provider == "ollama"
                }
            )
            _Ollama(
                self._clients.get("ollama") or _shared_client("ollama", ollama_url=self.settings.ollama_url),
                self.settings,
            ).health(required)
        return True

    def test_connection(self, task: str) -> str:
        """Make an explicit request. Paid-provider tests may incur a tiny charge."""
        if task == "embedding":
            self.embed(["connection test"], query=True)
            return f"{self.settings.embedding_provider.title()} embeddings connected."
        if task == "chat":
            result = self.structured(
                [
                    {"role": "system", "content": 'Return status "connected".'},
                    {"role": "user", "content": "Connection test."},
                ],
                _ConnectionResult,
            )
            if result.status.lower() != "connected":
                raise RagError("The chat provider responded but failed the connection check.")
            return f"{self.settings.chat_provider.title()} chat connected."
        raise RagError("Choose either the chat or embedding connection test.")

    def embed(self, texts, query=False):
        vectors: list[list[float]] = []
        for start in range(0, len(texts), BATCH_SIZE):
            batch = texts[start : start + BATCH_SIZE]
            data = self.embedding.embed(batch, query=query)
            if self.settings.embedding_provider == "openai":
                try:
                    rows = sorted(data["data"], key=lambda row: row["index"])
                    embeddings = [row["embedding"] for row in rows]
                except (KeyError, TypeError):
                    embeddings = []
            else:
                embeddings = data.get("embeddings", [])
            if len(embeddings) != len(batch):
                raise RagError("The embedding provider returned an incomplete result. Previous document data was kept.")
            for vector in embeddings:
                if (
                    len(vector) != self.settings.embedding_dimensions
                    or not all(isinstance(number, (int, float)) and math.isfinite(number) for number in vector)
                    or not any(vector)
                ):
                    raise RagError("The embedding provider returned invalid vectors. Check its model and dimensions.")
            vectors.extend(embeddings)
        return vectors

    def structured(self, messages, schema):
        return self.chat.structured(messages, schema)
