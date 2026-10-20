"""Private immutable originals with transactional index publication."""

from hashlib import sha256
import logging
import os
from pathlib import Path
import re
import tempfile
from uuid import uuid4

from .config import RagError
from .loaders import load_chunks
from .types import DriveFile

MIME_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".csv": "text/csv",
}
LOGGER = logging.getLogger(__name__)


def upload_name(name):
    if not isinstance(name, str) or not name or len(name) > 200 or any(c in name for c in "/\\"):
        raise RagError("Use a filename without folders, up to 200 characters.")
    if name.startswith(".") or any(ord(c) < 32 for c in name):
        raise RagError("Hidden filenames and control characters are unsupported.")
    if Path(name).suffix.lower() not in MIME_TYPES:
        raise RagError("Unsupported format. Use a text PDF, DOCX, TXT, Markdown, or CSV file.")
    return name


class LocalSource:
    def __init__(self, store, settings):
        self.store, self.settings = store, settings
        self.root = Path(settings.data_dir).expanduser().resolve() / "documents"

    def snapshot(self):
        files = [
            DriveFile(row["id"], row["name"], row["version"], row["mime_type"], "", row["size"], "local")
            for row in self.store.uploads()
        ]
        # Verify every original before allowing a rebuild to reconcile anything.
        for file in files:
            self.verify(file)
        return files, []

    def blob_path(self, version):
        if not re.fullmatch("[a-f0-9]{64}", version):
            raise RagError("An original document has an invalid content hash.")
        if self.root.is_symlink():
            raise RagError("The documents directory cannot be a symbolic link.")
        path = self.root / version
        if path.is_symlink():
            raise RagError("Original document files cannot be symbolic links.")
        return path

    def download(self, file):
        try:
            path = self.blob_path(file.version)
            if path.stat().st_size > self.settings.max_file_bytes:
                raise RagError("The original exceeds MAX_FILE_BYTES.")
            raw = path.read_bytes()
        except OSError:
            raise RagError(
                "An original upload is missing or unreadable. Restore its original storage before rebuilding."
            ) from None
        if sha256(raw).hexdigest() != file.version:
            raise RagError("An original upload changed on disk. Restore it before rebuilding.")
        return raw

    def verify(self, file):
        self.download(file)

    def write_blob(self, data, version):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)
        path = self.blob_path(version)
        if path.exists():
            if sha256(path.read_bytes()).hexdigest() != version:
                raise RagError("An existing original failed its integrity check.")
            return
        descriptor, temporary = tempfile.mkstemp(dir=self.root, prefix=".upload-")
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


class UploadService:
    def __init__(self, store, models, settings):
        self.store, self.models, self.settings = store, models, settings

    def add(self, name, data, replace_existing=False):
        name = upload_name(name)
        if not data or len(data) > self.settings.max_file_bytes:
            raise RagError(f"Upload a nonempty file up to {self.settings.max_file_bytes:,} bytes.")
        version = sha256(data).hexdigest()
        with self.store.sync_lock() as locked:
            locked.assert_pipeline(self.settings)
            existing = next((row for row in locked.uploads() if row["name"].casefold() == name.casefold()), None)
            if existing and existing["version"] == version:
                return "unchanged"
            if existing and not replace_existing:
                raise RagError("A document with this name exists. Enable replacement to update it.")
            file = DriveFile(
                existing["id"] if existing else "local:" + str(uuid4()),
                existing["name"] if existing else name,
                version,
                MIME_TYPES[Path(name).suffix.lower()],
                "",
                len(data),
                "local",
            )
            job_id = str(uuid4())
            locked.log_activity(job_id, "upload", "indexing", "running", "Preparing document.", file.id, file.name)
            try:
                chunks = load_chunks(file, data, self.settings.chunk_size, self.settings.chunk_overlap)
                vectors = self.models.embed([chunk.text for chunk in chunks])
                LocalSource(locked, self.settings).write_blob(data, version)
                locked.publish_upload(file, chunks, vectors)
            except Exception as error:
                message = (
                    str(error)
                    if isinstance(error, RagError)
                    else "Upload could not be published. The previous version was kept."
                )
                try:
                    locked.log_activity(job_id, "upload", "complete", "error", message, file.id, file.name)
                except Exception:
                    LOGGER.error("Upload failure could not be recorded in activity.")
                raise RagError(message) from None
            # Publication succeeded. Activity cleanup cannot relabel it as a failure.
            try:
                locked.log_activity(
                    job_id, "upload", "complete", "success", f"{len(chunks)} passages indexed.", file.id, file.name
                )
            except Exception:
                LOGGER.warning("Upload published; activity recording needs attention.")
            return "updated" if existing else "added"

    def remove(self, file_id):
        with self.store.sync_lock() as locked:
            locked.remove_upload(file_id)

    def cleanup(self):
        """Explicit maintenance under the writer lock; retained generations keep their blobs."""
        with self.store.sync_lock() as locked:
            with locked.connect(vector=False) as conn:
                versions = {
                    row["version"]
                    for row in conn.execute(
                        "select version from python_rag.generation_documents where source_kind='local' union select version from python_rag.uploaded_documents"
                    )
                }
            source = LocalSource(locked, self.settings)
            removed = 0
            if source.root.exists():
                for path in source.root.iterdir():
                    if re.fullmatch("[a-f0-9]{64}", path.name) and path.name not in versions:
                        source.blob_path(path.name).unlink()
                        removed += 1
            return removed
