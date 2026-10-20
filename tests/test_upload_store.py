from dataclasses import replace
import os
import pytest

from rag.config import Settings, RagError
from rag.store import Store
from rag.types import Chunk, DriveFile
from rag.uploads import UploadService, LocalSource
from rag.sources import rebuild_sources
from rag.reindex import ReindexEngine


class Models:
    fail = False

    def __init__(self, settings):
        self.settings = settings

    def embed(self, texts, query=False):
        if self.fail:
            raise RagError("Embedding failed")
        return [[0.1] * self.settings.embedding_dimensions for _ in texts]


@pytest.fixture
def local_library(tmp_path):
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Disposable local database required")
    settings = Settings(database_url=url, data_dir=str(tmp_path))
    store = Store(settings)
    store.initialize()
    with store.connect(vector=False) as conn:
        conn.execute(
            "truncate python_rag.library,python_rag.index_generations,python_rag.website_sources,python_rag.activity,python_rag.sessions restart identity cascade"
        )
    store.initialize()
    models = Models(settings)
    return store, settings, models, UploadService(store, models, settings)


@pytest.mark.integration
def test_upload_idempotency_explicit_replace_and_source_isolation(local_library):
    store, settings, models, uploads = local_library
    assert uploads.add("sample.txt", b"old fact") == "added"
    first = store.uploads()[0]
    assert uploads.add("sample.txt", b"old fact") == "unchanged"
    with pytest.raises(RagError, match="Enable replacement"):
        uploads.add("sample.txt", b"new fact")
    models.fail = True
    with pytest.raises(RagError):
        uploads.add("sample.txt", b"new fact", True)
    assert store.uploads()[0]["version"] == first["version"]
    assert store.search([0.1] * 768)[0][0].text == "old fact"
    models.fail = False
    assert uploads.add("sample.txt", b"new fact", True) == "updated"
    assert store.uploads()[0]["id"] == first["id"]
    with store.sync_lock() as locked:
        locked.reconcile(set())  # Drive reconciliation must preserve uploads.
    assert store.counts()["documents"] == 1
    uploads.remove(first["id"])
    assert not store.uploads() and store.counts()["chunks"] == 0


@pytest.mark.integration
def test_failed_database_publication_keeps_registry_and_previous_passages(local_library, monkeypatch):
    store, settings, models, uploads = local_library
    uploads.add("sample.txt", b"old fact")
    original = store.uploads()[0]
    method = Store.publish_upload

    def broken(self, file, chunks, vectors):
        # Simulate a failure after replace, inside the same publication transaction.
        with self.connect() as conn, conn.transaction():
            Store(self.settings, conn).replace(file, chunks, vectors)
            raise RagError("Database publication failed")

    monkeypatch.setattr(Store, "publish_upload", broken)
    with pytest.raises(RagError):
        uploads.add("sample.txt", b"new fact", True)
    assert store.uploads()[0] == original
    assert store.search([0.1] * 768)[0][0].text == "old fact"
    monkeypatch.setattr(Store, "publish_upload", method)
    assert uploads.cleanup() == 1


@pytest.mark.integration
def test_local_rebuild_and_recovery_require_current_originals(local_library):
    store, settings, models, uploads = local_library
    uploads.add("sample.txt", b"A fictional handbook. " * 50)
    original = store.active_generation()
    proposed = replace(settings, chunk_size=500, chunk_overlap=50)
    engine = ReindexEngine(
        store, rebuild_sources(store, settings), Models(proposed), "", chunk_size=500, chunk_overlap=50
    )
    engine.run()
    assert store.active_generation()["chunk_size"] == 500
    engine.rollback(str(original["id"]))
    assert store.active_generation()["id"] == original["id"]
    row = store.uploads()[0]
    LocalSource(store, settings).blob_path(row["version"]).unlink()
    with pytest.raises(RagError, match="missing"):
        engine.run()
    assert store.active_generation()["id"] == original["id"]


@pytest.mark.integration
def test_upload_rejects_incompatible_same_dimension_model(local_library):
    store, settings, models, uploads = local_library
    changed = replace(settings, embedding_provider="openai", embedding_model="text-embedding-3-small")
    with pytest.raises(RagError, match="differ"):
        UploadService(store, Models(changed), changed).add("new.txt", b"Never embed against the wrong pipeline.")
    assert store.uploads() == []


@pytest.mark.integration
def test_rebuild_preserves_all_source_kinds_and_remove_blocks_resurrection(local_library):
    store, settings, models, uploads = local_library
    uploads.add("local.txt", b"local information")
    with store.sync_lock() as locked:
        locked.replace(
            DriveFile("drive-one", "Drive", "1", "text/plain", "https://drive.google.com/file/d/one/view"),
            [Chunk("Drive information")],
            [[0.1] * 768],
        )
    uploads.remove(store.uploads()[0]["id"])
    assert store.counts()["documents"] == 1
    assert not store.uploads()


@pytest.mark.integration
def test_search_checks_embedding_identity_not_only_dimensions(local_library):
    store, settings, models, uploads = local_library
    uploads.add("local.txt", b"A fictional document")
    assert store.search_current([0.1] * 768, settings)[0]
    other = replace(settings, embedding_provider="openai", embedding_model="text-embedding-3-small")
    with pytest.raises(RagError, match="changed"):
        store.search_current([0.1] * 768, other)


@pytest.mark.integration
def test_writer_never_reconnects_after_lock_connection_loss(local_library):
    import psycopg

    store, settings, models, uploads = local_library
    uploads.add("local.txt", b"Original")
    with store.sync_lock() as locked:
        locked.connection.close()
        with pytest.raises(psycopg.Error):
            locked.replace(DriveFile("new", "new", "1", "text/plain", ""), [Chunk("should not publish")], [[0.1] * 768])
    assert store.counts()["documents"] == 1


@pytest.mark.integration
def test_chat_retry_and_rebuild_confirmation_survive_reruns(local_library, monkeypatch):
    from streamlit.testing.v1 import AppTest
    from pathlib import Path
    from rag.types import AnswerDraft

    store, settings, models, uploads = local_library
    uploads.add("local.txt", b"The project code is ORCHID-742.")
    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    monkeypatch.setenv("CHUNK_SIZE", "1000")
    monkeypatch.setenv("CHUNK_OVERLAP", "150")
    monkeypatch.setenv("DRIVE_FOLDER_ID", "")
    monkeypatch.setattr("rag.models.Models.health", lambda self: True)
    monkeypatch.setattr("rag.models.Models.embed", lambda self, texts, query=False: [[0.1] * 768 for _ in texts])
    calls = []

    def structured(self, messages, schema):
        calls.append(messages)
        if len(calls) == 1:
            raise RagError("Temporary model failure. Retry the question.")
        return AnswerDraft(answer="ORCHID-742", citation_ids=[1])

    monkeypatch.setattr("rag.models.Models.structured", structured)
    app = AppTest.from_file(str(Path(__file__).parents[1] / "app.py"), default_timeout=30).run()
    assert not app.exception
    app.chat_input[0].set_value("What is the project code?").run()
    assert not app.exception
    retry = next(button for button in app.button if button.label == "Try again")
    retry.click().run()
    assert not app.exception and len(calls) == 2
    assert len(store.history(store.sessions()[0]["id"])) == 1
    app.radio[0].set_value("Settings").run()
    before = next(button for button in app.button if button.label == "Rebuild index")
    assert before.disabled
    confirm = next(box for box in app.checkbox if "Rebuild all sources" in box.label)
    confirm.check().run()
    assert not app.exception
    assert not next(button for button in app.button if button.label == "Rebuild index").disabled


@pytest.mark.integration
def test_new_chat_selects_created_conversation(local_library, monkeypatch):
    from streamlit.testing.v1 import AppTest
    from pathlib import Path

    store, settings, models, uploads = local_library
    uploads.add("local.txt", b"A fictional project handbook.")
    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    monkeypatch.setenv("CHUNK_SIZE", "1000")
    monkeypatch.setenv("CHUNK_OVERLAP", "150")
    monkeypatch.setenv("DRIVE_FOLDER_ID", "")
    monkeypatch.setattr("rag.models.Models.health", lambda self: True)
    app = AppTest.from_file(str(Path(__file__).parents[1] / "app.py"), default_timeout=30).run()
    previous = app.session_state["conversation"]
    next(button for button in app.button if button.label == "New chat").click().run()
    assert not app.exception
    assert app.session_state["conversation"] != previous
    assert len(store.sessions()) == 2
    assert store.history(app.session_state["conversation"]) == []
