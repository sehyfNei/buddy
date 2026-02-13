import fitz  # PyMuPDF
import logging
from pathlib import Path
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class PageContent:
    page_num: int
    text: str
    word_count: int


@dataclass
class PDFDocument:
    filename: str
    total_pages: int
    pages: list[PageContent]

    def get_page_text(self, page_num: int) -> str:
        """Get text for a specific page (1-indexed)."""
        idx = page_num - 1
        if 0 <= idx < len(self.pages):
            return self.pages[idx].text
        return ""

    def get_surrounding_text(self, page_num: int, window: int = 1) -> str:
        """Get text from current page and surrounding pages for context."""
        start = max(0, page_num - 1 - window)
        end = min(len(self.pages), page_num + window)
        return "\n\n".join(p.text for p in self.pages[start:end])


class PDFHandler:
    """Extracts text and metadata from PDF files using PyMuPDF."""

    def extract(self, pdf_path: str | Path) -> PDFDocument:
        pdf_path = Path(pdf_path)
        doc = fitz.open(str(pdf_path))
        pages = []
        for i, page in enumerate(doc):
            text = page.get_text("text").strip()
            pages.append(PageContent(
                page_num=i + 1,
                text=text,
                word_count=len(text.split()),
            ))
        result = PDFDocument(
            filename=pdf_path.name,
            total_pages=len(pages),
            pages=pages,
        )
        doc.close()
        logger.info("Extracted %d pages from %s", result.total_pages, result.filename)
        return result

    def extract_from_bytes(self, data: bytes, filename: str = "upload.pdf") -> PDFDocument:
        doc = fitz.open(stream=data, filetype="pdf")
        pages = []
        for i, page in enumerate(doc):
            text = page.get_text("text").strip()
            pages.append(PageContent(
                page_num=i + 1,
                text=text,
                word_count=len(text.split()),
            ))
        result = PDFDocument(
            filename=filename,
            total_pages=len(pages),
            pages=pages,
        )
        doc.close()
        logger.info("Extracted %d pages from uploaded %s", result.total_pages, filename)
        return result
