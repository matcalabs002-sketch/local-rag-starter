from pathlib import Path
import pytest
from rag.config import Settings, RagError


def test_env_example_is_not_runtime_configuration(tmp_path, monkeypatch):
    monkeypatch.setattr("rag.config.ROOT", tmp_path)
    (tmp_path / ".env.example").write_text("DATABASE_URL=not-a-real-setting\nCHAT_MODEL=example-only\n")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CHAT_MODEL", raising=False)
    assert Settings.load().database_url == ""
    assert Settings.load().chat_model == "qwen3:4b"
    (tmp_path / ".env").write_text("CHAT_MODEL=from-file\n")
    assert Settings.load().chat_model == "from-file"
    monkeypatch.setenv("CHAT_MODEL", "from-process")
    assert Settings.load().chat_model == "from-process"


def test_local_database_does_not_require_drive():
    Settings(database_url="postgresql://localhost:55432/rag").validate()


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(chunk_overlap=1000),
        dict(top_k=0),
        dict(sync_seconds=0),
        dict(ollama_url="file:///tmp/models"),
        dict(database_url="postgresql://localhost:wrong/rag"),
    ],
)
def test_invalid_settings_are_actionable(kwargs):
    with pytest.raises(RagError):
        Settings(**{"database_url": "postgresql://localhost/rag", **kwargs}).validate()


def test_secret_fields_are_not_in_representation():
    settings = Settings(database_url="password-in-url", openai_api_key="private-key")
    assert "password-in-url" not in repr(settings) and "private-key" not in repr(settings)


def test_every_public_setting_is_documented():
    from dataclasses import fields

    names = {
        "folder_id": "DRIVE_FOLDER_ID",
        "project_url": "SUPABASE_PROJECT_URL",
        "ca_file": "DATABASE_CA_FILE",
        "data_dir": "RAG_DATA_DIR",
    }
    example = (Path(__file__).parents[1] / ".env.example").read_text()
    assert all(names.get(f.name, f.name.upper()) + "=" in example for f in fields(Settings))
