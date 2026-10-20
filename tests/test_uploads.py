from hashlib import sha256
import pytest
from rag.config import Settings, RagError
from rag.types import DriveFile
from rag.uploads import LocalSource, upload_name
from rag.sources import CombinedSource


@pytest.mark.parametrize(
    "name", ["../secret.txt", "/tmp/a.txt", r"C:\a.txt", ".hidden.txt", "a\x00.txt", "test.exe", "a" * 201 + ".txt"]
)
def test_unsafe_upload_names_rejected(name):
    with pytest.raises(RagError):
        upload_name(name)


def test_original_integrity_and_safe_paths(tmp_path):
    settings = Settings(data_dir=str(tmp_path))
    source = LocalSource(None, settings)
    raw = b"A fictional local document"
    version = sha256(raw).hexdigest()
    file = DriveFile("local:one", "file.txt", version, "text/plain", "", len(raw), "local")
    source.write_blob(raw, version)
    assert source.download(file) == raw
    import os

    if os.name != "nt":
        assert source.blob_path(version).stat().st_mode & 0o777 == 0o600
    source.blob_path(version).write_bytes(b"changed")
    with pytest.raises(RagError, match="changed"):
        source.verify(file)
    with pytest.raises(RagError):
        source.blob_path("../outside")
    source.blob_path(version).unlink()
    with pytest.raises(RagError, match="missing"):
        source.verify(file)
    source.blob_path(version).symlink_to(tmp_path / "elsewhere")
    with pytest.raises(RagError, match="symbolic"):
        source.verify(file)


def test_combined_snapshot_never_returns_partial_results():
    class Adapter:
        def snapshot(self):
            return [DriveFile("a", "A", "1", "text/plain", "")], []

    class Broken:
        def snapshot(self):
            raise RagError("Incomplete snapshot")

    with pytest.raises(RagError, match="Incomplete"):
        CombinedSource(Adapter(), Broken()).snapshot()
    with pytest.raises(RagError, match="same document"):
        CombinedSource(Adapter(), Adapter()).snapshot()


def test_oversize_original_rejected(tmp_path):
    source = LocalSource(None, Settings(data_dir=str(tmp_path), max_file_bytes=1))
    source.write_blob(b"large", sha256(b"large").hexdigest())
    file = DriveFile("a", "a.txt", sha256(b"large").hexdigest(), "text/plain", "")
    with pytest.raises(RagError, match="MAX_FILE_BYTES"):
        source.download(file)


@pytest.mark.parametrize("raw", [b"", b"too big"])
def test_upload_boundary_rejects_before_any_storage_or_model_access(raw):
    from rag.uploads import UploadService

    with pytest.raises(RagError, match="nonempty"):
        UploadService(None, None, Settings(max_file_bytes=2)).add("file.txt", raw)
