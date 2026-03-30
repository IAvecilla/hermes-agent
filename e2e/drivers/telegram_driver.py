"""
Telegram test driver using Telethon.

Acts as a *real Telegram user* — logs in with phone number / session,
sends messages to the Hermes bot, and listens for replies.
No mocks. Real MTProto connection to Telegram servers.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

from telethon import TelegramClient, events
from telethon.sessions import StringSession

from .base import DriverMessage, PlatformDriver

logger = logging.getLogger(__name__)


class TelegramDriver(PlatformDriver):
    """
    Real Telegram user that interacts with the Hermes bot.

    Required env vars:
        TELEGRAM_API_ID       — from https://my.telegram.org
        TELEGRAM_API_HASH     — from https://my.telegram.org
        TELEGRAM_TEST_PHONE   — phone number of the test account
        TELEGRAM_TEST_SESSION — (optional) Telethon StringSession for skip auth
        TELEGRAM_BOT_TOKEN    — used to resolve the bot's username
    """

    def __init__(
        self,
        api_id: Optional[int] = None,
        api_hash: Optional[str] = None,
        phone: Optional[str] = None,
        session_string: Optional[str] = None,
        bot_username: Optional[str] = None,
    ):
        super().__init__("telegram")
        self._api_id = api_id or int(os.environ["TELEGRAM_API_ID"])
        self._api_hash = api_hash or os.environ["TELEGRAM_API_HASH"]
        self._phone = phone or os.environ.get("TELEGRAM_TEST_PHONE")
        self._session_string = session_string or os.environ.get("TELEGRAM_TEST_SESSION", "")
        self._bot_username = bot_username  # resolved during connect if not set
        self._client: Optional[TelegramClient] = None
        self._bot_entity = None
        self._bot_id: Optional[int] = None

    async def connect(self) -> None:
        """
        Connect to Telegram as a real user via Telethon.

        First run requires interactive phone auth (code sent via Telegram).
        Subsequent runs use the saved session string.
        """
        session = StringSession(self._session_string) if self._session_string else StringSession()
        self._client = TelegramClient(session, self._api_id, self._api_hash)

        await self._client.start(phone=self._phone)
        logger.info("[TelegramDriver] Connected as user: %s", await self._client.get_me())

        # Export session string for future runs (avoids re-auth)
        exported = self._client.session.save()
        if exported and exported != self._session_string:
            logger.info(
                "[TelegramDriver] Session string (save to TELEGRAM_TEST_SESSION):\n%s",
                exported,
            )

        # Resolve the Hermes bot
        if not self._bot_username:
            # Try to get bot username from the bot token
            bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
            if bot_token:
                # Use httpx to call getMe on the bot API
                import httpx
                async with httpx.AsyncClient() as http:
                    resp = await http.get(f"https://api.telegram.org/bot{bot_token}/getMe")
                    data = resp.json()
                    if data.get("ok"):
                        self._bot_username = data["result"]["username"]
                        logger.info("[TelegramDriver] Resolved bot: @%s", self._bot_username)

        if not self._bot_username:
            raise RuntimeError(
                "Cannot resolve Hermes bot username. "
                "Set TELEGRAM_BOT_TOKEN or pass bot_username explicitly."
            )

        self._bot_entity = await self._client.get_entity(self._bot_username)
        self._bot_id = self._bot_entity.id

        # Register handler for incoming messages from the bot
        @self._client.on(events.NewMessage(from_users=[self._bot_id]))
        async def on_bot_message(event):
            msg = event.message
            has_media = msg.media is not None
            attachment_type = None
            if has_media:
                media_type = type(msg.media).__name__.lower()
                if "photo" in media_type:
                    attachment_type = "image"
                elif "document" in media_type:
                    attachment_type = "document"
                elif "audio" in media_type:
                    attachment_type = "audio"
                elif "video" in media_type:
                    attachment_type = "video"

            driver_msg = DriverMessage(
                text=msg.text or "",
                author_id=str(msg.sender_id),
                author_is_bot=True,
                timestamp=msg.date.timestamp(),
                has_attachment=has_media,
                attachment_type=attachment_type,
                raw=msg,
            )
            await self._incoming.put(driver_msg)

        logger.info("[TelegramDriver] Listening for messages from @%s", self._bot_username)

    async def disconnect(self) -> None:
        if self._client:
            await self._client.disconnect()
            logger.info("[TelegramDriver] Disconnected")

    async def send_message(self, text: str) -> None:
        assert self._client and self._bot_entity
        await self._client.send_message(self._bot_entity, text)
        logger.debug("[TelegramDriver] Sent: %s", text[:80])

    async def send_image(self, file_path: str, caption: str = "") -> None:
        assert self._client and self._bot_entity
        await self._client.send_file(self._bot_entity, file_path, caption=caption)
        logger.debug("[TelegramDriver] Sent image: %s", file_path)

    async def send_document(self, file_path: str, caption: str = "") -> None:
        assert self._client and self._bot_entity
        await self._client.send_file(
            self._bot_entity, file_path, caption=caption, force_document=True
        )
        logger.debug("[TelegramDriver] Sent document: %s", file_path)

    @property
    def session_string(self) -> str:
        """Get the current session string (save it to skip auth next time)."""
        if self._client:
            return self._client.session.save()
        return ""
