"""Bounded, same-host imports for public HTTPS websites."""

from __future__ import annotations
import logging

from collections import deque
from dataclasses import dataclass
from hashlib import sha256
from html.parser import HTMLParser
from ipaddress import ip_address
from socket import SOCK_STREAM, getaddrinfo
from time import monotonic
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser
from uuid import uuid4

import httpx

from .config import CHUNK_OVERLAP, CHUNK_SIZE, RagError
from .loaders import split_text_chunks
from .types import DriveFile, WebsitePage, WebsiteSource

DEFAULT_MAX_PAGES = 10
MAX_SITE_PAGES = 50
MAX_PAGE_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 5
REQUEST_SECONDS = 15
USER_AGENT = "ChatbotRAGStarter/0.1"
TRACKING_PARAMETERS = {"fbclid", "gclid", "mc_cid", "mc_eid"}
_WEB_CLIENT = httpx.Client(
    timeout=REQUEST_SECONDS,
    follow_redirects=False,
    trust_env=False,
    headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
)


def canonical_url(value: str) -> str:
    """Return a stable public HTTPS URL without fragments or tracking parameters."""
    try:
        parsed = urlsplit(value.strip())
        host = (parsed.hostname or "").encode("idna").decode("ascii").lower()
    except (UnicodeError, ValueError):
        raise RagError("Enter a valid public HTTPS website address.") from None
    if parsed.scheme.lower() != "https" or not host or parsed.username or parsed.password:
        raise RagError("Website imports require a public HTTPS address without credentials.")
    try:
        port = parsed.port
    except ValueError:
        raise RagError("Enter a valid public HTTPS website address.") from None
    if port not in (None, 443):
        raise RagError("Website imports only support the standard HTTPS port.")
    path = "/" + "/".join(segment for segment in parsed.path.split("/") if segment)
    if parsed.path.endswith("/") and path != "/":
        path += "/"
    query = urlencode(
        sorted(
            (key, val)
            for key, val in parse_qsl(parsed.query, keep_blank_values=True)
            if not key.lower().startswith("utm_") and key.lower() not in TRACKING_PARAMETERS
        )
    )
    return urlunsplit(("https", host, path or "/", query, ""))


def _public_addresses(host: str, resolver=getaddrinfo) -> tuple[str, ...]:
    try:
        addresses = tuple(sorted({item[4][0] for item in resolver(host, 443, type=SOCK_STREAM)}))
    except OSError:
        raise RagError("The website address could not be resolved.") from None
    if not addresses:
        raise RagError("The website address could not be resolved.")
    if any(not ip_address(address).is_global for address in addresses):
        raise RagError("Website imports can only connect to public internet addresses.")
    return addresses


class _PageParser(HTMLParser):
    ignored = {"script", "style", "noscript", "svg", "canvas", "form", "nav", "footer", "aside"}
    blocks = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "pre", "td", "th"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.title_depth = 0
        self.title_parts: list[str] = []
        self.parts: list[str] = []
        self.links: list[str] = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        values = dict(attrs)
        if tag == "a" and values.get("href"):
            self.links.append(values["href"])
        if tag in self.ignored:
            self.depth += 1
        if tag == "title":
            self.title_depth += 1
        if not self.depth and tag in self.blocks:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in self.ignored and self.depth:
            self.depth -= 1
        if tag == "title" and self.title_depth:
            self.title_depth -= 1
        if not self.depth and tag in self.blocks:
            self.parts.append("\n")

    def handle_data(self, data):
        if self.title_depth:
            self.title_parts.append(data)
        if not self.depth and not self.title_depth:
            self.parts.append(data)

    def result(self) -> tuple[str, str, list[str]]:
        title = " ".join(" ".join(self.title_parts).split())
        lines = [" ".join(line.split()) for line in "".join(self.parts).splitlines()]
        text = "\n".join(line for line in lines if line)
        return title, text, self.links


class WebsiteCrawler:
    def __init__(self, client: httpx.Client | None = None, resolver=getaddrinfo):
        self.client = client or _WEB_CLIENT
        self.resolver = resolver

    def crawl(self, source: WebsiteSource) -> list[WebsitePage]:
        start = canonical_url(source.start_url)
        host = urlsplit(start).hostname
        _public_addresses(host, self.resolver)
        maximum = max(1, min(int(source.max_pages), MAX_SITE_PAGES))
        robots = self._robots(start)
        queued = deque([start])
        seen: set[str] = set()
        pages: list[WebsitePage] = []
        while queued and len(pages) < maximum:
            url = queued.popleft()
            if url in seen:
                continue
            seen.add(url)
            if not robots.can_fetch(USER_AGENT, url):
                continue
            final_url, body = self._fetch(url)
            if urlsplit(final_url).hostname != host:
                raise RagError("The website redirected outside the selected host. Nothing was replaced.")
            parser = _PageParser()
            try:
                parser.feed(body.decode("utf-8", errors="replace"))
            except Exception:
                raise RagError("A website page contained unreadable HTML. Nothing was replaced.") from None
            title, text, links = parser.result()
            if not text:
                raise RagError("A website page had no readable text. Nothing was replaced.")
            page_id = "site:" + sha256(final_url.encode()).hexdigest()
            version = sha256(text.encode()).hexdigest()
            file = DriveFile(
                page_id, title or final_url, version, "text/html", final_url, len(body), "website", source.id
            )
            pages.append(WebsitePage(file, text))
            for link in links:
                try:
                    candidate = canonical_url(urljoin(final_url, link))
                except RagError:
                    continue
                if urlsplit(candidate).hostname == host and candidate not in seen:
                    queued.append(candidate)
        if not pages:
            raise RagError("No crawlable HTML pages were found at this website.")
        return pages

    def _robots(self, start: str) -> RobotFileParser:
        parsed = urlsplit(start)
        url = urlunsplit(("https", parsed.netloc, "/robots.txt", "", ""))
        try:
            _, response = self._request(
                url, allow_not_found=True, content_types=("text/plain", "text/html", "application/xhtml+xml")
            )
        except RagError:
            raise RagError("The website robots.txt check failed. Nothing was imported.") from None
        rules = RobotFileParser()
        rules.set_url(url)
        if response is None:
            rules.parse([])
        else:
            rules.parse(response.decode("utf-8", errors="replace").splitlines())
        return rules

    def _fetch(self, url: str) -> tuple[str, bytes]:
        final, body = self._request(url)
        if body is None:
            raise RagError("A website page could not be downloaded. Nothing was replaced.")
        return final, body

    def _request(
        self, url: str, allow_not_found=False, content_types=("text/html", "application/xhtml+xml")
    ) -> tuple[str, bytes | None]:
        current = canonical_url(url)
        origin_host = urlsplit(current).hostname
        for _ in range(MAX_REDIRECTS + 1):
            _public_addresses(urlsplit(current).hostname, self.resolver)
            try:
                with self.client.stream("GET", current) as response:
                    self._validate_peer(response)
                    if allow_not_found and response.status_code == 404:
                        return current, None
                    if response.status_code in (301, 302, 303, 307, 308):
                        location = response.headers.get("location")
                        if not location:
                            raise RagError("The website returned an invalid redirect.")
                        target = canonical_url(urljoin(current, location))
                        if urlsplit(target).hostname != origin_host:
                            raise RagError("The website redirected outside the selected host.")
                        current = target
                        continue
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
                    if content_type not in content_types:
                        raise RagError("Website import only supports HTML pages.")
                    body = bytearray()
                    for part in response.iter_bytes():
                        body.extend(part)
                        if len(body) > MAX_PAGE_BYTES:
                            raise RagError("A website page is larger than the 2 MB import limit.")
                    return canonical_url(str(response.url)), bytes(body)
            except RagError:
                raise
            except (httpx.HTTPError, OSError):
                raise RagError("The website did not respond with a readable public page.") from None
        raise RagError("The website redirected too many times.")

    @staticmethod
    def _validate_peer(response: httpx.Response):
        stream = response.extensions.get("network_stream")
        if not stream:
            return
        try:
            peer = stream.get_extra_info("server_addr") or stream.get_extra_info("peername")
            address = peer[0] if isinstance(peer, tuple) else peer
            if address and not ip_address(address).is_global:
                raise RagError("The website connection resolved to a private address and was blocked.")
        except (AttributeError, ValueError, TypeError):
            return


@dataclass(frozen=True)
class WebsiteSyncResult:
    pages: int
    chunks: int
    duration_ms: int


class WebsiteSyncEngine:
    """Prepare a complete crawl first, then publish the entire site in one transaction."""

    def __init__(self, store, models, crawler: WebsiteCrawler | None = None, chunk_size=None, chunk_overlap=None):
        self.store, self.models = store, models
        self.crawler = crawler or WebsiteCrawler()
        settings = getattr(models, "settings", None)
        self.chunk_size = chunk_size if chunk_size is not None else getattr(settings, "chunk_size", CHUNK_SIZE)
        self.chunk_overlap = (
            chunk_overlap if chunk_overlap is not None else getattr(settings, "chunk_overlap", CHUNK_OVERLAP)
        )

    def sync_site(self, source: WebsiteSource) -> WebsiteSyncResult:
        started = monotonic()
        job_id = str(uuid4())
        self._activity(job_id, "website crawl", "running", "Checking the complete bounded website.", source)
        self.store.update_website_source(source.id, status="syncing", error=None)
        try:
            pages = self.crawler.crawl(source)
            self._activity(job_id, "website crawl", "success", f"{len(pages)} readable page(s) found.", source)
            prepared = []
            total_chunks = 0
            self._activity(job_id, "website indexing", "running", "Preparing passages and embeddings.", source)
            for page in pages:
                chunks = split_text_chunks(page.text, self.chunk_size, self.chunk_overlap)
                vectors = self.models.embed([chunk.text for chunk in chunks])
                prepared.append((page.file, chunks, vectors))
                total_chunks += len(chunks)
            self.store.replace_site(source.id, prepared)
            duration = int((monotonic() - started) * 1000)
            self._activity(
                job_id,
                "complete",
                "success",
                f"{len(pages)} page(s) and {total_chunks} passage(s) indexed.",
                source,
                duration,
            )
            return WebsiteSyncResult(len(pages), total_chunks, duration)
        except RagError as error:
            try:
                self.store.update_website_source(source.id, status="error", error=str(error))
            except Exception:
                raise RagError(str(error) + " The website error status could not be saved.") from None
            self._activity(job_id, "complete", "error", str(error), source, int((monotonic() - started) * 1000))
            raise
        except Exception:
            message = "Website import stopped unexpectedly. The last complete website index was kept."
            self.store.update_website_source(source.id, status="error", error=message)
            self._activity(job_id, "complete", "error", message, source, int((monotonic() - started) * 1000))
            raise RagError(message) from None

    def run(self, site_id: str | None = None) -> dict[str, WebsiteSyncResult]:
        if hasattr(self.store, "assert_pipeline"):
            self.store.assert_pipeline(self.models.settings)
        sources = self.store.website_sources(enabled_only=True)
        if site_id:
            sources = [source for source in sources if source.id == site_id]
            if not sources:
                raise RagError("The selected website source was not found.")
            return {sources[0].id: self.sync_site(sources[0])}
        results = {}
        errors = []
        for source in sources:
            try:
                results[source.id] = self.sync_site(source)
            except RagError as error:
                errors.append(f"{source.start_url}: {error}")
        if errors:
            raise RagError(f"{len(errors)} website import(s) failed. " + " | ".join(errors))
        return results

    def _activity(self, job_id, stage, status, message, source, duration_ms=None):
        log = getattr(self.store, "log_activity", None)
        if callable(log):
            try:
                log(job_id, "website sync", stage, status, message, source.id, source.start_url, duration_ms)
            except Exception:
                # The source row and published generation are authoritative. An
                # observability write must never relabel a successful import as
                # failed or hide the original crawl/indexing error.
                logging.getLogger(__name__).warning(
                    "Website activity could not be recorded; source status remains authoritative."
                )
                return False
        return True
