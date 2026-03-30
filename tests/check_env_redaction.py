#!/usr/bin/env python3
"""Check which .env.example variables survive redaction."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agent.redact import redact_sensitive_text

tests = [
    "OPENROUTER_API_KEY=sk-or-v1-secret1234567890123456789012345",
    "TELEGRAM_BOT_TOKEN=bot123456789:ABCDEfghij-KLMNopqrst_UVWXyz12345",
    "FAL_KEY=fal_abc123def456ghi789jkl",
    "FIRECRAWL_API_KEY=fc-shortkey123456789012",
    "BROWSERBASE_API_KEY=bb_live_abc123def456ghi789",
    "VOICE_TOOLS_OPENAI_KEY=sk-proj-abc123def456ghi789jkl012",
    "SUDO_PASSWORD=mysudopassword12345678",
    "EMAIL_PASSWORD=myemailpassword12345678",
    "WANDB_API_KEY=wandb_abc123def456ghi789jkl012",
    "TINKER_API_KEY=tinker_abc123def456ghi789jkl",
    "GLM_API_KEY=glm_abc123def456ghi789jkl012",
    "KIMI_API_KEY=sk-kimi-abc123def456ghi789jkl",
    "MINIMAX_API_KEY=minimax_abc123def456ghi789jkl",
    "HONCHO_API_KEY=honcho_abc123def456ghi789jkl",
    "SLACK_BOT_TOKEN=xoxb-0000000000000-0000000000000-FAKEFAKEFAKEFAKE",
    "SLACK_APP_TOKEN=xapp-0-A000000000-0000000000000-FAKEFAKEFAKEFAKE",
    "GITHUB_TOKEN=ghp_abc123def456ghi789jklmno",
    # Now test bare values (no env name context, like `printenv VAR` or `echo $VAR`)
]

print()
print("=" * 90)
print("  TEST 1: env assignment format (e.g. from `env | grep KEY`)")
print("=" * 90)
print(f"  {'ENV VAR':<35} {'STATUS':<10} AFTER REDACTION")
print("-" * 90)
for t in tests:
    name = t.split("=")[0]
    value = t.split("=", 1)[1]
    result = redact_sensitive_text(t)
    leaked = value in result
    status = "\033[91mLEAKED\033[0m" if leaked else "\033[92mREDACTED\033[0m"
    print(f"  {name:<35} {status}    {result}")

print()
print("=" * 90)
print("  TEST 2: bare value (e.g. from `echo $VAR` or `printenv VAR`)")
print("=" * 90)
print(f"  {'ENV VAR':<35} {'STATUS':<10} AFTER REDACTION")
print("-" * 90)
for t in tests:
    name = t.split("=")[0]
    value = t.split("=", 1)[1]
    result = redact_sensitive_text(value)
    leaked = value in result
    status = "\033[91mLEAKED\033[0m" if leaked else "\033[92mREDACTED\033[0m"
    print(f"  {name:<35} {status}    {result}")

print()
print("=" * 90)
print("  TEST 3: base64 encoded bare value (e.g. `echo -n $VAR | base64`)")
print("=" * 90)
print(f"  {'ENV VAR':<35} {'STATUS':<10} AFTER REDACTION (truncated)")
print("-" * 90)
import base64
for t in tests:
    name = t.split("=")[0]
    value = t.split("=", 1)[1]
    encoded = base64.b64encode(value.encode()).decode()
    result = redact_sensitive_text(encoded)
    leaked = encoded in result
    status = "\033[91mLEAKED\033[0m" if leaked else "\033[92mREDACTED\033[0m"
    print(f"  {name:<35} {status}    {result[:50]}...")

print()
