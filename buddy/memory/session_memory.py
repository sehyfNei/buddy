from dataclasses import dataclass, field


@dataclass
class ChatMessage:
    role: str    # "user" or "buddy"
    content: str


class SessionMemory:
    """In-memory conversation history for a single reading session (v1: not persistent)."""

    def __init__(self, max_messages: int = 50):
        self._messages: list[ChatMessage] = []
        self._max = max_messages

    def add(self, role: str, content: str) -> None:
        self._messages.append(ChatMessage(role=role, content=content))
        # Trim old messages if over limit (keep most recent)
        if len(self._messages) > self._max:
            self._messages = self._messages[-self._max:]

    def get_history(self) -> list[ChatMessage]:
        return list(self._messages)

    def get_context_string(self) -> str:
        """Format recent chat history as context for the LLM."""
        if not self._messages:
            return ""
        lines = []
        for msg in self._messages[-10:]:  # last 10 messages for context
            prefix = "Reader" if msg.role == "user" else "Buddy"
            lines.append(f"{prefix}: {msg.content}")
        return "\n".join(lines)

    def clear(self) -> None:
        self._messages.clear()
