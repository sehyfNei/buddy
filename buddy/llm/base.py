from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class LLMResponse:
    text: str
    model: str
    tokens_used: int = 0


class LLMProvider(ABC):
    """Abstract interface for language model providers."""

    def __init__(self, model: str, endpoint: str, temperature: float = 0.7, max_tokens: int = 512):
        self.model = model
        self.endpoint = endpoint.rstrip("/")
        self.temperature = temperature
        self.max_tokens = max_tokens

    @abstractmethod
    async def generate(self, prompt: str, context: str = "") -> LLMResponse:
        """Generate a response given a prompt and optional document context."""
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the provider is reachable."""
        ...
