"""Tests for the state detection heuristics."""

import pytest
from buddy.core.state_detector import StateDetector, ReadingSignals, UserState


@pytest.fixture
def detector():
    return StateDetector()


def make_signals(**kwargs) -> ReadingSignals:
    defaults = {
        "page_visits": {},
        "time_on_current_page_s": 10.0,
        "idle_time_s": 0.0,
        "pages_skipped": 0,
        "scroll_backs": 0,
        "selections_count": 0,
    }
    defaults.update(kwargs)
    return ReadingSignals(**defaults)


class TestStateDetector:
    def test_focused_when_normal_reading(self, detector):
        signals = make_signals(page_visits={1: 1, 2: 1, 3: 1})
        assert detector.detect(signals) == UserState.FOCUSED

    def test_stuck_on_reread(self, detector):
        # Page visited 3+ times = stuck
        signals = make_signals(page_visits={5: 3})
        assert detector.detect(signals) == UserState.STUCK

    def test_stuck_on_reread_plus_scroll_backs(self, detector):
        signals = make_signals(page_visits={5: 2}, scroll_backs=3)
        assert detector.detect(signals) == UserState.STUCK

    def test_stuck_on_long_page_with_scroll_backs(self, detector):
        signals = make_signals(
            time_on_current_page_s=150.0,
            scroll_backs=2,
            page_visits={3: 1},
        )
        assert detector.detect(signals) == UserState.STUCK

    def test_stuck_on_page_skipping(self, detector):
        signals = make_signals(pages_skipped=4)
        assert detector.detect(signals) == UserState.STUCK

    def test_tired_on_long_idle(self, detector):
        signals = make_signals(idle_time_s=100.0)
        assert detector.detect(signals) == UserState.TIRED

    def test_idle_on_medium_idle(self, detector):
        signals = make_signals(idle_time_s=45.0)
        assert detector.detect(signals) == UserState.IDLE

    def test_focused_on_short_idle(self, detector):
        signals = make_signals(idle_time_s=10.0, page_visits={1: 1})
        assert detector.detect(signals) == UserState.FOCUSED

    def test_empty_signals_are_focused(self, detector):
        signals = make_signals()
        assert detector.detect(signals) == UserState.FOCUSED

    def test_stuck_takes_priority_over_idle(self, detector):
        # Both stuck AND idle signals — stuck should win (checked first)
        signals = make_signals(page_visits={2: 3}, idle_time_s=50.0)
        assert detector.detect(signals) == UserState.STUCK
