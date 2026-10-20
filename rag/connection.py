"""User-safe connection diagnostics and local certificate storage."""

import ssl
from .config import PRIVATE, RagError, write_private

MAX_CERTIFICATE_BYTES = 128 * 1024


def connection_message(error):
    message = str(error).lower()
    if "certificate verify failed" in message or "root certificate" in message:
        return "Supabase was reached, but its security certificate could not be verified. In Supabase → Database → Settings → SSL configuration, download the certificate. Upload it below, then test the connection again."
    if "password authentication failed" in message or "authentication failed" in message:
        return "The database rejected the database password. Enter the database password from this project, then Save connection. Your Supabase account password and API keys will not work here."
    if "tenant or user not found" in message:
        return "Supabase could not match the host and user to your project. Copy both from the same project’s Connect → Session pooler panel."
    if "timeout" in message or "timed out" in message or "network is unreachable" in message:
        return "The database did not respond. Check your internet, resume the project if paused, and use Connect → Session pooler on port 5432."
    if "translate host name" in message or "name or service not known" in message:
        return "The database host could not be found. Copy only the Host field from Connect → Session pooler, without https:// or a path."
    return "Cannot connect to the database. Check the Session pooler details, database password, project status, and internet connection."


def save_certificate(data: bytes):
    if len(data) > MAX_CERTIFICATE_BYTES:
        raise RagError("The certificate file is too large. Upload the certificate downloaded from Supabase.")
    try:
        pem = data.decode("ascii")
        if "PRIVATE KEY" in pem or "-----BEGIN CERTIFICATE-----" not in pem:
            raise ValueError("Not a certificate")
        ssl.create_default_context(cadata=pem)
    except (UnicodeError, ValueError, ssl.SSLError):
        raise RagError(
            "This is not a valid PEM certificate. Upload the .crt, .cer, or .pem file from Supabase SSL configuration."
        ) from None
    path = PRIVATE / "supabase-ca.crt"
    write_private(path, pem)
    return str(path)
