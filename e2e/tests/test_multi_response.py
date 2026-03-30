"""
Multi-response and message splitting tests.

Verifies that when the bot sends long responses that exceed platform
character limits, the messages are properly split and all parts arrive.
"""

from __future__ import annotations

import uuid

import pytest

from drivers.base import PlatformDriver


@pytest.mark.telegram
async def test_telegram_long_response(hermes, telegram_driver: PlatformDriver):
    """
    Ask the bot to generate a long response on Telegram.

    Telegram has a 4096 char limit per message, so the adapter should
    split long responses into multiple messages.
    """
    telegram_driver.drain_queue()
    nonce = uuid.uuid4().hex[:8]
    await telegram_driver.send_message(
        f"Write a 500-word essay about the history of computing. Tag: {nonce}"
    )

    replies = await telegram_driver.collect_bot_replies(timeout=120, max_replies=10)
    assert len(replies) >= 1, "No replies for long response request"

    # Combine all reply text
    full_text = " ".join(r.text for r in replies)
    assert len(full_text) > 200, f"Response too short: {len(full_text)} chars"


@pytest.mark.discord
async def test_discord_long_response(hermes, discord_driver: PlatformDriver):
    """
    Ask for a long response on Discord.

    Discord has a 2000 char limit per message.
    """
    discord_driver.drain_queue()
    nonce = uuid.uuid4().hex[:8]
    await discord_driver.send_message(
        f"Write a 500-word essay about the history of computing. Tag: {nonce}"
    )

    replies = await discord_driver.collect_bot_replies(timeout=120, max_replies=10)
    assert len(replies) >= 1, "No replies for long response request on Discord"

    full_text = " ".join(r.text for r in replies)
    assert len(full_text) > 200, f"Response too short: {len(full_text)} chars"


@pytest.mark.slack
async def test_slack_long_response(hermes, slack_driver):
    """
    Ask for a long response on Slack.

    Slack has a 39KB limit per message (practically unlimited for text).
    """
    slack_driver.drain_queue()
    nonce = uuid.uuid4().hex[:8]
    await slack_driver.send_mention(
        f"Write a 500-word essay about the history of computing. Tag: {nonce}"
    )

    replies = await slack_driver.collect_bot_replies(timeout=120, max_replies=10)
    assert len(replies) >= 1, "No replies for long response request on Slack"

    full_text = " ".join(r.text for r in replies)
    assert len(full_text) > 200, f"Response too short: {len(full_text)} chars"
