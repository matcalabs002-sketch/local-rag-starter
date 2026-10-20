from contextlib import contextmanager
from types import SimpleNamespace

from rag.runtime import Runtime


class FakeStore:
    @contextmanager
    def sync_lock(self):
        yield self


class FakeModels:
    def __init__(self, events):
        self.events = events

    def health(self):
        self.events.append("health")


def runtime_for(events):
    runtime = Runtime.__new__(Runtime)
    runtime.settings = SimpleNamespace(folder_id="folder")
    runtime.store = FakeStore()
    runtime.models = FakeModels(events)
    import threading

    runtime.stop_event = threading.Event()
    runtime.wake = threading.Event()
    runtime.thread = None
    runtime.request_lock = threading.Lock()
    runtime.requested_sites = set()
    runtime.error = None
    runtime.last_attempt = None
    return runtime


def test_targeted_website_request_skips_drive(monkeypatch):
    events = []
    runtime = runtime_for(events)

    class SiteSync:
        def __init__(self, store, models):
            pass

        def run(self, site_id=None):
            events.append(("site", site_id))
            runtime.stop_event.set()

    class DriveSync:
        def __init__(self, *args):
            events.append("drive-created")

        def run(self):
            events.append("drive")

    monkeypatch.setattr("rag.runtime.WebsiteSyncEngine", SiteSync)
    monkeypatch.setattr("rag.runtime.SyncEngine", DriveSync)
    monkeypatch.setattr("rag.runtime.SYNC_SECONDS", 0)
    runtime.request_site_sync("site-1")
    runtime._loop()
    assert events == ["health", ("site", "site-1")]


def test_periodic_sync_refreshes_drive_then_websites(monkeypatch):
    events = []
    runtime = runtime_for(events)

    class SiteSync:
        def __init__(self, store, models):
            pass

        def run(self, site_id=None):
            events.append(("site", site_id))
            runtime.stop_event.set()

    class DriveSync:
        def __init__(self, *args):
            pass

        def run(self):
            events.append("drive")

    monkeypatch.setattr("rag.runtime.WebsiteSyncEngine", SiteSync)
    monkeypatch.setattr("rag.runtime.SyncEngine", DriveSync)
    monkeypatch.setattr("rag.runtime.Drive", lambda folder_id: object())
    monkeypatch.setattr("rag.runtime.SYNC_SECONDS", 0)
    runtime._loop()
    assert events == ["health", "drive", ("site", None)]


def test_websites_work_without_drive(monkeypatch):
    events = []
    runtime = runtime_for(events)
    runtime.settings.folder_id = ""

    class Sites:
        def __init__(self, *args):
            pass

        def run(self):
            events.append("website-only")
            runtime.stop_event.set()

    monkeypatch.setattr("rag.runtime.WebsiteSyncEngine", Sites)
    monkeypatch.setattr("rag.runtime.SYNC_SECONDS", 0)
    runtime._loop()
    assert events == ["health", "website-only"]


def test_drive_error_does_not_block_websites(monkeypatch):
    from rag.config import RagError

    events = []
    runtime = runtime_for(events)

    class Sites:
        def __init__(self, *args):
            pass

        def run(self):
            events.append("website")
            runtime.stop_event.set()

    class BrokenDrive:
        def __init__(self, *args):
            raise RagError("Google needs sign-in")

    monkeypatch.setattr("rag.runtime.WebsiteSyncEngine", Sites)
    monkeypatch.setattr("rag.runtime.Drive", BrokenDrive)
    monkeypatch.setattr("rag.runtime.SYNC_SECONDS", 0)
    runtime._loop()
    assert events == ["health", "website"]
    assert runtime.error == "Google needs sign-in"
