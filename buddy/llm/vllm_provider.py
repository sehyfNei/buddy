import httpx
import logging

from .base import LLMProvider, LLMResponse

logger = logging.getLogger(__name__)


class VLLMProvider(LLMProvider):
    """vLLM server provider (OpenAI-compatible API on a custom endpoint)."""

    async def generate(self, prompt: str, context: str = "") -> LLMResponse:
        messages = []
        if context:
            messages.append({"role": "system", "content": context})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(f"{self.endpoint}/v1/chat/completions", json=payload)
            resp.raise_for_status()
            data = resp.json()

        choice = data["choices"][0]
        text = choice["message"]["content"]
        tokens = data.get("usage", {}).get("total_tokens", 0)
        return LLMResponse(text=text, model=self.model, tokens_used=tokens)

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.endpoint}/v1/models")
                return resp.status_code == 200
        except Exception:
            logger.warning("vLLM not reachable at %s", self.endpoint)
            return False
