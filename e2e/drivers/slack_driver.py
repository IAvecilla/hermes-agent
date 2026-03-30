"""
Slack test driver using a user OAuth token.

Sends messages as a real Slack user (not a bot) and polls the channel
history to detect replies from the Hermes bot.
No mocks. Real Slack Web API calls.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Optional

from slack_sdk.web.async_client import AsyncWebClient

from .base import DriverMessage, PlatformDriver

logger = logging.getLogger(__name__)


class SlackDriver(PlatformDriver):
    """
    A real Slack user that interacts with the Hermes bot.

    Required env vars:
        SLACK_TEST_USER_TOKEN  — xoxp-... user token with chat:write, channels:history
        SLACK_TEST_CHANNEL_ID  — channel where tests run
        SLACK_BOT_TOKEN        — Hermes bot token (to resolve its user ID)
    """

    def __init__(
        self,
        user_token: Optional[str] = None,
        channel_id: Optional[str] = None,
        hermes_bot_id: Optional[str] = None,
        poll_interval: float = 1.5,
    ):
        super().__init__("slack")
        self._user_token = user_token or os.environ["SLACK_TEST_USER_TOKEN"]
        self._channel_id = channel_id or os.environ["SLACK_TEST_CHANNEL_ID"]
        self._hermes_bot_id = hermes_bot_id
        self._poll_interval = poll_interval
        self._client: Optional[AsyncWebClient] = None
        self._poller_task: Optional[asyncio.Task] = None
        self._last_ts: Optional[str] = None  # timestamp of last seen message
        self._my_user_id: Optional[str] = None

    async def connect(self) -> None:
        """Connect to Slack and start polling for messages."""
        self._client = AsyncWebClient(token=self._user_token)

        # Verify auth and get our user ID
        auth = await self._client.auth_test()
        self._my_user_id = auth["user_id"]
        logger.info("[SlackDriver] Connected as user: %s (%s)", auth["user"], self._my_user_id)

        # Resolve Hermes bot user ID
        if not self._hermes_bot_id:
            bot_token = os.environ.get("SLACK_BOT_TOKEN", "")
            if bot_token:
                bot_client = AsyncWebClient(token=bot_token)
                bot_auth = await bot_client.auth_test()
                self._hermes_bot_id = bot_auth["user_id"]
                logger.info("[SlackDriver] Hermes bot ID: %s", self._hermes_bot_id)

        # Set the "last seen" timestamp to now so we only see new messages
        self._last_ts = str(time.time())

        # Start polling for new messages
        self._poller_task = asyncio.create_task(self._poll_messages())
        logger.info("[SlackDriver] Polling channel %s for bot replies", self._channel_id)

    async def disconnect(self) -> None:
        if self._poller_task and not self._poller_task.done():
            self._poller_task.cancel()
            try:
                await self._poller_task
            except asyncio.CancelledError:
                pass
        logger.info("[SlackDriver] Disconnected")

    async def send_message(self, text: str) -> None:
        assert self._client
        await self._client.chat_postMessage(channel=self._channel_id, text=text)
        logger.debug("[SlackDriver] Sent: %s", text[:80])

    async def send_image(self, file_path: str, caption: str = "") -> None:
        assert self._client
        await self._client.files_upload_v2(
            channel=self._channel_id,
            file=file_path,
            initial_comment=caption,
        )
        logger.debug("[SlackDriver] Sent image: %s", file_path)

    async def send_document(self, file_path: str, caption: str = "") -> None:
        assert self._client
        await self._client.files_upload_v2(
            channel=self._channel_id,
            file=file_path,
            initial_comment=caption,
        )
        logger.debug("[SlackDriver] Sent document: %s", file_path)

    async def send_mention(self, text: str) -> None:
        """Send a message that @mentions the Hermes bot."""
        assert self._client and self._hermes_bot_id
        await self._client.chat_postMessage(
            channel=self._channel_id,
            text=f"<@{self._hermes_bot_id}> {text}",
        )
        logger.debug("[SlackDriver] Sent mention: %s", text[:80])

    async def _poll_messages(self) -> None:
        """
        Poll conversations.history for new messages from the Hermes bot.

        Slack doesn't offer real-time events for user tokens without Socket Mode,
        so we poll at a regular interval.
        """
        assert self._client
        while True:
            try:
                result = await self._client.conversations_history(
                    channel=self._channel_id,
                    oldest=self._last_ts,
                    limit=20,
                )
                messages = result.get("messages", [])

                # Messages come newest-first, reverse for chronological order
                for msg in reversed(messages):
                    ts = msg.get("ts", "")
                    # Skip messages we've already seen
                    if self._last_ts and ts <= self._last_ts:
                        continue
                    self._last_ts = ts

                    # Skip our own messages
                    user_id = msg.get("user", "")
                    if user_id == self._my_user_id:
                        continue

                    is_hermes = (
                        self._hermes_bot_id is not None
                        and user_id == self._hermes_bot_id
                    ) or msg.get("bot_id") is not None

                    has_files = bool(msg.get("files"))
                    attachment_type = None
                    if has_files:
                        ftype = msg["files"][0].get("mimetype", "")
                        if ftype.startswith("image/"):
                            attachment_type = "image"
                        elif ftype.startswith("video/"):
                            attachment_type = "video"
                        elif ftype.startswith("audio/"):
                            attachment_type = "audio"
                        else:
                            attachment_type = "document"

                    driver_msg = DriverMessage(
                        text=msg.get("text", ""),
                        author_id=user_id,
                        author_is_bot=is_hermes,
                        timestamp=float(ts),
                        has_attachment=has_files,
                        attachment_type=attachment_type,
                        thread_id=msg.get("thread_ts"),
                        raw=msg,
                    )
                    await self._incoming.put(driver_msg)

            except Exception as e:
                logger.warning("[SlackDriver] Poll error: %s", e)

            await asyncio.sleep(self._poll_interval)
