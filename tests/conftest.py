"""All destructive checks require a distinctly named, disposable loopback database."""

import os
from urllib.parse import urlparse
import pytest


def pytest_configure(config):
    url = os.getenv("TEST_DATABASE_URL")
    if url:
        parsed = urlparse(url)
        if parsed.hostname not in {"localhost", "127.0.0.1", "::1"} or not parsed.path.removeprefix("/").endswith(
            "_test"
        ):
            raise pytest.UsageError(
                "TEST_DATABASE_URL must target a disposable loopback database whose name ends in _test."
            )
