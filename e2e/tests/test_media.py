"""
Media handling tests — send images/documents and verify the bot processes them.

Tests that the bot can receive media files and acknowledges them
(either by responding about the content or at minimum not crashing).
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import pytest

from drivers.base import PlatformDriver

# Simple 1x1 red PNG (68 bytes)
_TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
    b"\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00"
    b"\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.fixture
def test_image(tmp_path) -> str:
    """Create a tiny test PNG file."""
    img_path = tmp_path / "test_image.png"
    img_path.write_bytes(_TINY_PNG)
    return str(img_path)


@pytest.fixture
def test_document(tmp_path) -> str:
    """Create a tiny test text file."""
    doc_path = tmp_path / "test_document.txt"
    doc_path.write_text("This is a test document for Hermes E2E testing.\n" * 5)
    return str(doc_path)


# ── Image tests ──────────────────────────────────────────────────────────────


@pytest.mark.telegram
async def test_telegram_image(hermes, telegram_driver: PlatformDriver, test_image: str):
    """Send an image to the Telegram bot and verify it responds."""
    telegram_driver.drain_queue()
    await telegram_driver.send_image(test_image, caption="What do you see in this image?")

    reply = await telegram_driver.wait_for_bot_reply(timeout=90)
    assert reply is not None, "No reply after sending image on Telegram"
    assert len(reply.text) > 0


@pytest.mark.discord
async def test_discord_image(hermes, discord_driver: PlatformDriver, test_image: str):
    """Send an image in the Discord test channel."""
    discord_driver.drain_queue()
    await discord_driver.send_image(test_image, caption="What do you see?")

    reply = await discord_driver.wait_for_bot_reply(timeout=90)
    assert reply is not None, "No reply after sending image on Discord"
    assert len(reply.text) > 0


@pytest.mark.slack
async def test_slack_image(hermes, slack_driver: PlatformDriver, test_image: str):
    """Send an image in the Slack test channel."""
    slack_driver.drain_queue()
    await slack_driver.send_image(test_image, caption="What do you see?")

    reply = await slack_driver.wait_for_bot_reply(timeout=90)
    assert reply is not None, "No reply after sending image on Slack"
    assert len(reply.text) > 0


# ── Document tests ───────────────────────────────────────────────────────────


@pytest.mark.telegram
async def test_telegram_document(hermes, telegram_driver: PlatformDriver, test_document: str):
    """Send a document to the Telegram bot."""
    telegram_driver.drain_queue()
    await telegram_driver.send_document(test_document, caption="Summarize this file")

    reply = await telegram_driver.wait_for_bot_reply(timeout=90)
    assert reply is not None, "No reply after sending document on Telegram"
    assert len(reply.text) > 0


@pytest.mark.discord
async def test_discord_document(hermes, discord_driver: PlatformDriver, test_document: str):
    """Send a document in the Discord test channel."""
    discord_driver.drain_queue()
    await discord_driver.send_document(test_document, caption="Summarize this file")

    reply = await discord_driver.wait_for_bot_reply(timeout=90)
    assert reply is not None, "No reply after sending document on Discord"
    assert len(reply.text) > 0


@pytest.mark.slack
async def test_slack_document(hermes, slack_driver: PlatformDriver, test_document: str):
    """Send a document in the Slack test channel."""
    slack_driver.drain_queue()
    await slack_driver.send_document(test_document, caption="Summarize this file")

    reply = await slack_driver.wait_for_bot_reply(timeout=90)
    assert reply is not None, "No reply after sending document on Slack"
    assert len(reply.text) > 0


# ── Cross-platform ───────────────────────────────────────────────────────────


@pytest.mark.all_platforms
async def test_image_across_platforms(hermes, drivers: dict, test_image: str):
    """Every configured platform should handle an image without crashing."""
    if not drivers:
        pytest.skip("No platform credentials configured")

    for name, driver in drivers.items():
        driver.drain_queue()
        await driver.send_image(test_image, caption="Describe this")
        reply = await driver.wait_for_bot_reply(timeout=90)
        assert reply is not None, f"[{name}] No reply after image"
