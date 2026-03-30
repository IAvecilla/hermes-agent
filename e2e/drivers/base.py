"""
Abstract base for platform test drivers.

Each driver acts as a *real user* (or second bot) on the platform,
sending messages to the Hermes bot and waiting for its replies.
No mocks — every call hits the real platform API.
"""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class DriverMessage:
    """A message observed by the test driver."""

    text: str
    author_id: str
    author_is_bot: bool = False
    timestamp: float = field(default_factory=time.time)
    has_attachment: bool = False
    attachment_type: Optional[str] = None  # "image", "document", "audio", "video"
    thread_id: Optional[str] = None
    raw: Optional[object] = None  # platform-specific raw message object


class PlatformDriver(ABC):
    """
    Interface that every platform test driver must implement.

    Lifecycle:
        driver = SomeDriver(config)
        await driver.connect()
        await driver.send_message("hello")
        reply = await driver.wait_for_bot_reply(timeout=30)
        assert reply is not None
        await driver.disconnect()
    """

    def __init__(self, platform_name: str):
        self.platform_name = platform_name
        self._incoming: asyncio.Queue[DriverMessage] = asyncio.Queue()

    # ── Connection ───────────────────────────────────────────────────

    @abstractmethod
    async def connect(self) -> None:
        """Connect to the platform as the test user/bot."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Clean up and disconnect."""

    # ── Sending ──────────────────────────────────────────────────────

    @abstractmethod
    async def send_message(self, text: str) -> None:
        """Send a text message in the test channel/chat."""

    @abstractmethod
    async def send_image(self, file_path: str, caption: str = "") -> None:
        """Send an image file in the test channel/chat."""

    @abstractmethod
    async def send_document(self, file_path: str, caption: str = "") -> None:
        """Send a document file in the test channel/chat."""

    # ── Receiving ────────────────────────────────────────────────────

    async def wait_for_bot_reply(self, timeout: float = 60) -> Optional[DriverMessage]:
        """
        Wait for the Hermes bot to send a reply.

        Drains the incoming queue looking for a message where author_is_bot=True.
        Returns None if no bot reply arrives within the timeout.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            try:
                msg = await asyncio.wait_for(self._incoming.get(), timeout=min(remaining, 2.0))
                if msg.author_is_bot:
                    return msg
            except asyncio.TimeoutError:
                continue
        return None

    async def collect_bot_replies(self, timeout: float = 30, max_replies: int = 10) -> List[DriverMessage]:
        """
        Collect multiple bot replies within a timeout window.

        Useful when the bot sends split messages or multiple responses.
        """
        replies: List[DriverMessage] = []
        deadline = time.time() + timeout
        while time.time() < deadline and len(replies) < max_replies:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            try:
                msg = await asyncio.wait_for(self._incoming.get(), timeout=min(remaining, 2.0))
                if msg.author_is_bot:
                    replies.append(msg)
            except asyncio.TimeoutError:
                # If we already have at least one reply and nothing new for 2s, stop
                if replies:
                    break
                continue
        return replies

    # ── Utilities ────────────────────────────────────────────────────

    def drain_queue(self) -> List[DriverMessage]:
        """Remove and return all messages currently in the queue."""
        drained = []
        while not self._incoming.empty():
            try:
                drained.append(self._incoming.get_nowait())
            except asyncio.QueueEmpty:
                break
        return drained
