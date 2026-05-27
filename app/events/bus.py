"""OTS Approval Helping Agent — Async event bus (asyncio.Queue).

Single-process event bus. All agents publish events here.
The Orchestrator subscribes to drive state transitions.
The notification consumer subscribes for IM/email dispatch.

Upgrade path: asyncio.Queue (MVP) → RabbitMQ (production).
"""

import asyncio
import logging
from typing import Awaitable, Callable

from app.events.types import Event

logger = logging.getLogger(__name__)

Handler = Callable[[Event], Awaitable[None]]


class EventBus:
    def __init__(self):
        self._queue: asyncio.Queue = asyncio.Queue()
        self._handlers: dict[str, list[Handler]] = {}
        self._running = False
        self._consumer_task = None

    async def start(self):
        self._running = True
        self._consumer_task = asyncio.create_task(self._consume())
        logger.info("EventBus started (asyncio.Queue)")

    async def stop(self):
        self._running = False
        logger.info("EventBus stopped")

    async def publish(self, event: Event):
        await self._queue.put(event)
        logger.debug(f"Event published: {event.type} task={event.task_id}")

    def subscribe(self, event_type: str, handler: Handler):
        self._handlers.setdefault(event_type, []).append(handler)

    async def _consume(self):
        while self._running:
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                handlers = self._handlers.get(event.type, [])
                for h in handlers:
                    try:
                        await h(event)
                    except Exception:
                        logger.exception(f"Handler failed for {event.type}")
            except asyncio.TimeoutError:
                pass


# Singleton
event_bus = EventBus()
