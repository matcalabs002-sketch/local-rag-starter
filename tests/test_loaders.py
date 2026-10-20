import io, zipfile
import pytest
from rag.types import DriveFile
from rag.loaders import load_chunks
from rag.config import RagError, CHUNK_SIZE


def file(mime):
    return DriveFile("a", "A", "1", mime, "https://drive.google.com/file/d/a/view")


def test_text_markdown_csv_and_google_doc():
    for mime in ["text/plain", "text/markdown", "application/vnd.google-apps.document"]:
        chunks = load_chunks(file(mime), b"Hello world. " * 200)
        assert len(chunks) > 1 and max(len(c.text) for c in chunks) <= CHUNK_SIZE
    assert "Orchid" in load_chunks(file("text/csv"), b"name,code\nOrchid,742\n")[0].text


def test_docx():
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as z:
        z.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Welcome to Orchid.</w:t></w:r></w:p></w:body></w:document>',
        )
    assert (
        "Orchid"
        in load_chunks(
            file("application/vnd.openxmlformats-officedocument.wordprocessingml.document"), output.getvalue()
        )[0].text
    )


def test_pdf_page_metadata():
    stream = b"BT /F1 12 Tf 72 700 Td (Welcome to Orchid.) Tj ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    pdf = b"%PDF-1.4\n"
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(pdf))
        pdf += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    start = len(pdf)
    pdf += b"xref\n0 6\n0000000000 65535 f \n"
    for off in offsets[1:]:
        pdf += f"{off:010d} 00000 n \n".encode()
    pdf += b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n" + str(start).encode() + b"\n%%EOF"
    chunks = load_chunks(file("application/pdf"), pdf)
    assert "Orchid" in chunks[0].text and chunks[0].metadata["page"] == 1


@pytest.mark.parametrize("content", [b"", b"   ", b"\xff\xfe"])
def test_empty_and_unreadable_text(content):
    with pytest.raises(RagError):
        load_chunks(file("text/plain"), content)
