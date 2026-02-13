from enum import Enum
from dataclasses import dataclass, field
import time
import logging

logger = logging.getLogger(__name__)


class UserState(str, Enum):
    FOCUSED = "focused"
    STUCK = "stuck"
    TIRED = "tired"
    IDLE = "idle"


@dataclass
class ReadingSignals:
    """Aggregated reading behavior signals for a detection window."""
    page_visits: dict[int, int] = field(default_factory=dict)  # page -> visit count
    time_on_current_page_s: float = 0.0
    idle_time_s: float = 0.0
    pages_skipped: int = 0
    scroll_backs: int = 0
    selections_count: int = 0
    reading_speed_wpm: float = 0.0  # 0 means unknown
    timestamp: float = field(default_factory=time.time)


class StateDetector:
    """Rule-based heuristic detector for user reading state."""

    # Thresholds (tunable)
    REREAD_THRESHOLD = 2          # visits to same page before "stuck"
    IDLE_TIRED_S = 90.0           # seconds idle before "tired"
    IDLE_THRESHOLD_S = 30.0       # seconds idle before "idle"
    PAGE_SKIP_THRESHOLD = 3       # pages skipped in one burst
    LONG_PAGE_TIME_S = 120.0      # seconds on one page before concern
    SCROLL_BACK_THRESHOLD = 3     # scroll-backs on one page

    def detect(self, signals: ReadingSignals) -> UserState:
        """Classify the user's current state from reading signals."""

        # Check for re-reading (strongest stuck signal)
        max_visits = max(signals.page_visits.values()) if signals.page_visits else 0
        if max_visits >= self.REREAD_THRESHOLD and signals.scroll_backs >= self.SCROLL_BACK_THRESHOLD:
            logger.info("Detected STUCK: page visited %d times, %d scroll-backs", max_visits, signals.scroll_backs)
            return UserState.STUCK

        if max_visits >= self.REREAD_THRESHOLD + 1:
            logger.info("Detected STUCK: page visited %d times", max_visits)
            return UserState.STUCK

        # Long time on one page + scroll backs = stuck
        if signals.time_on_current_page_s > self.LONG_PAGE_TIME_S and signals.scroll_backs >= 2:
            logger.info("Detected STUCK: %.0fs on page with %d scroll-backs", signals.time_on_current_page_s, signals.scroll_backs)
            return UserState.STUCK

        # Extended idle = tired
        if signals.idle_time_s > self.IDLE_TIRED_S:
            logger.info("Detected TIRED: idle for %.0fs", signals.idle_time_s)
            return UserState.TIRED

        # Short idle
        if signals.idle_time_s > self.IDLE_THRESHOLD_S:
            logger.info("Detected IDLE: idle for %.0fs", signals.idle_time_s)
            return UserState.IDLE

        # Fast page skipping = could be lost (treat as stuck-adjacent)
        if signals.pages_skipped >= self.PAGE_SKIP_THRESHOLD:
            logger.info("Detected STUCK: skipped %d pages", signals.pages_skipped)
            return UserState.STUCK

        # Default: user is reading normally
        return UserState.FOCUSED
