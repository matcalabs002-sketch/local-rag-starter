"""Bounded format extraction and a shared passage splitter."""

import csv
import io
from pathlib import Path
from tempfile import TemporaryDirectory
import zipfile

from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader
import docx2txt

from .config import CHUNK_SIZE, CHUNK_OVERLAP, MAX_TEXT_CHARS, MAX_CHUNKS, RagError
from .types import Chunk

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
TEXT_TYPES = {"text/plain", "text/markdown", "application/vnd.google-apps.document"}


def splitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP, separators=None):
    if not 200 <= chunk_size <= 4000:
        raise RagError("Chunk size must be between 200 and 4,000 characters.")
    if not 0 <= chunk_overlap < chunk_size:
        raise RagError("Chunk overlap must be smaller than the chunk size.")
    options = dict(chunk_size=chunk_size, chunk_overlap=chunk_overlap, add_start_index=True)
    if separators:
        options["separators"] = separators
    return RecursiveCharacterTextSplitter(**options)


def _extract(file, data):
    if file.mime_type == "application/pdf":
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise RagError("Encrypted PDFs are unsupported. Upload an unencrypted text PDF.")
        for number, page in enumerate(reader.pages, 1):
            yield page.extract_text() or "", {"page": number}
    elif file.mime_type == DOCX_MIME:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if sum(item.file_size for item in archive.infolist()) > MAX_TEXT_CHARS * 10:
                raise RagError("The expanded DOCX is too large. Split it into smaller documents.")
        with TemporaryDirectory(prefix="rag-extract-") as folder:
            path = Path(folder) / "document.docx"
            path.write_bytes(data)
            yield docx2txt.process(str(path)), {}
    elif file.mime_type == "text/csv":
        reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig")))
        for number, row in enumerate(reader):
            yield "\n".join(f"{key}: {value}" for key, value in row.items()), {"row": number}
    elif file.mime_type in TEXT_TYPES:
        yield data.decode("utf-8-sig"), {}
    else:
        raise RagError("Unsupported format. Use a text PDF, DOCX, TXT, Markdown, or CSV file.")


def load_chunks(file, data, chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP, separators=None):
    split = splitter(chunk_size, chunk_overlap, separators)
    result, total = [], 0
    try:
        for text, metadata in _extract(file, data):
            total += len(text)
            if total > MAX_TEXT_CHARS:
                raise RagError("This document has too much text. Split it into smaller documents.")
            for document in split.create_documents([text], [metadata]):
                if document.page_content.strip():
                    result.append(Chunk(document.page_content.strip(), document.metadata))
                if len(result) > MAX_CHUNKS:
                    raise RagError("This document produces too many passages. Split it into smaller documents.")
        if not result:
            raise RagError("No readable text was found. Scanned PDFs need OCR first; the previous version was kept.")
        return result
    except RagError:
        raise
    except Exception:
        raise RagError(
            "This document could not be read. Use an unencrypted PDF, DOCX, UTF-8 text, Markdown, or CSV file."
        ) from None


def split_text_chunks(text, chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP, separators=None):
    if len(text) > MAX_TEXT_CHARS:
        raise RagError("This page has too much text to import.")
    from .types import DriveFile

    return load_chunks(DriveFile("", "", "", "text/plain", ""), text.encode(), chunk_size, chunk_overlap, separators)


def preview_chunks(text, chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP, separators=None, limit=4):
    if not text.strip():
        return []
    return [
        chunk.text for chunk in split_text_chunks(text, chunk_size, chunk_overlap, separators)[: max(1, min(limit, 20))]
    ]
