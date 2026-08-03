"""Bounded WebSocket fan-out for current spectrum snapshots."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Callable


logger = logging.getLogger(__name__)


@dataclass
class _StreamClient:
    websocket: object
    queue: asyncio.Queue
    sender_task: asyncio.Task


class SpectrumStreamManager:
    """Fan out only the latest snapshot without blocking scan threads."""

    def __init__(self, snapshot_provider: Callable[[], dict | None]) -> None:
        self._snapshot_provider = snapshot_provider
        self._loop: asyncio.AbstractEventLoop | None = None
        self._clients: dict[int, _StreamClient] = {}
        self.enqueued_frames = 0
        self.replaced_frames = 0
        self.sent_frames = 0

    def bind_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def publish_threadsafe(self) -> bool:
        """Schedule snapshot publication from a controller or lifecycle thread."""
        loop = self._loop
        if loop is None or loop.is_closed():
            return False
        loop.call_soon_threadsafe(self.publish_current)
        return True

    async def register(self, websocket: object, initial_snapshot: dict | None = None) -> int:
        client_id = id(websocket)
        queue: asyncio.Queue = asyncio.Queue(maxsize=1)
        sender_task = asyncio.create_task(self._sender_loop(client_id, websocket, queue))
        self._clients[client_id] = _StreamClient(websocket, queue, sender_task)
        self._replace_latest(queue, initial_snapshot or self._snapshot_provider())
        return client_id

    async def remove(self, client_id: int) -> None:
        client = self._clients.pop(client_id, None)
        if client is None:
            return
        if client.sender_task is not asyncio.current_task():
            client.sender_task.cancel()
            await asyncio.gather(client.sender_task, return_exceptions=True)

    async def shutdown(self) -> None:
        clients = list(self._clients)
        for client_id in clients:
            await self.remove(client_id)

    def publish_current(self) -> None:
        """Run on the ASGI event loop after a committed state transition."""
        snapshot = self._snapshot_provider()
        if snapshot is None:
            return
        for client in tuple(self._clients.values()):
            self._replace_latest(client.queue, snapshot)

    def _replace_latest(self, queue: asyncio.Queue, snapshot: dict | None) -> None:
        if snapshot is None:
            return
        try:
            queue.put_nowait(snapshot)
            self.enqueued_frames += 1
            return
        except asyncio.QueueFull:
            pass

        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            return
        self.replaced_frames += 1
        queue.put_nowait(snapshot)
        self.enqueued_frames += 1

    async def _sender_loop(self, client_id: int, websocket: object, queue: asyncio.Queue) -> None:
        try:
            while True:
                snapshot = await queue.get()
                await websocket.send_json(snapshot)
                self.sent_frames += 1
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Spectrum WebSocket sender failed for client %s", client_id)
        finally:
            self._clients.pop(client_id, None)
