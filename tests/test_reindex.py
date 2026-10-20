from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace

import pytest

from rag.config import RagError
from rag.reindex import ReindexEngine
from rag.types import DriveFile, WebsitePage, WebsiteSource


DRIVE_FILE = DriveFile("drive-1", "Handbook", "1", "text/plain", "https://drive.example/1")
WEB_FILE = DriveFile("site:one", "About", "web-1", "text/html", "https://example.com/", 100, "website", "site-1")


class Store:
    def __init__(self):
        self.staged = []
        self.activated = None
        self.errors = []

    @contextmanager
    def sync_lock(self):
        yield self

    def bind_folder(self, folder):
        assert folder == "folder"

    def resumable_generation(self, pipeline):
        return None

    def create_generation(self, *args):
        return "generation"

    def log_activity(self, *args, **kwargs):
        pass

    def exclusions(self):
        return {}

    def generation_versions(self, generation):
        return {}

    def stage_document(self, generation, file, chunks, vectors):
        self.staged.append(file.id)

    def website_sources(self, enabled_only=False):
        return [WebsiteSource("site-1", "https://example.com/", 1)]

    def stage_site_generation(self, generation, site_id, prepared):
        self.staged.extend(file.id for file, _, _ in prepared)

    def reconcile_generation(self, generation, expected):
        self.reconciled = set(expected)

    def activate_generation(self, generation, expected):
        self.activated = dict(expected)

    def prune_generations(self):
        pass

    def generation_error(self, generation, error):
        self.errors.append(error)


class Drive:
    def snapshot(self):
        return [DRIVE_FILE], []

    def download(self, file):
        return b"drive text"

    def verify(self, file):
        pass


class Models:
    settings = SimpleNamespace(
        embedding_provider="ollama", embedding_model="nomic-embed-text:v1.5", embedding_dimensions=768
    )

    def embed(self, texts):
        return [[1.0] * 768 for _ in texts]


class Crawler:
    fail = False

    def crawl(self, source):
        if self.fail:
            raise RagError("Website unavailable. The working index was kept.")
        return [WebsitePage(WEB_FILE, "website text " * 30)]


def loader(file, body, **kwargs):
    from rag.types import Chunk

    return [Chunk(body.decode())]


def test_rebuild_includes_drive_and_website_before_activation():
    store = Store()
    result = ReindexEngine(store, Drive(), Models(), "folder", loader=loader, crawler=Crawler()).run()
    assert result == "generation"
    assert store.staged == ["drive-1", "site:one"]
    assert store.reconciled == {"drive-1", "site:one"}
    assert store.activated == {"drive-1": "1", "site:one": "web-1"}


def test_failed_website_rebuild_keeps_generation_inactive():
    store = Store()
    crawler = Crawler()
    crawler.fail = True
    with pytest.raises(RagError, match="Website unavailable"):
        ReindexEngine(store, Drive(), Models(), "folder", loader=loader, crawler=crawler).run()
    assert store.activated is None
    assert store.errors == ["Website unavailable. The working index was kept."]


def test_website_change_before_activation_keeps_working_index():
    store = Store()

    class ChangingCrawler:
        calls = 0

        def crawl(self, source):
            self.calls += 1
            version = "web-1" if self.calls == 1 else "web-2"
            return [WebsitePage(replace(WEB_FILE, version=version), "website text " * 30)]

    with pytest.raises(RagError, match="website changed"):
        ReindexEngine(store, Drive(), Models(), "folder", loader=loader, crawler=ChangingCrawler()).run()
    assert store.activated is None
