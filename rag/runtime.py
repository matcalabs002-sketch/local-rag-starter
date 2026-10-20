import threading
from datetime import datetime, timezone
from .config import SYNC_SECONDS, RagError
from .drive import Drive
from .store import Store
from .models import Models
from .sync import SyncEngine
from .websites import WebsiteSyncEngine


class Runtime:
    def __init__(self, settings):
        self.settings = settings
        self.store = Store(settings)
        self.models = Models(settings)
        self.stop_event = threading.Event()
        self.wake = threading.Event()
        self.thread = None
        self.request_lock = threading.Lock()
        self.requested_sites = set()
        self.error = None
        self.last_attempt = None

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self._loop, name="document-sync", daemon=True)
        self.thread.start()

    def request_sync(self):
        self.wake.set()

    def request_site_sync(self, site_id):
        with self.request_lock:
            self.requested_sites.add(str(site_id))
        self.wake.set()

    def stop(self):
        self.stop_event.set()
        self.wake.set()

    def _loop(self):
        while not self.stop_event.is_set():
            self.wake.clear()
            self.last_attempt = datetime.now(timezone.utc)
            try:
                self.models.health()
                with self.request_lock:
                    requested = set(self.requested_sites)
                    self.requested_sites.clear()
                if requested:
                    for site_id in requested:
                        with self.store.sync_lock() as locked:
                            WebsiteSyncEngine(locked, self.models).run(site_id)
                else:
                    drive_error = None
                    if self.settings.folder_id:
                        try:
                            SyncEngine(
                                self.store, Drive(self.settings.folder_id), self.models, self.settings.folder_id
                            ).run()
                        except RagError as error:
                            drive_error = error
                    with self.store.sync_lock() as locked:
                        WebsiteSyncEngine(locked, self.models).run()
                    if drive_error:
                        raise drive_error
                self.error = None
            except RagError as error:
                self.error = str(error)
            except Exception:
                self.error = "Sync could not run. Check your connection settings and try again."
            self.wake.wait(getattr(self.settings, "sync_seconds", SYNC_SECONDS))
