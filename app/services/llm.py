"""OTS Approval Helping Agent — DeepSeek LLM client."""

import httpx
import logging

from app.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL

logger = logging.getLogger(__name__)


class LLMClient:
    def __init__(self):
        self._client = httpx.AsyncClient(
            base_url=DEEPSEEK_BASE_URL,
            headers={
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json",
            },
            timeout=60.0,
        )
        self.model = DEEPSEEK_MODEL

    async def chat(self, system_prompt: str, user_message: str, temperature: float = 0.1) -> str:
        """Send a chat completion request, return text content."""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]
        resp = await self._client.post(
            "/chat/completions",
            json={
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    async def health_check(self) -> bool:
        """Verify API connectivity."""
        try:
            resp = await self._client.get("/models")
            resp.raise_for_status()
            models = resp.json().get("data", [])
            logger.info(f"DeepSeek connected. Available models: {len(models)}")
            return True
        except Exception:
            logger.exception("DeepSeek health check failed")
            return False

    async def close(self):
        await self._client.aclose()


# Singleton
llm = LLMClient()
