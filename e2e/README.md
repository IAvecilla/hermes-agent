# Hermes E2E Integration Tests

Real end-to-end tests for the Hermes Agent messaging platform integrations.
**No mocks** — every test hits the actual Telegram, Discord, and Slack APIs.

## How it works

```
┌─────────────┐         ┌───────────────┐         ┌──────────────┐
│ Test Driver  │──send──▶│  Platform API  │──recv──▶│ Hermes Bot   │
│ (real user)  │◀─read───│  (real)        │◀─send───│ (real)       │
└─────────────┘         └───────────────┘         └──────────────┘
```

Each platform has a **test driver** that acts as a real user:
- **Telegram**: [Telethon](https://github.com/LonamiWebs/Telethon) — logs in as a real Telegram user via MTProto
- **Discord**: A second bot in the same guild — sends messages and listens for replies
- **Slack**: A user OAuth token — posts messages and polls channel history

The Hermes gateway runs as a real subprocess with real bot tokens.

## Quick start

```bash
cd e2e/

# Install dependencies
pip install -e .

# Copy and fill in credentials (see sections below)
cp .env.example .env

# Verify credentials work (run these first!)
pytest tests/test_connectivity.py -v

# Run all tests for a specific platform
pytest -m telegram -v
pytest -m discord -v
pytest -m slack -v

# Run everything
pytest -v
```

## Credential setup

### Telegram

You need **two things**: a bot (for Hermes) and a user account (for the test driver).

**1. Create the Hermes bot** (one-time, ~2 min):
1. Open Telegram and message [@BotFather](https://t.me/BotFather)
2. Send `/newbot`, follow the prompts
3. Copy the token → `TELEGRAM_BOT_TOKEN`

**2. Get Telethon API credentials** (one-time, ~2 min):
1. Go to https://my.telegram.org and log in
2. Go to "API development tools"
3. Create an app (any name/description)
4. Copy API ID → `TELEGRAM_API_ID`
5. Copy API Hash → `TELEGRAM_API_HASH`

**3. Test user phone**:
- Use any Telegram account's phone number → `TELEGRAM_TEST_PHONE`
- First run will send a login code to this account via Telegram
- After first login, a session string is printed — save it to `TELEGRAM_TEST_SESSION` to skip auth on future runs

### Discord

You need **two bots**: one for Hermes, one for the test driver.

**1. Create the Hermes bot** (one-time, ~5 min):
1. Go to https://discord.com/developers/applications
2. Click "New Application" → name it "Hermes E2E"
3. Go to "Bot" tab → "Reset Token" → copy → `DISCORD_BOT_TOKEN`
4. Enable these Privileged Gateway Intents:
   - Message Content Intent
   - Server Members Intent
5. Go to OAuth2 → URL Generator:
   - Scopes: `bot`
   - Permissions: Send Messages, Read Message History, Attach Files, Read Messages/View Channels
   - Open the generated URL to invite the bot to your test server

**2. Create the test driver bot** (same steps):
1. Create another application "Hermes E2E Driver"
2. Get its token → `DISCORD_TEST_BOT_TOKEN`
3. Enable Message Content Intent
4. Invite it to the same test server

**3. Set up test channel**:
- Run `python -m setup.provision --discord` (creates a guild + channel)
- Or manually create a channel and copy its ID → `DISCORD_TEST_CHANNEL_ID`

### Slack

You need a **bot app** (for Hermes) and a **user token** (for the test driver).

**1. Create the Hermes Slack app** (one-time, ~10 min):
1. Go to https://api.slack.com/apps → "Create New App" → "From scratch"
2. **OAuth & Permissions** → Bot Token Scopes:
   - `chat:write`, `channels:history`, `channels:read`, `files:read`, `files:write`
   - `reactions:write`, `users:read`, `app_mentions:read`
3. **Socket Mode** → Enable → create an App-Level Token with `connections:write` scope
   - Copy token → `SLACK_APP_TOKEN`
4. **Event Subscriptions** → Enable → Subscribe to bot events:
   - `message.channels`, `message.im`, `app_mention`
5. Install to workspace → copy Bot User OAuth Token → `SLACK_BOT_TOKEN`

**2. Get a user token for the test driver**:
1. In the same app (or a new one), add User Token Scopes:
   - `chat:write`, `channels:history`, `channels:read`
2. Re-install to workspace
3. Copy the User OAuth Token (xoxp-...) → `SLACK_TEST_USER_TOKEN`

**3. Set up test channel**:
- Run `python -m setup.provision --slack` (creates `#hermes-e2e-tests`)
- Or manually create a channel and copy its ID → `SLACK_TEST_CHANNEL_ID`
- Make sure both the bot and user are in the channel

## Provisioning

The provision script automates creating test channels/guilds:

```bash
# Provision specific platforms
python -m setup.provision --telegram
python -m setup.provision --discord
python -m setup.provision --slack

# Provision all at once
python -m setup.provision --all
```

It will print the env vars to add to your `.env` file.

## Test structure

```
e2e/
├── conftest.py                  # Session fixtures: starts hermes, connects drivers
├── hermes_runner.py             # Subprocess manager for hermes gateway
├── drivers/
│   ├── base.py                  # Abstract driver interface
│   ├── telegram_driver.py       # Telethon-based real user
│   ├── discord_driver.py        # Second bot via discord.py
│   └── slack_driver.py          # User token via slack_sdk
├── setup/
│   └── provision.py             # Creates test channels/guilds
├── tests/
│   ├── test_connectivity.py     # Credential validation (run first!)
│   ├── test_basic_reply.py      # Send message → verify response
│   ├── test_media.py            # Image/document handling
│   ├── test_slash_commands.py   # Platform-specific commands
│   └── test_multi_response.py   # Long response splitting
└── fixtures/                    # Test media files
```

## Running specific tests

```bash
# Only connectivity checks (fast, no hermes needed)
pytest tests/test_connectivity.py -v

# Only Telegram tests
pytest -m telegram -v

# Only Discord tests
pytest -m discord -v

# Only Slack tests
pytest -m slack -v

# Cross-platform tests (runs on all configured platforms)
pytest -m all_platforms -v

# Single test
pytest tests/test_basic_reply.py::test_telegram_basic_reply -v

# With debug logging
E2E_DEBUG=1 pytest -m telegram -v -s
```

## How tests auto-skip

Tests are automatically skipped if the required credentials aren't set.
You can configure just one platform and run the full suite — unconfigured
platforms will be skipped, not fail.

## Timeouts

- Bot reply timeout: 60s (configurable per test)
- Hermes gateway startup: 90s
- Per-test timeout: 120s (pytest-timeout)

These are generous because the bot needs to:
1. Receive the message from the platform
2. Process it through the AI model
3. Send the response back through the platform

## CI integration

To run in CI, add the credentials as secrets:

```yaml
# .github/workflows/e2e.yml
env:
  TELEGRAM_BOT_TOKEN: ${{ secrets.E2E_TELEGRAM_BOT_TOKEN }}
  TELEGRAM_API_ID: ${{ secrets.E2E_TELEGRAM_API_ID }}
  # ... etc
```

Note: Telegram test user auth requires a session string (no interactive
code entry in CI). Generate it locally first, then store as a secret.
