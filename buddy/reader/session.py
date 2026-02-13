import time
from dataclasses import dataclass, field

from .pdf_handler import PDFDocument


@dataclass
class Highlight:
    page: int
    text: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class ReadingSession:
    """Tracks the state of a single reading session."""
    session_id: str
    document: PDFDocument | None = None
    current_page: int = 1
    started_at: float = field(default_factory=time.time)
    highlights: list[Highlight] = field(default_factory=list)

    @property
    def has_document(self) -> bool:
        return self.document is not None

    @property
    def total_pages(self) -> int:
        return self.document.total_pages if self.document else 0

    def get_current_text(self) -> str:
        if not self.document:
            return ""
        return self.document.get_page_text(self.current_page)

    def get_context_text(self, window: int = 1) -> str:
        if not self.document:
            return ""
        return self.document.get_surrounding_text(self.current_page, window)

    def add_highlight(self, page: int, text: str) -> None:
        self.highlights.append(Highlight(page=page, text=text))
