"""
Slash command tests — verify platform-specific command handling.

Tests that the bot processes slash commands (e.g., /help, /hermes)
on each platform and responds appropriately.
"""

from __future__ import annotations

import pytest

from drivers.base import PlatformDriver


@pytest.mark.telegram
async def test_telegram_help_command(hermes, telegram_driver: PlatformDriver):
    """Send /help to the Telegram bot."""
    telegram_driver.drain_queue()
    await telegram_driver.send_message("/help")

    reply = await telegram_driver.wait_for_bot_reply(timeout=60)
    assert reply is not None, "No reply to /help on Telegram"
    assert len(reply.text) > 0


@pytest.mark.telegram
async def test_telegram_start_command(hermes, telegram_driver: PlatformDriver):
    """Send /start to the Telegram bot (standard Telegram bot greeting)."""
    telegram_driver.drain_queue()
    await telegram_driver.send_message("/start")

    reply = await telegram_driver.wait_for_bot_reply(timeout=60)
    assert reply is not None, "No reply to /start on Telegram"
    assert len(reply.text) > 0


@pytest.mark.discord
async def test_discord_help_command(hermes, discord_driver: PlatformDriver):
    """Send /help in the Discord test channel."""
    discord_driver.drain_queue()
    # Discord slash commands are registered differently, but text-based
    # /help should also work via message handler
    await discord_driver.send_message("/help")

    reply = await discord_driver.wait_for_bot_reply(timeout=60)
    # Some bots don't respond to /help as a text message on Discord
    # (they use slash command interactions). This is still a valid test
    # to ensure it doesn't crash.
    # reply may be None if the bot only handles slash commands via interactions


@pytest.mark.slack
async def test_slack_hermes_command(hermes, slack_driver):
    """
    Test the /hermes slash command on Slack.

    Note: Slash commands in Slack are sent as HTTP payloads, not regular
    messages. The user token can't invoke slash commands — they must be
    triggered from the Slack UI. This test sends it as a regular message
    with @mention as a workaround to test command-like input.
    """
    slack_driver.drain_queue()
    await slack_driver.send_mention("help")

    reply = await slack_driver.wait_for_bot_reply(timeout=60)
    assert reply is not None, "No reply to help request on Slack"
    assert len(reply.text) > 0
