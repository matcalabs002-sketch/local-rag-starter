import ssl
from pathlib import Path
import certifi
import psycopg
import pytest
from rag.connection import connection_message, save_certificate
from rag.config import RagError, Settings


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("SSL error: certificate verify failed", "security certificate"),
        ("password authentication failed for secret=DO_NOT_SHOW", "database password"),
        ("Tenant or user not found", "host and user"),
        ("connection timeout expired", "did not respond"),
        ("could not translate host name secret", "host could not be found"),
        ("unknown error with secret=DO_NOT_SHOW", "Cannot connect"),
    ],
)
def test_safe_actionable_diagnostics(raw, expected):
    result = connection_message(psycopg.OperationalError(raw))
    assert expected in result and "DO_NOT_SHOW" not in result


def test_certificate_validation_and_private_save(tmp_path, monkeypatch):
    import rag.connection as module

    monkeypatch.setattr(module, "PRIVATE", tmp_path)
    # Standard public CA data supplies a valid fixture; no network or credentials.
    bundle = Path(certifi.where()).read_text()
    pem = (
        "-----BEGIN CERTIFICATE-----"
        + bundle.split("-----BEGIN CERTIFICATE-----")[1].split("-----END CERTIFICATE-----")[0]
        + "-----END CERTIFICATE-----\n"
    ).encode()
    path = Path(save_certificate(pem))
    assert path.read_bytes() == pem
    import os

    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600
    ssl.create_default_context(cafile=str(path))


@pytest.mark.parametrize("data", [b"not a certificate", b"-----BEGIN PRIVATE KEY-----", b"x" * 131073])
def test_invalid_certificate_does_not_overwrite(data, tmp_path, monkeypatch):
    import rag.connection as module

    monkeypatch.setattr(module, "PRIVATE", tmp_path)
    target = tmp_path / "supabase-ca.crt"
    target.write_text("existing")
    with pytest.raises(RagError):
        save_certificate(data)
    assert target.read_text() == "existing"


def test_transaction_pooler_rejected():
    with pytest.raises(RagError, match="Session pooler port 5432"):
        Settings(
            "postgresql://postgres.example:secret@aws-0-example.pooler.supabase.com:6543/postgres",
            "folder",
            "https://example.supabase.co",
        ).validate()
