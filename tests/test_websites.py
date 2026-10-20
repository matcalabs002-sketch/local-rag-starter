import httpx
import pytest

from rag.config import RagError
from rag.types import WebsiteSource
from rag.websites import WebsiteCrawler, WebsiteSyncEngine, canonical_url


PUBLIC = lambda *args, **kwargs: [(2, 1, 6, "", ("93.184.216.34", 443))]


def client_for(routes):
    def handler(request):
        value = routes.get(str(request.url))
        if callable(value):
            return value(request)
        return value or httpx.Response(404, request=request)

    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)


def test_canonical_url_is_stable_and_rejects_unsafe_targets():
    assert canonical_url("https://Example.com/docs/?utm_source=x&b=2&a=1#part") == "https://example.com/docs/?a=1&b=2"
    for value in ("http://example.com", "https://user:pass@example.com", "https://example.com:8443"):
        with pytest.raises(RagError):
            canonical_url(value)
    with pytest.raises(RagError):
        WebsiteCrawler(client_for({}), resolver=lambda *a, **k: [(2, 1, 6, "", ("127.0.0.1", 443))]).crawl(
            WebsiteSource("s", "https://localhost/", 1)
        )


def test_crawl_respects_bounds_extracts_content_and_deduplicates_links():
    routes = {
        "https://example.com/robots.txt": httpx.Response(
            200, headers={"content-type": "text/plain"}, text="User-agent: *\nAllow: /"
        ),
        "https://example.com/": httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text="""
            <html><head><title>Home</title><style>secret</style></head><body>
            <nav>menu <a href="/about?utm_source=nav">About</a></nav>
            <main><h1>Useful heading</h1><p>Useful paragraph.</p>
            <a href="/about">About again</a></main><footer>hidden footer</footer></body></html>""",
        ),
        "https://example.com/about": httpx.Response(
            200, headers={"content-type": "text/html"}, text="<title>About</title><main><p>Second page.</p></main>"
        ),
    }
    pages = WebsiteCrawler(client_for(routes), PUBLIC).crawl(WebsiteSource("s", "https://example.com/", 2))
    assert [page.file.url for page in pages] == ["https://example.com/", "https://example.com/about"]
    assert pages[0].file.source_kind == "website" and pages[0].file.source_group == "s"
    assert "Useful paragraph" in pages[0].text
    assert "secret" not in pages[0].text and "hidden footer" not in pages[0].text
    assert pages[0].file.id.startswith("site:")


def test_crawl_rejects_non_html_and_outside_host_redirect():
    base = {"https://example.com/robots.txt": httpx.Response(404)}
    routes = {
        **base,
        "https://example.com/": httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"pdf"),
    }
    with pytest.raises(RagError, match="HTML"):
        WebsiteCrawler(client_for(routes), PUBLIC).crawl(WebsiteSource("s", "https://example.com/", 1))
    routes = {**base, "https://example.com/": httpx.Response(302, headers={"location": "https://other.example/page"})}
    with pytest.raises(RagError, match="outside"):
        WebsiteCrawler(client_for(routes), PUBLIC).crawl(WebsiteSource("s", "https://example.com/", 1))


def test_redirect_dns_rebinding_to_private_is_blocked():
    calls = 0

    def resolver(*args, **kwargs):
        nonlocal calls
        calls += 1
        address = "93.184.216.34" if calls < 4 else "10.0.0.2"
        return [(2, 1, 6, "", (address, 443))]

    routes = {
        "https://example.com/robots.txt": httpx.Response(
            200, headers={"content-type": "text/html"}, text="User-agent: *\nAllow: /"
        ),
        "https://example.com/": httpx.Response(302, headers={"location": "/next"}),
        "https://example.com/next": httpx.Response(
            200, headers={"content-type": "text/html"}, text="<p>Should never load.</p>"
        ),
    }
    with pytest.raises(RagError, match="public internet"):
        WebsiteCrawler(client_for(routes), resolver).crawl(WebsiteSource("s", "https://example.com/", 1))


def test_robots_disallow_results_in_visible_failure():
    routes = {
        "https://example.com/robots.txt": httpx.Response(
            200, headers={"content-type": "text/html"}, text="User-agent: *\nDisallow: /"
        )
    }
    with pytest.raises(RagError, match="No crawlable"):
        WebsiteCrawler(client_for(routes), PUBLIC).crawl(WebsiteSource("s", "https://example.com/", 1))


def test_sync_prepares_every_page_before_atomic_publish():
    source = WebsiteSource("s", "https://example.com/", 2)
    pages = WebsiteCrawler(
        client_for(
            {
                "https://example.com/robots.txt": httpx.Response(404),
                "https://example.com/": httpx.Response(
                    200,
                    headers={"content-type": "text/html"},
                    text="<p>" + ("one " * 80) + '</p><a href="/two">Two</a>',
                ),
                "https://example.com/two": httpx.Response(
                    200, headers={"content-type": "text/html"}, text="<p>" + ("two " * 80) + "</p>"
                ),
            }
        ),
        PUBLIC,
    ).crawl(source)

    class Crawler:
        def crawl(self, _):
            return pages

    class Store:
        def __init__(self):
            self.published = None
            self.states = []

        def update_website_source(self, *args, **kwargs):
            self.states.append((args, kwargs))

        def replace_site(self, site_id, prepared):
            self.published = (site_id, prepared)

    class Models:
        def embed(self, texts):
            return [[1.0, 2.0] for _ in texts]

    store = Store()
    result = WebsiteSyncEngine(store, Models(), Crawler(), chunk_size=200, chunk_overlap=20).sync_site(source)
    assert result.pages == 2 and result.chunks >= 2
    assert store.published[0] == "s" and len(store.published[1]) == 2
    assert store.states[0][1]["status"] == "syncing"


def test_activity_log_failure_does_not_relabel_a_published_site():
    source = WebsiteSource("s", "https://example.com/", 1)

    class Crawler:
        def crawl(self, _):
            from rag.types import DriveFile, WebsitePage

            file = DriveFile("site:x", "X", "1", "text/html", source.start_url, 10, "website", source.id)
            return [WebsitePage(file, "readable " * 50)]

    class Store:
        def __init__(self):
            self.published = False
            self.states = []

        def log_activity(self, *args):
            raise RuntimeError("activity unavailable")

        def update_website_source(self, *args, **kwargs):
            self.states.append(kwargs["status"])

        def replace_site(self, *args):
            self.published = True

    class Models:
        def embed(self, texts):
            return [[1.0, 2.0] for _ in texts]

    store = Store()
    result = WebsiteSyncEngine(store, Models(), Crawler(), chunk_size=200, chunk_overlap=20).sync_site(source)
    assert result.pages == 1 and store.published
    assert store.states == ["syncing"]


def test_sync_failure_never_calls_replace_site():
    source = WebsiteSource("s", "https://example.com/", 1)

    class Crawler:
        def crawl(self, _):
            from rag.types import DriveFile, WebsitePage

            file = DriveFile("site:x", "X", "1", "text/html", source.start_url, 10, "website", source.id)
            return [WebsitePage(file, "readable " * 50)]

    class Store:
        published = False

        def update_website_source(self, *args, **kwargs):
            pass

        def replace_site(self, *args):
            self.published = True

    class Models:
        def embed(self, texts):
            raise RagError("Embedding failed.")

    store = Store()
    with pytest.raises(RagError, match="Embedding failed"):
        WebsiteSyncEngine(store, Models(), Crawler(), chunk_size=200, chunk_overlap=20).sync_site(source)
    assert not store.published


def test_full_run_continues_after_one_site_fails():
    sources = [WebsiteSource("bad", "https://bad.example/", 1), WebsiteSource("good", "https://good.example/", 1)]

    class Store:
        def website_sources(self, enabled_only=False):
            return sources

    class Engine(WebsiteSyncEngine):
        attempted = []

        def sync_site(self, source):
            self.attempted.append(source.id)
            if source.id == "bad":
                raise RagError("Could not read this site.")
            return "ok"

    engine = Engine(Store(), object(), object())
    with pytest.raises(RagError, match="1 website import"):
        engine.run()
    assert engine.attempted == ["bad", "good"]
