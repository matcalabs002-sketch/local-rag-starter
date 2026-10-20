"""Portable setup, initialization, diagnostics, and explicit maintenance."""

import argparse
import os
import secrets
import sys
from urllib.parse import quote

from dotenv import dotenv_values
import httpx

from .config import ROOT, Settings, RagError
from .models import Models
from .store import Store


def setup():
    path = ROOT / ".env"
    if path.exists():
        raise RagError(".env already exists. Existing configuration was kept; edit it explicitly.")
    values = {key: value or "" for key, value in dotenv_values(ROOT / ".env.example").items()}
    password = secrets.token_urlsafe(24)
    values["POSTGRES_PASSWORD"] = password
    values["DATABASE_URL"] = f"postgresql://rag:{quote(password, safe='')}@127.0.0.1:55432/rag"
    # Exclusive creation prevents overwriting a concurrent setup.
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        for key, value in values.items():
            stream.write(f"{key}='{value}'\n")
    print("Created private .env with a generated local database password. Next: docker compose up -d --wait")


def checks(settings):
    failures = []
    for label, operation in (
        ("Configuration", settings.validate),
        ("Database schema", lambda: Store(settings).ready()),
        ("Active index", lambda: Store(settings).assert_pipeline(settings)),
        ("Selected models", lambda: Models(settings).health()),
    ):
        try:
            operation()
            print(f"OK    {label}")
        except RagError as error:
            print(f"ERROR {label}: {error}")
            failures.append(label)
        except Exception:
            print(f"ERROR {label}: check settings and service availability.")
            failures.append(label)
    return not failures


def main():
    parser = argparse.ArgumentParser(description="Local RAG Starter — local starter tools")
    parser.add_argument("command", choices=["setup", "init", "check", "sync", "cleanup"])
    args = parser.parse_args()
    try:
        if args.command == "setup":
            setup()
            return
        settings = Settings.load()
        if args.command == "check":
            raise SystemExit(0 if checks(settings) else 1)
        settings.validate()
        store = Store(settings)
        if args.command == "init":
            Models(settings)  # Validate model configuration without contacting a provider.
            store.initialize()
            print("Library schema initialized. Existing source data was preserved.")
        elif args.command == "sync":
            from .sync import SyncEngine
            from .websites import WebsiteSyncEngine

            models = Models(settings)
            models.health()
            if settings.folder_id:
                from .drive import Drive

                SyncEngine(store, Drive(settings.folder_id), models, settings.folder_id).run()
            with store.sync_lock() as locked:
                locked.assert_pipeline(settings)
                WebsiteSyncEngine(locked, models).run()
            print("Configured remote sources refreshed. Uploads remain unchanged.")
        else:
            from .uploads import UploadService

            removed = UploadService(store, None, settings).cleanup()
            print(f"Removed {removed} unreferenced original(s). Retained indexes were preserved.")
    except RagError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1) from None
    except (OSError, httpx.HTTPError):
        print("ERROR: A local file or service was unavailable. Check configuration and retry.", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
