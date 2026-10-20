import logging
from time import monotonic
from uuid import uuid4
from .config import RagError, Settings, pipeline_id
from .loaders import load_chunks


class SyncEngine:
    def __init__(self, store, drive, models, folder, loader=load_chunks):
        self.store, self.drive, self.models, self.folder = store, drive, models, folder
        if loader is load_chunks:
            settings = getattr(models, "settings", Settings())
            self.loader = lambda file, data: load_chunks(file, data, settings.chunk_size, settings.chunk_overlap)
        else:
            self.loader = loader

    def run(self):
        job_id = str(uuid4())
        with self.store.sync_lock() as store:
            try:
                started = monotonic()
                self._activity(store, job_id, "folder listing", "running", "Checking the complete Drive folder.")
                store.bind(self.folder, pipeline_id(getattr(self.models, "settings", Settings())))
                store.set_status(status="syncing", message="Checking the complete Drive folder…")
                files, skipped = self.drive.snapshot()
                excluded = set(store.exclusions()) if hasattr(store, "exclusions") else set()
                files = [file for file in files if file.id not in excluded]
                self._activity(
                    store,
                    job_id,
                    "folder listing",
                    "success",
                    f"{len(files)} supported document(s), {len(excluded)} excluded.",
                    duration_ms=int((monotonic() - started) * 1000),
                )
                store.set_status(status="syncing", message="Comparing documents…", skipped=skipped)
                store.reconcile({f.id for f in files})
                versions = store.versions()
                errors = []
                indexed = 0
                for file in files:
                    if versions.get(file.id) == file.version:
                        continue
                    store.set_status(status="syncing", message="Reading " + file.name)
                    document_started = monotonic()
                    self._activity(store, job_id, "document", "running", "Reading and indexing.", file.id, file.name)
                    try:
                        chunks = self.loader(file, self.drive.download(file))
                        if not chunks:
                            raise RagError("No readable text was found.")
                        vectors = self.models.embed([c.text for c in chunks])
                        self.drive.verify(file)
                        store.replace(file, chunks, vectors)
                        indexed += 1
                        self._activity(
                            store,
                            job_id,
                            "document",
                            "success",
                            f"{len(chunks)} passage(s) indexed.",
                            file.id,
                            file.name,
                            int((monotonic() - document_started) * 1000),
                        )
                    except RagError as error:
                        errors.append(file.name + ": " + str(error))
                        self._activity(
                            store,
                            job_id,
                            "document",
                            "error",
                            str(error),
                            file.id,
                            file.name,
                            int((monotonic() - document_started) * 1000),
                        )
                if errors:
                    raise RagError(f"{indexed} document(s) updated. " + " | ".join(errors))
                counts = store.counts()
                store.set_status(
                    status="ready",
                    message=f"Up to date · {counts['documents']} documents · {indexed} updated this run",
                    skipped=skipped,
                    success=True,
                )
                self._activity(
                    store,
                    job_id,
                    "complete",
                    "success",
                    f"{counts['documents']} document(s), {counts['chunks']} passage(s).",
                    duration_ms=int((monotonic() - started) * 1000),
                )
                if hasattr(store, "purge_activity"):
                    store.purge_activity()
                return counts
            except RagError as error:
                store.set_status(status="error", message=str(error))
                try:
                    self._activity(store, job_id, "complete", "error", str(error))
                except Exception:
                    logging.getLogger(__name__).warning("Sync error could not be written to activity.")
                raise
            except Exception:
                # No raw database/provider errors in the UI or status table.
                message = "Sync stopped because of a processing or database error. Completed documents were saved; incomplete replacements were not published. Check Setup and retry."
                try:
                    store.set_status(status="error", message=message)
                except Exception:
                    # Caller records this failure in the independent local runtime status.
                    raise RagError(message + " The database is also unavailable for saving sync status.") from None
                raise RagError(message) from None

    @staticmethod
    def _activity(store, job_id, stage, status, message="", document_id=None, document_name=None, duration_ms=None):
        if hasattr(store, "log_activity"):
            store.log_activity(job_id, "sync", stage, status, message, document_id, document_name, duration_ms)
