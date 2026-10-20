"""One configuration contract: environment > .env > code defaults."""

from dataclasses import dataclass, field, fields
import os
from pathlib import Path
import re
from urllib.parse import urlparse

from dotenv import dotenv_values, set_key

ROOT = Path(__file__).resolve().parents[1]
_data_path = Path(
    os.getenv("RAG_DATA_DIR") or dotenv_values(ROOT / ".env").get("RAG_DATA_DIR") or ROOT / ".private"
).expanduser()
PRIVATE = (_data_path if _data_path.is_absolute() else ROOT / _data_path).resolve()
CHAT_MODEL = "qwen3:4b"
EMBED_MODEL = "nomic-embed-text:v1.5"
DIMENSIONS = 768
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150
SYNC_SECONDS = 300
TOP_K = 5
MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_TEXT_CHARS = 2_000_000
MAX_CHUNKS = 4000
MAX_QUESTION_CHARS = 3000
OLLAMA_URL = "http://127.0.0.1:11435"
OLLAMA_KEEP_ALIVE = "10m"
MAX_CONTEXT_CHARS = 12_000
MAX_ANSWER_TOKENS = 900
PIPELINE_ID = f"{EMBED_MODEL}|{DIMENSIONS}|{CHUNK_SIZE}|{CHUNK_OVERLAP}|v1"
ADVISORY_LOCK_ID = 731_426_019


class RagError(Exception):
    """An actionable message safe to show without secrets or provider bodies."""


def pipeline_id(settings, chunk_size=None, chunk_overlap=None):
    size = chunk_size if chunk_size is not None else getattr(settings, "chunk_size", CHUNK_SIZE)
    overlap = chunk_overlap if chunk_overlap is not None else getattr(settings, "chunk_overlap", CHUNK_OVERLAP)
    if (
        settings.embedding_provider == "ollama"
        and settings.embedding_model == EMBED_MODEL
        and settings.embedding_dimensions == DIMENSIONS
        and size == CHUNK_SIZE
        and overlap == CHUNK_OVERLAP
    ):
        return PIPELINE_ID
    return (
        f"{settings.embedding_provider}:{settings.embedding_model}|{settings.embedding_dimensions}|{size}|{overlap}|v2"
    )


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default="", repr=False)
    folder_id: str = ""
    project_url: str = ""
    ca_file: str = ""
    chat_provider: str = "ollama"
    chat_model: str = CHAT_MODEL
    embedding_provider: str = "ollama"
    embedding_model: str = EMBED_MODEL
    embedding_dimensions: int = DIMENSIONS
    ollama_keep_alive: str = OLLAMA_KEEP_ALIVE
    max_context_chars: int = MAX_CONTEXT_CHARS
    max_answer_tokens: int = MAX_ANSWER_TOKENS
    openai_api_key: str = field(default="", repr=False)
    anthropic_api_key: str = field(default="", repr=False)
    ollama_url: str = OLLAMA_URL
    data_dir: str = str(PRIVATE)
    chunk_size: int = CHUNK_SIZE
    chunk_overlap: int = CHUNK_OVERLAP
    sync_seconds: int = SYNC_SECONDS
    top_k: int = TOP_K
    max_file_bytes: int = MAX_FILE_BYTES

    @classmethod
    def load(cls):
        values = {**dotenv_values(ROOT / ".env"), **os.environ}
        names = {
            "folder_id": "DRIVE_FOLDER_ID",
            "project_url": "SUPABASE_PROJECT_URL",
            "ca_file": "DATABASE_CA_FILE",
            "data_dir": "RAG_DATA_DIR",
        }
        integers = {
            "embedding_dimensions",
            "max_context_chars",
            "max_answer_tokens",
            "chunk_size",
            "chunk_overlap",
            "sync_seconds",
            "top_k",
            "max_file_bytes",
        }
        defaults = cls()
        kwargs = {}
        for item in fields(cls):
            key = names.get(item.name, item.name.upper())
            raw = values.get(key)
            if raw is None:
                continue
            try:
                kwargs[item.name] = int(raw) if item.name in integers else str(raw).strip()
            except ValueError:
                raise RagError(f"{key} must be a whole number.") from None
        result = cls(**kwargs)
        # Empty variables remain empty; only absent variables use defaults.
        if not result.data_dir:
            result = cls(**{**kwargs, "data_dir": defaults.data_dir})
        location = Path(result.data_dir).expanduser()
        if not location.is_absolute():
            location = ROOT / location
        return cls(**{**{f.name: getattr(result, f.name) for f in fields(cls)}, "data_dir": str(location.resolve())})

    def validate(self):
        if self.folder_id and not re.fullmatch(r"[A-Za-z0-9_-]+", self.folder_id):
            raise RagError("Enter a valid Google Drive folder ID in Settings.")
        if not self.database_url:
            raise RagError("Set DATABASE_URL in .env, then initialize your database.")
        try:
            parsed = urlparse(self.database_url)
            port = parsed.port
        except ValueError:
            raise RagError("DATABASE_URL has an invalid host or port.") from None
        if parsed.scheme not in ("postgres", "postgresql") or not parsed.hostname:
            raise RagError("DATABASE_URL must be a PostgreSQL connection URL.")
        if parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
            if port != 5432:
                raise RagError(
                    "Use Session pooler port 5432. Transaction pooler port 6543 cannot safely run the sync lock."
                )
            project = urlparse(self.project_url).hostname
            if not project or not project.endswith(".supabase.co"):
                raise RagError("Set SUPABASE_PROJECT_URL for a remote Supabase database.")
            ref = project.split(".")[0]
            if parsed.hostname != f"db.{ref}.supabase.co" and not (
                parsed.hostname.endswith(".pooler.supabase.com") and parsed.username == f"postgres.{ref}"
            ):
                raise RagError("The database connection does not match the selected Supabase project.")
        endpoint = urlparse(self.ollama_url)
        if endpoint.scheme not in ("http", "https") or not endpoint.hostname or endpoint.username or endpoint.password:
            raise RagError("OLLAMA_URL must be an HTTP(S) URL without credentials.")
        if not 200 <= self.chunk_size <= 4000 or not 0 <= self.chunk_overlap < self.chunk_size:
            raise RagError("Use a chunk size of 200–4,000 and an overlap smaller than the chunk size.")
        if not 1 <= self.top_k <= 20 or not 30 <= self.sync_seconds <= 86400:
            raise RagError("TOP_K must be 1–20 and SYNC_SECONDS must be 30–86,400.")
        if not 1 <= self.max_file_bytes <= MAX_FILE_BYTES:
            raise RagError("MAX_FILE_BYTES must be between 1 and 52,428,800 (50 MiB).")


def private_dir():
    PRIVATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    PRIVATE.chmod(0o700)
    return PRIVATE


def write_private(path: Path, content: str):
    private_dir()
    temp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as file:
        file.write(content)
    temp.replace(path)
    path.chmod(0o600)


def save_settings(values: dict[str, str]):
    allowed = {item.name.upper() for item in fields(Settings)} - {"FOLDER_ID", "PROJECT_URL", "CA_FILE", "DATA_DIR"}
    allowed |= {"DRIVE_FOLDER_ID", "SUPABASE_PROJECT_URL", "DATABASE_CA_FILE", "RAG_DATA_DIR"}
    if set(values) - allowed:
        raise RagError("Unknown configuration setting.")
    path = ROOT / ".env"
    fd = os.open(path, os.O_CREAT | os.O_WRONLY, 0o600)
    os.close(fd)
    path.chmod(0o600)
    for key, value in values.items():
        set_key(str(path), key, value)
