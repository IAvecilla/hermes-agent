"""
Connectivity and health tests — verify adapters connect and stay connected.

These are the most basic tests: can we reach the platform APIs,
authenticate, and establish a connection?
Run these first to diagnose credential / network issues.
"""

from __future__ import annotations

import os

import pytest


@pytest.mark.telegram
async def test_telegram_bot_reachable():
    """Verify the Telegram bot token is valid by calling getMe."""
    import httpx

    token = os.environ["TELEGRAM_BOT_TOKEN"]
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"https://api.telegram.org/bot{token}/getMe")
        data = resp.json()
        assert data["ok"], f"Telegram getMe failed: {data}"
        assert data["result"]["is_bot"] is True
        print(f"  Bot: @{data['result']['username']} (ID: {data['result']['id']})")


@pytest.mark.telegram
async def test_telegram_test_user_connects():
    """Verify the Telethon test user can connect."""
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    api_id = int(os.environ["TELEGRAM_API_ID"])
    api_hash = os.environ["TELEGRAM_API_HASH"]
    session = os.environ.get("TELEGRAM_TEST_SESSION", "")
    phone = os.environ.get("TELEGRAM_TEST_PHONE")

    client = TelegramClient(StringSession(session), api_id, api_hash)
    try:
        await client.start(phone=phone)
        me = await client.get_me()
        assert me is not None
        print(f"  Test user: {me.first_name} (ID: {me.id})")
    finally:
        await client.disconnect()


@pytest.mark.discord
async def test_discord_bot_reachable():
    """Verify the Discord bot token is valid."""
    import httpx

    token = os.environ["DISCORD_BOT_TOKEN"]
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://discord.com/api/v10/users/@me",
            headers={"Authorization": f"Bot {token}"},
        )
        assert resp.status_code == 200, f"Discord auth failed: {resp.status_code}"
        data = resp.json()
        print(f"  Bot: {data['username']} (ID: {data['id']})")


@pytest.mark.discord
async def test_discord_test_bot_reachable():
    """Verify the test driver bot token is valid."""
    import httpx

    token = os.environ["DISCORD_TEST_BOT_TOKEN"]
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://discord.com/api/v10/users/@me",
            headers={"Authorization": f"Bot {token}"},
        )
        assert resp.status_code == 200, f"Test bot auth failed: {resp.status_code}"
        data = resp.json()
        print(f"  Test bot: {data['username']} (ID: {data['id']})")


@pytest.mark.discord
async def test_discord_test_channel_exists():
    """Verify the test channel exists and the bot can access it."""
    import httpx

    token = os.environ["DISCORD_TEST_BOT_TOKEN"]
    channel_id = os.environ["DISCORD_TEST_CHANNEL_ID"]
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://discord.com/api/v10/channels/{channel_id}",
            headers={"Authorization": f"Bot {token}"},
        )
        assert resp.status_code == 200, f"Cannot access test channel: {resp.status_code}"
        data = resp.json()
        print(f"  Channel: #{data.get('name', 'DM')} (ID: {channel_id})")


@pytest.mark.slack
async def test_slack_bot_reachable():
    """Verify the Slack bot token is valid."""
    from slack_sdk.web.async_client import AsyncWebClient

    client = AsyncWebClient(token=os.environ["SLACK_BOT_TOKEN"])
    resp = await client.auth_test()
    assert resp["ok"], f"Slack auth failed: {resp}"
    print(f"  Bot: @{resp['user']} (ID: {resp['user_id']})")


@pytest.mark.slack
async def test_slack_test_user_reachable():
    """Verify the Slack test user token is valid."""
    from slack_sdk.web.async_client import AsyncWebClient

    client = AsyncWebClient(token=os.environ["SLACK_TEST_USER_TOKEN"])
    resp = await client.auth_test()
    assert resp["ok"], f"Test user auth failed: {resp}"
    print(f"  Test user: @{resp['user']} (ID: {resp['user_id']})")


@pytest.mark.slack
async def test_slack_test_channel_exists():
    """Verify the test channel exists and the bot can access it."""
    from slack_sdk.web.async_client import AsyncWebClient

    client = AsyncWebClient(token=os.environ["SLACK_BOT_TOKEN"])
    channel_id = os.environ["SLACK_TEST_CHANNEL_ID"]
    resp = await client.conversations_info(channel=channel_id)
    assert resp["ok"], f"Cannot access test channel: {resp}"
    print(f"  Channel: #{resp['channel']['name']} (ID: {channel_id})")
