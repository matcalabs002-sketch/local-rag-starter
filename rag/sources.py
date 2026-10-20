"""Minimal source contract used by rebuilds; no agent framework is needed."""

from typing import Protocol
from .config import RagError
from .types import DriveFile


class SourceAdapter(Protocol):
    def snapshot(self) -> tuple[list[DriveFile], list[dict]]: ...
    def download(self, file: DriveFile) -> bytes: ...
    def verify(self, file: DriveFile) -> None: ...


class CombinedSource:
    """A complete snapshot only exists when every configured adapter succeeds."""

    def __init__(self, *adapters: SourceAdapter):
        self.adapters = adapters
        self.owners = {}

    def snapshot(self):
        files, skipped, owners = [], [], {}
        for adapter in self.adapters:
            documents, ignored = adapter.snapshot()
            for file in documents:
                if file.id in owners:
                    raise RagError("Two source adapters returned the same document identity.")
                owners[file.id] = adapter
            files.extend(documents)
            skipped.extend(ignored)
        self.owners = owners
        return files, skipped

    def download(self, file):
        return self.owners[file.id].download(file)

    def verify(self, file):
        self.owners[file.id].verify(file)


def rebuild_sources(store, settings):
    from .uploads import LocalSource

    adapters = [LocalSource(store, settings)]
    if settings.folder_id:
        from .drive import Drive

        adapters.append(Drive(settings.folder_id))
    return CombinedSource(*adapters)
