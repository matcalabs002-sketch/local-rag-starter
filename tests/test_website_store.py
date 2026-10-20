import os
from urllib.parse import urlparse

import pytest

from rag.config import PIPELINE_ID, RagError, Settings
from rag.store import Store
from rag.types import Chunk, DriveFile


@pytest.fixture
def website_store():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a disposable local PostgreSQL database")
    assert urlparse(url).hostname in ("localhost", "127.0.0.1"), "Never run against a remote database"
    store = Store(Settings(database_url=url, folder_id="test-folder"))
    store.initialize()
    with store.connect() as connection:
        connection.execute("""truncate python_rag.activity,python_rag.document_exclusions,
            python_rag.generation_chunks,python_rag.generation_documents,python_rag.website_sources,
            python_rag.index_generations,python_rag.turns,python_rag.sessions,python_rag.chunks,
            python_rag.documents,python_rag.library restart identity cascade""")
    store.initialize()
    return store


def web_file(site_id, page_id, version="1"):
    return DriveFile(
        "site:" + page_id,
        page_id.title(),
        version,
        "text/html",
        "https://example.com/" + page_id,
        100,
        "website",
        site_id,
    )


@pytest.mark.integration
def test_atomic_site_replace_and_drive_reconcile_are_isolated(website_store):
    with website_store.sync_lock() as store:
        store.bind("test-folder", PIPELINE_ID)
        site_id = store.add_site("https://example.com/", 5)
        first = [(web_file(site_id, "one"), [Chunk("old page")], [[1.0] * 768])]
        store.replace_site(site_id, first)
        assert store.sites()[0]["status"] == "ready" and store.sites()[0]["page_count"] == 1
        store.reconcile(set())
        assert store.versions() == {}
        assert store.counts() == {"documents": 1, "chunks": 1}
        invalid = [(web_file(site_id, "two"), [Chunk("new page")], [[1.0] * 2])]
        with pytest.raises(RagError, match="768"):
            store.replace_site(site_id, invalid)
        assert store.search([1.0] * 768)[0][0].text == "old page"


@pytest.mark.integration
def test_duplicate_source_and_complete_replacement(website_store):
    with website_store.sync_lock() as store:
        store.bind("test-folder", PIPELINE_ID)
        site_id = store.add_site("https://example.com/?utm_source=test", 5)
        assert store.add_site("https://EXAMPLE.com/", 8) == site_id
        assert store.sites()[0]["max_pages"] == 8
        store.replace_site(
            site_id,
            [
                (web_file(site_id, "one"), [Chunk("one")], [[1.0] * 768]),
                (web_file(site_id, "two"), [Chunk("two")], [[1.0] * 768]),
            ],
        )
        store.replace_site(site_id, [(web_file(site_id, "three"), [Chunk("three")], [[1.0] * 768])])
        documents = store.documents()
        assert [(row["id"], row["source_kind"]) for row in documents] == [("site:three", "website")]


@pytest.mark.integration
def test_staged_site_is_invisible_until_generation_activation(website_store):
    with website_store.sync_lock() as store:
        store.bind("test-folder", PIPELINE_ID)
        site_id = store.add_site("https://example.com/", 5)
        store.replace_site(site_id, [(web_file(site_id, "one"), [Chunk("active")], [[1.0] * 768])])
        pending = store.create_generation("new", "ollama", "other", 3, 500, 50)
        store.stage_site_generation(
            pending, site_id, [(web_file(site_id, "one", "2"), [Chunk("pending")], [[1.0] * 3])]
        )
        assert store.search([1.0] * 768)[0][0].text == "active"
        with website_store.connect() as connection:
            assert (
                connection.execute(
                    """select content from python_rag.generation_chunks
                where generation_id=%s""",
                    (pending,),
                ).fetchone()["content"]
                == "pending"
            )
