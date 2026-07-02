"""Parse documents into plain text.  Supported: PDF, DOCX, TXT, Markdown."""

from pathlib import Path

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".markdown"}


def parse_file(file_path: str) -> tuple[str, dict]:
    """Parse a document file into plain text.

    Returns
    -------
    (text, metadata)  where metadata includes *file_name*, *file_type*, *file_size*.
    """
    path = Path(file_path)
    ext = path.suffix.lower()

    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {ext}")

    file_name = path.name
    file_size = path.stat().st_size

    if ext == ".pdf":
        text = _parse_pdf(file_path)
    elif ext == ".docx":
        text = _parse_docx(file_path)
    else:
        text = _parse_text(file_path)

    metadata = {
        "file_name": file_name,
        "file_type": ext.lstrip("."),
        "file_size": file_size,
    }
    return text, metadata


# ── PDF ──────────────────────────────────────────────────────────────────────

def _parse_pdf(path: str) -> str:
    import fitz  # pymupdf

    doc = fitz.open(path)
    pages: list[str] = []
    for page in doc:
        page_text = page.get_text("text")
        if page_text:
            pages.append(page_text)
    doc.close()
    return "\n\n".join(pages)


# ── DOCX ─────────────────────────────────────────────────────────────────────

def _parse_docx(path: str) -> str:
    from docx import Document  # python-docx

    doc = Document(path)
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n".join(paragraphs)


# ── Plain text / Markdown ────────────────────────────────────────────────────

def _parse_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except UnicodeDecodeError:
        with open(path, "r", encoding="latin-1") as fh:
            return fh.read()
