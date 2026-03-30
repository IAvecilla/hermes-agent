"""
Basic reply tests — send a message, verify the bot responds.

These are the fundamental smoke tests: if the bot can receive a message
and send a response on each platform, the integration is working.
"""

from __future__ import annotations

import uuid

import pytest

from drivers.base import PlatformDriver


# ── Per-platform tests ───────────────────────────────────────────────────────


@pytest.mark.telegram
async def test_telegram_basic_reply(hermes, telegram_driver: PlatformDriver):
    """Send a message to the Hermes Telegram bot and verify it responds."""
    telegram_driver.drain_queue()
    nonce = uuid.uuid4().hex[:8]
    await telegram_driver.send_message(f"e2e test ping {nonce}")

    reply = await telegram_driver.wait_for_bot_reply(timeout=60)
    assert reply is not None, "Hermes bot did not reply on Telegram within 60s"
    assert len(reply.text) > 0, "Bot reply was empty"
    assert reply.author_is_bot


@pytest.mark.discord
async def test_discord_basic_reply(hermes, discord_driver):
    """Send a message in the Discord test channel and verify hermes responds."""
    discord_driver.drain_queue()
    nonce = uuid.uuid4().hex[:8]

    # Discord hermes may require @mention depending on config.
    # The test fixture sets DISCORD_REQUIRE_MENTION=false and DISCORD_ALLOW_BOTS=all,
    # but we also have send_mention() as fallback.
    await discord_driver.send_message(f"e2e test ping {nonce}")

    reply = await discord_driver.wait_for_bot_reply(timeout=60)
    if reply is None:
        # Retry with @mention
        discord_driver.drain_queue()
        await discord_driver.send_mention(f"e2e test ping {nonce}")
        reply = await discord_driver.wait_for_bot_reply(timeout=60)

    assert reply is not None, "Hermes bot did not reply on Discord within 60s"
    assert len(reply.text) > 0, "Bot reply was empty"
    assert reply.author_is_bot


@pytest.mark.slack
async def test_slack_basic_reply(hermes, slack_driver):
    """Send a message in the Slack test channel and verify hermes responds."""
    slack_driver.drain_queue()
    nonce = uuid.uuid4().hex[:8]

    # In channels, Slack hermes requires @mention
    await slack_driver.send_mention(f"e2e test ping {nonce}")

    reply = await slack_driver.wait_for_bot_reply(timeout=60)
    assert reply is not None, "Hermes bot did not reply on Slack within 60s"
    assert len(reply.text) > 0, "Bot reply was empty"
    assert reply.author_is_bot


# ── Cross-platform parametrized tests ────────────────────────────────────────


@pytest.mark.all_platforms
async def test_bot_responds_with_content(hermes, drivers: dict):
    """On every configured platform, the bot should produce a non-trivial reply."""
    if not drivers:
        pytest.skip("No platform credentials configured")

    for platform_name, driver in drivers.items():
        driver.drain_queue()
        nonce = uuid.uuid4().hex[:8]

        if platform_name == "slack":
            await driver.send_mention(f"Say 'pong {nonce}' and nothing else")
        else:
            await driver.send_message(f"Say 'pong {nonce}' and nothing else")

        reply = await driver.wait_for_bot_reply(timeout=60)
        assert reply is not None, f"[{platform_name}] No reply within 60s"
        assert len(reply.text) > 0, f"[{platform_name}] Empty reply"


@pytest.mark.all_platforms
async def test_bot_handles_long_message(hermes, drivers: dict):
    """Send a longer message and verify the bot doesn't choke."""
    if not drivers:
        pytest.skip("No platform credentials configured")

    for platform_name, driver in drivers.items():
        driver.drain_queue()
        long_text = "This is a test message. " * 50  # ~1200 chars

        if platform_name == "slack":
            await driver.send_mention(long_text)
        else:
            await driver.send_message(long_text)

        reply = await driver.wait_for_bot_reply(timeout=90)
        assert reply is not None, f"[{platform_name}] No reply for long message"
