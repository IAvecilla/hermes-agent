"""
Discord test driver using a second bot.

A dedicated test bot joins the same guild as the Hermes bot, sends messages
in a test channel, and listens for the Hermes bot's replies.
No mocks. Real WebSocket connection to Discord.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Optional

import discord
from discord import Intents, Message

from .base import DriverMessage, PlatformDriver

logger = logging.getLogger(__name__)


class DiscordDriver(PlatformDriver):
    """
    A second Discord bot that acts as the test user.

    Required env vars:
        DISCORD_TEST_BOT_TOKEN  — Token for the *test driver* bot (NOT Hermes)
        DISCORD_TEST_CHANNEL_ID — Channel where tests are run
        DISCORD_BOT_TOKEN       — Hermes bot token (to resolve its user ID)
    """

    def __init__(
        self,
        test_bot_token: Optional[str] = None,
        channel_id: Optional[int] = None,
        hermes_bot_id: Optional[int] = None,
    ):
        super().__init__("discord")
        self._token = test_bot_token or os.environ["DISCORD_TEST_BOT_TOKEN"]
        self._channel_id = channel_id or int(os.environ["DISCORD_TEST_CHANNEL_ID"])
        self._hermes_bot_id = hermes_bot_id  # resolved during connect if not set
        self._client: Optional[discord.Client] = None
        self._channel: Optional[discord.TextChannel] = None
        self._ready_event = asyncio.Event()
        self._task: Optional[asyncio.Task] = None

    async def connect(self) -> None:
        """Connect the test driver bot to Discord."""
        intents = Intents.default()
        intents.message_content = True
        intents.guild_messages = True

        self._client = discord.Client(intents=intents)
        driver = self  # capture for closures

        @self._client.event
        async def on_ready():
            logger.info("[DiscordDriver] Connected as %s", self._client.user)
            # Resolve test channel
            driver._channel = self._client.get_channel(driver._channel_id)
            if not driver._channel:
                driver._channel = await self._client.fetch_channel(driver._channel_id)
            logger.info("[DiscordDriver] Test channel: #%s", driver._channel.name)

            # Resolve Hermes bot ID if not provided
            if not driver._hermes_bot_id:
                hermes_token = os.environ.get("DISCORD_BOT_TOKEN", "")
                if hermes_token:
                    import httpx
                    async with httpx.AsyncClient() as http:
                        resp = await http.get(
                            "https://discord.com/api/v10/users/@me",
                            headers={"Authorization": f"Bot {hermes_token}"},
                        )
                        if resp.status_code == 200:
                            driver._hermes_bot_id = int(resp.json()["id"])
                            logger.info("[DiscordDriver] Hermes bot ID: %s", driver._hermes_bot_id)

            driver._ready_event.set()

        @self._client.event
        async def on_message(message: Message):
            # Only capture messages in our test channel
            if message.channel.id != driver._channel_id:
                return
            # Skip our own messages
            if message.author == self._client.user:
                return

            is_hermes = (
                driver._hermes_bot_id is not None
                and message.author.id == driver._hermes_bot_id
            ) or message.author.bot

            has_attachment = len(message.attachments) > 0
            attachment_type = None
            if has_attachment:
                ct = message.attachments[0].content_type or ""
                if ct.startswith("image/"):
                    attachment_type = "image"
                elif ct.startswith("video/"):
                    attachment_type = "video"
                elif ct.startswith("audio/"):
                    attachment_type = "audio"
                else:
                    attachment_type = "document"

            driver_msg = DriverMessage(
                text=message.content,
                author_id=str(message.author.id),
                author_is_bot=is_hermes,
                timestamp=message.created_at.timestamp(),
                has_attachment=has_attachment,
                attachment_type=attachment_type,
                thread_id=str(message.thread.id) if hasattr(message, "thread") and message.thread else None,
                raw=message,
            )
            await driver._incoming.put(driver_msg)

        # Start in background
        self._task = asyncio.create_task(self._client.start(self._token))

        # Wait for ready
        try:
            await asyncio.wait_for(self._ready_event.wait(), timeout=30)
        except asyncio.TimeoutError:
            await self.disconnect()
            raise RuntimeError("Discord test driver bot failed to connect within 30s")

    async def disconnect(self) -> None:
        if self._client and not self._client.is_closed():
            await self._client.close()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        logger.info("[DiscordDriver] Disconnected")

    async def send_message(self, text: str) -> None:
        assert self._channel
        await self._channel.send(text)
        logger.debug("[DiscordDriver] Sent: %s", text[:80])

    async def send_image(self, file_path: str, caption: str = "") -> None:
        assert self._channel
        await self._channel.send(content=caption, file=discord.File(file_path))
        logger.debug("[DiscordDriver] Sent image: %s", file_path)

    async def send_document(self, file_path: str, caption: str = "") -> None:
        assert self._channel
        await self._channel.send(content=caption, file=discord.File(file_path))
        logger.debug("[DiscordDriver] Sent document: %s", file_path)

    async def send_mention(self, text: str) -> None:
        """Send a message that @mentions the Hermes bot."""
        assert self._channel and self._hermes_bot_id
        await self._channel.send(f"<@{self._hermes_bot_id}> {text}")
        logger.debug("[DiscordDriver] Sent mention: %s", text[:80])
