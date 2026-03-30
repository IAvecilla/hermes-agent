"""
Root conftest for the Hermes E2E test suite.

Manages the lifecycle of:
  1. The Hermes gateway (real subprocess)
  2. Platform test drivers (real connections to Telegram/Discord/Slack)

All connections are real. No mocks.
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from pathlib import Path
from typing import Dict, Optional

import pytest
from dotenv import load_dotenv

# Load .env from the e2e directory
_e2e_dir = Path(__file__).parent
load_dotenv(_e2e_dir / ".env")

from drivers.base import PlatformDriver
from hermes_runner import HermesRunner

logging.basicConfig(
    level=logging.DEBUG if os.environ.get("E2E_DEBUG") else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("e2e")


# ── Helpers ──────────────────────────────────────────────────────────────────


def _platform_available(name: str) -> bool:
    """Check if the required env vars are set for a platform."""
    required = {
        "telegram": ["TELEGRAM_BOT_TOKEN", "TELEGRAM_API_ID", "TELEGRAM_API_HASH"],
        "discord": ["DISCORD_BOT_TOKEN", "DISCORD_TEST_BOT_TOKEN", "DISCORD_TEST_CHANNEL_ID"],
        "slack": ["SLACK_BOT_TOKEN", "SLACK_APP_TOKEN", "SLACK_TEST_USER_TOKEN", "SLACK_TEST_CHANNEL_ID"],
    }
    return all(os.environ.get(v) for v in required.get(name, []))


def _available_platforms() -> list[str]:
    """Return list of platforms that have credentials configured."""
    return [p for p in ("telegram", "discord", "slack") if _platform_available(p)]


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def repo_dir() -> Path:
    """Path to the hermes-agent repository root."""
    configured = os.environ.get("HERMES_REPO_DIR")
    if configured:
        return Path(configured).resolve()
    return _e2e_dir.parent.resolve()


@pytest.fixture(scope="session")
def hermes_env() -> Dict[str, str]:
    """
    Environment variables for the Hermes gateway subprocess.

    Collects all platform tokens from the test .env.
    """
    env = {}
    # Map test env vars to what hermes expects
    token_vars = [
        "TELEGRAM_BOT_TOKEN",
        "DISCORD_BOT_TOKEN",
        "SLACK_BOT_TOKEN",
        "SLACK_APP_TOKEN",
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
        "NOUS_API_KEY",
    ]
    for var in token_vars:
        val = os.environ.get(var)
        if val:
            env[var] = val

    # Discord: the hermes bot needs to allow the test bot's messages
    env["DISCORD_ALLOW_BOTS"] = "all"
    # Discord: don't require @mention in test channel
    env["DISCORD_REQUIRE_MENTION"] = "false"

    return env


@pytest.fixture(scope="session")
def event_loop():
    """Create a session-scoped event loop for all async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def hermes(repo_dir: Path, hermes_env: Dict[str, str]) -> HermesRunner:
    """
    Start the Hermes gateway for the entire test session.

    Uses an isolated HERMES_HOME to avoid interfering with any
    local hermes installation.
    """
    hermes_home = tempfile.mkdtemp(prefix="hermes_e2e_")
    runner = HermesRunner(repo_dir=repo_dir, env=hermes_env, hermes_home=hermes_home)
    await runner.start(timeout=90)
    yield runner
    await runner.stop()


@pytest.fixture(scope="session")
async def telegram_driver() -> Optional[PlatformDriver]:
    """Telegram test driver — real Telethon user client."""
    if not _platform_available("telegram"):
        pytest.skip("Telegram credentials not configured")

    from drivers.telegram_driver import TelegramDriver

    driver = TelegramDriver()
    await driver.connect()
    yield driver
    await driver.disconnect()


@pytest.fixture(scope="session")
async def discord_driver() -> Optional[PlatformDriver]:
    """Discord test driver — real second bot."""
    if not _platform_available("discord"):
        pytest.skip("Discord credentials not configured")

    from drivers.discord_driver import DiscordDriver

    driver = DiscordDriver()
    await driver.connect()
    yield driver
    await driver.disconnect()


@pytest.fixture(scope="session")
async def slack_driver() -> Optional[PlatformDriver]:
    """Slack test driver — real user token."""
    if not _platform_available("slack"):
        pytest.skip("Slack credentials not configured")

    from drivers.slack_driver import SlackDriver

    driver = SlackDriver()
    await driver.connect()
    yield driver
    await driver.disconnect()


@pytest.fixture(scope="session")
async def drivers(
    telegram_driver, discord_driver, slack_driver
) -> Dict[str, PlatformDriver]:
    """All available platform drivers as a dict."""
    d = {}
    if telegram_driver:
        d["telegram"] = telegram_driver
    if discord_driver:
        d["discord"] = discord_driver
    if slack_driver:
        d["slack"] = slack_driver
    return d


def pytest_collection_modifyitems(config, items):
    """Auto-skip tests for platforms that don't have credentials."""
    for item in items:
        for marker_name in ("telegram", "discord", "slack"):
            if marker_name in item.keywords and not _platform_available(marker_name):
                item.add_marker(
                    pytest.mark.skip(reason=f"{marker_name} credentials not configured")
                )
