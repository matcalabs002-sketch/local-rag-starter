"""Build and atomically activate a versioned search index."""

import logging
from time import monotonic
from uuid import uuid4

from .config import CHUNK_OVERLAP, CHUNK_SIZE, RagError, pipeline_id
from .loaders import load_chunks, split_text_chunks
from .websites import WebsiteCrawler


class ReindexEngine:
    def __init__(
        self,
        store,
        drive,
        models,
        folder,
        loader=load_chunks,
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        crawler=None,
    ):
        self.store, self.drive, self.models, self.folder = store, drive, models, folder
        self.loader = loader
        self.chunk_size, self.chunk_overlap = chunk_size, chunk_overlap
        self.crawler = crawler or WebsiteCrawler()

    @property
    def pipeline(self):
        return pipeline_id(self.models.settings, self.chunk_size, self.chunk_overlap)

    def run(self, cancelled=lambda: False):
        job_id = str(uuid4())
        started = monotonic()
        with self.store.sync_lock() as store:
            store.bind_folder(self.folder)
            pending = store.resumable_generation(self.pipeline)
            generation = (
                pending["id"]
                if pending
                else store.create_generation(
                    self.pipeline,
                    self.models.settings.embedding_provider,
                    self.models.settings.embedding_model,
                    self.models.settings.embedding_dimensions,
                    self.chunk_size,
                    self.chunk_overlap,
                )
            )
            try:
                store.log_activity(
                    job_id, "rebuild", "folder listing", "running", "Checking all configured document sources."
                )
                files, skipped = self.drive.snapshot()
                exclusions = set(store.exclusions())
                files = [file for file in files if file.id not in exclusions]
                expected = {file.id: file.version for file in files}
                website_expected = {}
                complete = store.generation_versions(generation)
                for file in files:
                    if cancelled():
                        store.finish_generation(generation, "cancelled", "Cancelled by the user.")
                        store.log_activity(job_id, "rebuild", "complete", "cancelled", "The working index was kept.")
                        raise RagError("The rebuild was cancelled. The working index was kept.")
                    if complete.get(file.id) == file.version:
                        continue
                    file_started = monotonic()
                    store.log_activity(
                        job_id, "rebuild", "document", "running", "Building a pending index.", file.id, file.name
                    )
                    chunks = self.loader(
                        file, self.drive.download(file), chunk_size=self.chunk_size, chunk_overlap=self.chunk_overlap
                    )
                    vectors = self.models.embed([chunk.text for chunk in chunks])
                    self.drive.verify(file)
                    store.stage_document(generation, file, chunks, vectors)
                    store.log_activity(
                        job_id,
                        "rebuild",
                        "document",
                        "success",
                        f"{len(chunks)} passage(s) prepared.",
                        file.id,
                        file.name,
                        int((monotonic() - file_started) * 1000),
                    )
                website_sources = self._website_sources(store)
                for source in website_sources:
                    if cancelled():
                        store.finish_generation(generation, "cancelled", "Cancelled by the user.")
                        store.log_activity(job_id, "rebuild", "complete", "cancelled", "The working index was kept.")
                        raise RagError("The rebuild was cancelled. The working index was kept.")
                    site_started = monotonic()
                    store.log_activity(
                        job_id,
                        "rebuild",
                        "website",
                        "running",
                        "Crawling and preparing a complete website index.",
                        source.id,
                        source.start_url,
                    )
                    prepared = self._prepare_site(source, with_vectors=True)
                    store.stage_site_generation(generation, source.id, prepared)
                    site_versions = {file.id: file.version for file, _, _ in prepared}
                    website_expected[source.id] = site_versions
                    expected.update(site_versions)
                    store.log_activity(
                        job_id,
                        "rebuild",
                        "website",
                        "success",
                        f"{len(prepared)} page(s) prepared.",
                        source.id,
                        source.start_url,
                        int((monotonic() - site_started) * 1000),
                    )
                fresh, ignored = self.drive.snapshot()
                fresh = {file.id: file.version for file in fresh if file.id not in exclusions}
                drive_expected = {file.id: file.version for file in files}
                if fresh != drive_expected:
                    raise RagError(
                        "A document source changed during rebuilding. Retry to finish against the latest complete source list."
                    )
                latest_sources = self._website_sources(store)
                initial_config = {(source.id, source.start_url, source.max_pages) for source in website_sources}
                latest_config = {(source.id, source.start_url, source.max_pages) for source in latest_sources}
                if latest_config != initial_config:
                    raise RagError(
                        "Website sources changed during rebuilding. Retry to include the latest source list."
                    )
                for source in latest_sources:
                    current = {page.file.id: page.file.version for page in self.crawler.crawl(source)}
                    if current != website_expected[source.id]:
                        raise RagError("A website changed during rebuilding. Retry to include its latest pages.")
                store.reconcile_generation(generation, set(expected))
                store.activate_generation(generation, expected)
                # Nothing after atomic activation may turn a successful switch
                # into a reported failure: the caller must persist matching
                # embedding settings immediately after this method returns.
                try:
                    store.prune_generations()
                    store.log_activity(
                        job_id,
                        "rebuild",
                        "complete",
                        "success",
                        f"{len(expected)} document(s) activated. The previous index is retained for recovery.",
                        duration_ms=int((monotonic() - started) * 1000),
                    )
                except Exception:
                    try:
                        store.set_status(
                            "ready", "The replacement index is active. Activity cleanup needs a retry.", success=True
                        )
                    except Exception:
                        logging.getLogger(__name__).warning(
                            "Index activated; post-activation cleanup and status recording need attention."
                        )
                return generation
            except RagError as error:
                # Keep a partially built generation resumable; it is never searchable.
                store.generation_error(generation, str(error))
                store.log_activity(
                    job_id, "rebuild", "complete", "error", str(error), duration_ms=int((monotonic() - started) * 1000)
                )
                raise

    def rollback(self, generation):
        with self.store.sync_lock() as store:
            files, _ = self.drive.snapshot()
            exclusions = set(store.exclusions())
            expected = {file.id: file.version for file in files if file.id not in exclusions}
            for source in self._website_sources(store):
                expected.update({page.file.id: page.file.version for page in self.crawler.crawl(source)})
            store.rollback_generation(generation, expected)

    @staticmethod
    def _website_sources(store):
        method = getattr(store, "website_sources", None)
        return method(enabled_only=True) if callable(method) else []

    def _prepare_site(self, source, with_vectors=True):
        prepared = []
        for page in self.crawler.crawl(source):
            chunks = split_text_chunks(page.text, self.chunk_size, self.chunk_overlap)
            vectors = self.models.embed([chunk.text for chunk in chunks]) if with_vectors else []
            prepared.append((page.file, chunks, vectors))
        return prepared
