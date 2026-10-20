from contextlib import contextmanager
import pytest
from rag.config import RagError
from rag.types import DriveFile, Chunk
from rag.sync import SyncEngine

FILE = DriveFile("a", "Handbook", "1", "text/plain", "https://drive.google.com/file/d/a/view")


class Drive:
    files = [FILE]
    fail = False
    changed = False

    def snapshot(self):
        if self.fail:
            raise RagError("Incomplete listing")
        return self.files, []

    def download(self, file):
        return b"hello"

    def verify(self, file):
        if self.changed:
            raise RagError("Changed during indexing")


class Models:
    fail = False

    def embed(self, texts, query=False):
        if self.fail:
            raise RagError("Embedding failed")
        return [[1.0] * 768 for _ in texts]


class Store:
    def __init__(self):
        self.docs = {}
        self.replacements = 0
        self.status = {}
        self.locked = False

    @contextmanager
    def sync_lock(self):
        if self.locked:
            raise RagError("Another sync is running")
        self.locked = True
        try:
            yield self
        finally:
            self.locked = False

    def bind(self, folder, pipeline):
        pass

    def reconcile(self, ids):
        self.docs = {k: v for k, v in self.docs.items() if k in ids}

    def versions(self):
        return {k: v["version"] for k, v in self.docs.items()}

    def replace(self, file, chunks, vectors):
        self.docs[file.id] = {"version": file.version, "chunks": chunks}
        self.replacements += 1

    def set_status(self, **kwargs):
        self.status.update(kwargs)

    def counts(self):
        return {"documents": len(self.docs), "chunks": sum(len(v["chunks"]) for v in self.docs.values())}


@pytest.fixture
def parts():
    store = Store()
    drive = Drive()
    models = Models()
    engine = SyncEngine(store, drive, models, "folder", loader=lambda f, b: [Chunk(b.decode())])
    return engine, store, drive, models


def test_upload_repeat_update_delete(parts):
    e, s, d, m = parts
    e.run()
    assert s.replacements == 1
    e.run()
    assert s.replacements == 1
    d.files = [DriveFile(**{**FILE.__dict__, "version": "2"})]
    e.run()
    assert s.replacements == 2
    d.files = []
    e.run()
    assert s.counts()["chunks"] == 0


def test_incomplete_listing_does_not_delete(parts):
    e, s, d, m = parts
    e.run()
    d.fail = True
    with pytest.raises(RagError):
        e.run()
    assert "a" in s.docs and s.status["status"] == "error"


def test_failed_update_keeps_prior_version(parts):
    e, s, d, m = parts
    e.run()
    d.files = [DriveFile(**{**FILE.__dict__, "version": "2"})]
    m.fail = True
    with pytest.raises(RagError):
        e.run()
    assert s.docs["a"]["version"] == "1"
    m.fail = False
    e.run()
    assert s.docs["a"]["version"] == "2"


def test_changed_during_download_not_published(parts):
    e, s, d, m = parts
    d.changed = True
    with pytest.raises(RagError):
        e.run()
    assert not s.docs


def test_single_sync(parts):
    e, s, d, m = parts
    s.locked = True
    with pytest.raises(RagError):
        e.run()
    assert not s.docs


def test_empty_extraction_is_failure(parts):
    e, s, d, m = parts
    e.loader = lambda f, b: []
    with pytest.raises(RagError):
        e.run()
    assert not s.docs
