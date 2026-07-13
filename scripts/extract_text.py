"""Text extraction helpers for PDF, TXT and EPUB source documents."""
from pathlib import Path

import pdfplumber
from bs4 import BeautifulSoup
from ebooklib import epub, ITEM_DOCUMENT


def extract_txt(path: Path) -> str:
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    # Last resort: ignore undecodable bytes rather than crash.
    return path.read_text(encoding="utf-8", errors="ignore")


def extract_pdf(path: Path) -> str:
    chunks = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            chunks.append(text)
    return "\n".join(chunks)


def extract_epub(path: Path) -> str:
    book = epub.read_epub(str(path))
    chunks = []
    for item in book.get_items_of_type(ITEM_DOCUMENT):
        soup = BeautifulSoup(item.get_content(), "html.parser")
        chunks.append(soup.get_text(separator=" "))
    return "\n".join(chunks)


EXTRACTORS = {
    ".txt": extract_txt,
    ".pdf": extract_pdf,
    ".epub": extract_epub,
}


def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    extractor = EXTRACTORS.get(suffix)
    if extractor is None:
        raise ValueError(f"Unsupported file type: {suffix} ({path.name})")
    return extractor(path)
