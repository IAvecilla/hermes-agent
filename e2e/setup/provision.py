#!/usr/bin/env python3
"""
Provisioning script for Hermes E2E tests.

Creates test channels/guilds/groups on each platform and outputs
the .env values needed to run the test suite.

Usage:
    python -m setup.provision [--telegram] [--discord] [--slack] [--all]

Prerequisites:
    - Bot tokens already created (see README.md for instructions)
    - Environment variables set in .env or exported
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys

from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Load .env from the e2e directory
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))


async def provision_discord() -> dict:
    """
    Create a test guild and channel for Discord e2e tests.

    Uses the Hermes bot token to create a guild (bots in <10 guilds can
    create guilds via the API) and a dedicated test channel.
    """
    import httpx

    bot_token = os.environ.get("DISCORD_BOT_TOKEN")
    test_bot_token = os.environ.get("DISCORD_TEST_BOT_TOKEN")
    if not bot_token:
        logger.error("DISCORD_BOT_TOKEN not set")
        return {}

    headers = {"Authorization": f"Bot {bot_token}", "Content-Type": "application/json"}
    result = {}

    async with httpx.AsyncClient(base_url="https://discord.com/api/v10") as http:
        # Create a test guild
        logger.info("[Discord] Creating test guild...")
        resp = await http.post("/guilds", headers=headers, json={"name": "Hermes E2E Tests"})
        if resp.status_code != 201:
            logger.error("[Discord] Failed to create guild: %s %s", resp.status_code, resp.text)
            return {}

        guild = resp.json()
        guild_id = guild["id"]
        result["DISCORD_TEST_GUILD_ID"] = guild_id
        logger.info("[Discord] Created guild: %s (ID: %s)", guild["name"], guild_id)

        # Find the default text channel or create one
        resp = await http.get(f"/guilds/{guild_id}/channels", headers=headers)
        channels = resp.json()
        text_channel = next((c for c in channels if c["type"] == 0), None)

        if text_channel:
            channel_id = text_channel["id"]
        else:
            resp = await http.post(
                f"/guilds/{guild_id}/channels",
                headers=headers,
                json={"name": "e2e-tests", "type": 0},
            )
            channel = resp.json()
            channel_id = channel["id"]

        result["DISCORD_TEST_CHANNEL_ID"] = channel_id
        logger.info("[Discord] Test channel ID: %s", channel_id)

        # Invite the test driver bot to the guild
        if test_bot_token:
            # Get test bot's application ID
            test_headers = {
                "Authorization": f"Bot {test_bot_token}",
                "Content-Type": "application/json",
            }
            resp = await http.get("/users/@me", headers=test_headers)
            if resp.status_code == 200:
                test_bot_id = resp.json()["id"]
                # Get the test bot's application ID (same as user ID for bots)
                logger.info(
                    "[Discord] Test driver bot ID: %s — "
                    "Invite it to the guild with:\n"
                    "  https://discord.com/oauth2/authorize?client_id=%s"
                    "&permissions=274877991936&scope=bot",
                    test_bot_id,
                    test_bot_id,
                )

    return result


async def provision_slack() -> dict:
    """
    Create a test channel in the Slack workspace for e2e tests.

    Uses the bot token (needs channels:manage scope).
    """
    from slack_sdk.web.async_client import AsyncWebClient

    bot_token = os.environ.get("SLACK_BOT_TOKEN")
    if not bot_token:
        logger.error("SLACK_BOT_TOKEN not set")
        return {}

    client = AsyncWebClient(token=bot_token)
    result = {}

    try:
        # Create a test channel
        channel_name = "hermes-e2e-tests"
        logger.info("[Slack] Creating channel #%s...", channel_name)
        resp = await client.conversations_create(name=channel_name, is_private=False)
        channel_id = resp["channel"]["id"]
        result["SLACK_TEST_CHANNEL_ID"] = channel_id
        logger.info("[Slack] Created channel: #%s (ID: %s)", channel_name, channel_id)

        # Set channel topic
        await client.conversations_setTopic(
            channel=channel_id,
            topic="Automated E2E testing channel for Hermes Agent. Do not use manually.",
        )

    except Exception as e:
        error_msg = str(e)
        if "name_taken" in error_msg:
            # Channel already exists, find it
            logger.info("[Slack] Channel #%s already exists, looking it up...", channel_name)
            resp = await client.conversations_list(types="public_channel", limit=200)
            for ch in resp["channels"]:
                if ch["name"] == channel_name:
                    result["SLACK_TEST_CHANNEL_ID"] = ch["id"]
                    logger.info("[Slack] Found existing channel: %s", ch["id"])
                    break
        else:
            logger.error("[Slack] Failed to create channel: %s", e)

    return result


async def provision_telegram() -> dict:
    """
    Create a test group for Telegram e2e tests.

    Uses Telethon (user account) to create a group and add the bot.
    Requires the test user's Telethon session.
    """
    try:
        from telethon import TelegramClient
        from telethon.sessions import StringSession
    except ImportError:
        logger.error("telethon not installed. Run: pip install telethon")
        return {}

    api_id = os.environ.get("TELEGRAM_API_ID")
    api_hash = os.environ.get("TELEGRAM_API_HASH")
    session = os.environ.get("TELEGRAM_TEST_SESSION", "")
    phone = os.environ.get("TELEGRAM_TEST_PHONE")
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")

    if not api_id or not api_hash:
        logger.error("TELEGRAM_API_ID and TELEGRAM_API_HASH required")
        return {}

    result = {}
    client = TelegramClient(StringSession(session), int(api_id), api_hash)

    try:
        await client.start(phone=phone)

        # Export session for future use
        exported = client.session.save()
        if exported and exported != session:
            result["TELEGRAM_TEST_SESSION"] = exported
            logger.info("[Telegram] New session string generated (save to .env)")

        # Resolve the bot
        if bot_token:
            import httpx
            async with httpx.AsyncClient() as http:
                resp = await http.get(f"https://api.telegram.org/bot{bot_token}/getMe")
                data = resp.json()
                if data.get("ok"):
                    bot_username = data["result"]["username"]
                    logger.info("[Telegram] Bot: @%s", bot_username)

                    # For Telegram, DM-based testing is simplest:
                    # the test user just messages the bot directly.
                    # No group creation needed.
                    logger.info(
                        "[Telegram] Ready for DM-based testing. "
                        "The test user will message @%s directly.",
                        bot_username,
                    )

    finally:
        await client.disconnect()

    return result


async def main():
    parser = argparse.ArgumentParser(description="Provision e2e test infrastructure")
    parser.add_argument("--telegram", action="store_true", help="Provision Telegram")
    parser.add_argument("--discord", action="store_true", help="Provision Discord")
    parser.add_argument("--slack", action="store_true", help="Provision Slack")
    parser.add_argument("--all", action="store_true", help="Provision all platforms")
    args = parser.parse_args()

    if args.all:
        args.telegram = args.discord = args.slack = True

    if not any([args.telegram, args.discord, args.slack]):
        parser.print_help()
        print("\nSpecify at least one platform or --all")
        sys.exit(1)

    all_results = {}

    if args.telegram:
        r = await provision_telegram()
        all_results.update(r)

    if args.discord:
        r = await provision_discord()
        all_results.update(r)

    if args.slack:
        r = await provision_slack()
        all_results.update(r)

    if all_results:
        print("\n" + "=" * 60)
        print("Add these to your e2e/.env file:")
        print("=" * 60)
        for key, value in all_results.items():
            print(f"{key}={value}")
        print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
