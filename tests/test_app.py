from pathlib import Path
from streamlit.testing.v1 import AppTest
from rag.config import Settings
from rag.ui import visible_settings


def test_three_page_workspace_without_credentials(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setattr("rag.models.Models.health", lambda self: True)
    app = AppTest.from_file(str(Path(__file__).parents[1] / "app.py"), default_timeout=30).run()
    assert not app.exception
    assert app.radio[0].options == ["Chat", "Sources", "Settings"]
    assert any(title.value == "Chat" for title in app.title)
    app.radio[0].set_value("Sources").run()
    assert not app.exception
    assert any("Initialize" in item.value for item in app.info)
    app.radio[0].set_value("Settings").run()
    assert not app.exception
    assert any(title.value == "Settings" for title in app.title)
    assert any("setup" in item.value for item in app.code)


def test_public_settings_never_include_credentials():
    public = visible_settings(Settings(openai_api_key="placeholder", anthropic_api_key="placeholder"))
    assert "openai_api_key" not in public and "database_url" not in public


def test_preview_and_ingestion_use_identical_splitter():
    from rag.ui import preview_chunks
    from rag.loaders import split_text_chunks

    text = "A short sentence about onboarding. " * 40
    assert preview_chunks(text, 300, 50) == [chunk.text for chunk in split_text_chunks(text, 300, 50)[:4]]


def test_untrusted_document_names_are_literal_labels():
    from rag.ui import literal_label

    assert literal_label("![image](https://example.com/x)") == r"\!\[image\]\(https://example.com/x\)"
    app = AppTest.from_string("""
from rag.workspace.chat_page import show_sources
show_sources([{'number':1,'file_name':'![image](https://example.com/x)','text':'A fictional passage','url':''}])
""").run()
    assert not app.exception
    assert r"\!\[image\]" in app.markdown[0].value
