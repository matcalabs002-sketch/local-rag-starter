import os
from contextlib import contextmanager
from uuid import uuid4
import pytest
from rag.store import Store
from rag.config import Settings, RagError, PIPELINE_ID
from rag.types import DriveFile, Chunk, Answer


def test_metadata_reads_skip_vector_registration(monkeypatch):
    flags = []

    class Connection:
        def execute(self, query, params=None):
            return self

        def fetchone(self):
            return {"t": "python_rag.sync_status"}

        def fetchall(self):
            return []

    @contextmanager
    def connect(self, vector=True):
        flags.append(vector)
        yield Connection()

    monkeypatch.setattr(Store, "connect", connect)
    store = Store(Settings())
    store.ready()
    store.sessions()
    store.history("session")
    store.status()
    assert flags == [False, False, False, False]


@pytest.fixture
def store():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a disposable local PostgreSQL database")
    from urllib.parse import urlparse

    assert urlparse(url).hostname in ("localhost", "127.0.0.1"), "Never run against a remote database"
    s = Store(Settings(database_url=url, folder_id="test-folder"))
    s.initialize()
    with s.connect() as c:
        c.execute("""truncate python_rag.activity,python_rag.document_exclusions,
            python_rag.generation_chunks,python_rag.generation_documents,python_rag.website_sources,
            python_rag.index_generations,
            python_rag.turns,python_rag.sessions,python_rag.chunks,python_rag.documents,
            python_rag.library restart identity cascade""")
    s.initialize()
    return s


@pytest.mark.integration
def test_transaction_rollback_and_deletion(store):
    f = DriveFile("a", "A", "1", "text/plain", "https://drive.google.com/file/d/a/view")
    with store.sync_lock() as locked:
        locked.bind("test-folder", PIPELINE_ID)
        locked.replace(f, [Chunk("original")], [[1.0] * 768])
        with pytest.raises(RagError):
            locked.replace(DriveFile(**{**f.__dict__, "version": "2"}), [Chunk("replacement")], [[1.0] * 2])
        assert locked.versions() == {"a": "1"}
        assert store.search([1.0] * 768)[0][0].text == "original"
        locked.reconcile(set())
        assert locked.counts() == {"documents": 0, "chunks": 0}


@pytest.mark.integration
def test_lock_excludes_concurrent_sync_and_releases(store):
    with store.sync_lock():
        with pytest.raises(RagError):
            with store.sync_lock():
                pass
    with store.sync_lock():
        pass


@pytest.mark.integration
def test_persistence_session_isolation_and_stale_answer(store):
    with store.sync_lock() as locked:
        locked.bind("test-folder", PIPELINE_ID)
    a = store.new_session()
    b = store.new_session()
    turn = str(uuid4())
    store.save_turn(a, turn, "Question", Answer("Answer", [], "Question"), 0)
    store.save_turn(a, turn, "Question", Answer("Answer", [], "Question"), 0)
    reloaded = Store(store.settings)
    assert len(reloaded.history(a)) == 1 and reloaded.history(b) == []
    with store.connect() as c:
        c.execute("update python_rag.library set revision=1")
    with pytest.raises(RagError):
        store.save_turn(a, str(uuid4()), "q", Answer("a", [], "q"), 0)


@pytest.mark.integration
def test_folder_and_embedding_binding(store):
    with store.sync_lock() as locked:
        locked.bind("test-folder", PIPELINE_ID)
        with pytest.raises(RagError):
            locked.bind("wrong-folder", PIPELINE_ID)
        with pytest.raises(RagError):
            locked.bind("test-folder", "wrong-model")


@pytest.mark.integration
def test_pending_generation_is_invisible_until_atomic_activation(store):
    file = DriveFile("a", "A", "1", "text/plain", "https://drive.google.com/file/d/a/view")
    with store.sync_lock() as locked:
        locked.bind("test-folder", PIPELINE_ID)
        locked.replace(file, [Chunk("working")], [[1.0] * 768])
        pending = locked.create_generation("new", "ollama", "other", 3, 500, 50)
        locked.stage_document(pending, file, [Chunk("pending")], [[1.0] * 3])
        assert store.search([1.0] * 768)[0][0].text == "working"
        locked.activate_generation(pending, {"a": "1"})
    assert store.search([1.0] * 3)[0][0].text == "pending"


@pytest.mark.integration
def test_failed_activation_keeps_working_generation(store):
    file = DriveFile("a", "A", "1", "text/plain", "https://drive.google.com/file/d/a/view")
    with store.sync_lock() as locked:
        locked.bind("test-folder", PIPELINE_ID)
        locked.replace(file, [Chunk("working")], [[1.0] * 768])
        pending = locked.create_generation("new", "ollama", "other", 3, 500, 50)
        locked.stage_document(pending, file, [Chunk("pending")], [[1.0] * 3])
        with pytest.raises(RagError):
            locked.activate_generation(pending, {"a": "2"})
    assert store.search([1.0] * 768)[0][0].text == "working"
