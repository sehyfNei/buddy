import httpx
import logging

from .base import LLMProvider, LLMResponse

logger = logging.getLogger(__name__)


class OllamaProvider(LLMProvider):
    """Ollama local model provider (http://localhost:11434 by default)."""

    async def generate(self, prompt: str, context: str = "") -> LLMResponse:
        messages = []
        if context:
            messages.append({"role": "system", "content": context})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "num_predict": self.max_tokens,
            },
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(f"{self.endpoint}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()

        text = data.get("message", {}).get("content", "")
        tokens = data.get("eval_count", 0)
        return LLMResponse(text=text, model=self.model, tokens_used=tokens)

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.endpoint}/api/tags")
                return resp.status_code == 200
        except Exception:
            logger.warning("Ollama not reachable at %s", self.endpoint)
            return False
