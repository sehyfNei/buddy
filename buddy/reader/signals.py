import time
import logging
from dataclasses import dataclass, field

from ..core.state_detector import ReadingSignals

logger = logging.getLogger(__name__)


@dataclass
class SignalEvent:
    event_type: str   # "page_view", "scroll_back", "selection", "idle", "page_skip"
    page: int = 0
    timestamp: float = field(default_factory=time.time)
    data: dict = field(default_factory=dict)


class SignalCollector:
    """Collects raw reading events and aggregates them into ReadingSignals."""

    def __init__(self):
        self._events: list[SignalEvent] = []
        self._page_visits: dict[int, int] = {}
        self._current_page: int = 1
        self._page_enter_time: float = time.time()
        self._last_activity_time: float = time.time()

    def record(self, event: SignalEvent) -> None:
        self._events.append(event)
        self._last_activity_time = event.timestamp

        if event.event_type == "page_view":
            page = event.page
            self._page_visits[page] = self._page_visits.get(page, 0) + 1
            self._current_page = page
            self._page_enter_time = event.timestamp
            logger.debug("Page %d viewed (visit #%d)", page, self._page_visits[page])

        elif event.event_type == "scroll_back":
            logger.debug("Scroll back on page %d", event.page)

        elif event.event_type == "selection":
            logger.debug("Text selected on page %d", event.page)

    def aggregate(self) -> ReadingSignals:
        """Build a ReadingSignals snapshot from collected events."""
        now = time.time()

        scroll_backs = sum(1 for e in self._events if e.event_type == "scroll_back")
        selections = sum(1 for e in self._events if e.event_type == "selection")
        page_skips = sum(1 for e in self._events if e.event_type == "page_skip")
        idle_time = now - self._last_activity_time
        time_on_page = now - self._page_enter_time

        return ReadingSignals(
            page_visits=dict(self._page_visits),
            time_on_current_page_s=time_on_page,
            idle_time_s=idle_time,
            pages_skipped=page_skips,
            scroll_backs=scroll_backs,
            selections_count=selections,
            timestamp=now,
        )

    def reset(self) -> None:
        """Clear events after processing (keep page visits for session continuity)."""
        self._events.clear()
