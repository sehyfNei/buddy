from enum import Enum
from dataclasses import dataclass

from .state_detector import UserState


class ResponseMode(str, Enum):
    EXPLAIN = "explain"       # Break down, simplify, use analogies
    NUDGE = "nudge"           # Short encouragement, suggest break
    SILENT = "silent"         # Do nothing — user is in flow
    CHECK_IN = "check_in"    # Gentle "still there?" after idle


@dataclass
class RouterDecision:
    mode: ResponseMode
    should_intervene: bool
    reason: str


class ModeRouter:
    """Routes a detected user state to the appropriate response strategy."""

    def route(self, state: UserState) -> RouterDecision:
        if state == UserState.STUCK:
            return RouterDecision(
                mode=ResponseMode.EXPLAIN,
                should_intervene=True,
                reason="User appears to be struggling with this section.",
            )

        if state == UserState.TIRED:
            return RouterDecision(
                mode=ResponseMode.NUDGE,
                should_intervene=True,
                reason="User seems fatigued — long idle period detected.",
            )

        if state == UserState.IDLE:
            return RouterDecision(
                mode=ResponseMode.CHECK_IN,
                should_intervene=True,
                reason="User has been idle for a while.",
            )

        # FOCUSED — stay quiet
        return RouterDecision(
            mode=ResponseMode.SILENT,
            should_intervene=False,
            reason="User is reading steadily — no interruption needed.",
        )
