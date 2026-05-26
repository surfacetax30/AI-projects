"""Agent base class — all functional agents inherit from this."""

from abc import ABC, abstractmethod
from typing import Any


class BaseAgent(ABC):
    """Minimal agent contract: every agent has a name and an async process method."""

    name: str

    @abstractmethod
    async def process(self, payload: dict) -> dict:
        """Process an event payload, return result dict.

        Result MUST include at least: {"status": "ok"|"error"|"pending_human", ...}
        """
        ...
