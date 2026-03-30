"""
Manages a real Hermes gateway process for e2e testing.

Starts `hermes gateway run` as a subprocess, waits for adapters to connect,
and tears it down after tests complete.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class HermesRunner:
    """
    Starts and manages a Hermes gateway subprocess.

    Usage:
        runner = HermesRunner(repo_dir="/path/to/hermes-agent", env={...})
        await runner.start(timeout=60)
        # ... run tests ...
        await runner.stop()

    Or as an async context manager:
        async with HermesRunner(repo_dir=..., env={...}) as runner:
            # gateway is running
    """

    def __init__(
        self,
        repo_dir: str | Path,
        env: Optional[Dict[str, str]] = None,
        hermes_home: Optional[str | Path] = None,
    ):
        self.repo_dir = Path(repo_dir).resolve()
        self._extra_env = env or {}
        self._hermes_home = Path(hermes_home) if hermes_home else None
        self._process: Optional[subprocess.Popen] = None
        self._log_task: Optional[asyncio.Task] = None

    async def start(self, timeout: float = 90) -> None:
        """
        Start the Hermes gateway and wait for it to be ready.

        The gateway is ready when we see adapter connection log lines.
        """
        env = self._build_env()

        # Use python -m gateway.run or the cli entrypoint
        cmd = [
            sys.executable, "-m", "gateway.run",
        ]

        logger.info("Starting Hermes gateway: %s", " ".join(cmd))
        logger.info("  repo_dir: %s", self.repo_dir)
        logger.info("  HERMES_HOME: %s", env.get("HERMES_HOME", "(default)"))

        self._process = subprocess.Popen(
            cmd,
            cwd=str(self.repo_dir),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,  # line-buffered
        )

        # Stream logs in background and watch for readiness
        ready_event = asyncio.Event()
        self._log_task = asyncio.create_task(
            self._stream_logs(ready_event)
        )

        # Wait for the gateway to report at least one adapter connected
        try:
            await asyncio.wait_for(ready_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            await self.stop()
            raise RuntimeError(
                f"Hermes gateway did not become ready within {timeout}s. "
                "Check that bot tokens are valid and network is reachable."
            )

        logger.info("Hermes gateway is ready (PID %s)", self._process.pid)

    async def stop(self) -> None:
        """Gracefully stop the gateway process."""
        if self._process and self._process.poll() is None:
            logger.info("Stopping Hermes gateway (PID %s)...", self._process.pid)
            # Send SIGINT for graceful shutdown
            self._process.send_signal(signal.SIGINT)
            # Give it a few seconds to shut down
            for _ in range(10):
                if self._process.poll() is not None:
                    break
                await asyncio.sleep(1)
            # Force kill if still running
            if self._process.poll() is None:
                logger.warning("Gateway didn't stop gracefully, sending SIGKILL")
                self._process.kill()
                self._process.wait(timeout=5)

        if self._log_task and not self._log_task.done():
            self._log_task.cancel()
            try:
                await self._log_task
            except asyncio.CancelledError:
                pass

        logger.info("Hermes gateway stopped")

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    async def _stream_logs(self, ready_event: asyncio.Event) -> None:
        """Read gateway stdout/stderr and detect readiness."""
        assert self._process and self._process.stdout

        connected_platforms = set()
        target_keywords = {
            "telegram": "[Telegram] Connected",
            "discord": "Connected as",
            "slack": "[Slack] Connected",
        }

        loop = asyncio.get_event_loop()
        while True:
            line = await loop.run_in_executor(None, self._process.stdout.readline)
            if not line:
                break

            line = line.rstrip()
            logger.debug("[hermes] %s", line)

            # Check for adapter connection messages
            for platform, keyword in target_keywords.items():
                if keyword in line:
                    connected_platforms.add(platform)
                    logger.info("  -> %s adapter connected", platform)

            # Ready once at least one adapter is connected
            if connected_platforms and not ready_event.is_set():
                ready_event.set()

    def _build_env(self) -> Dict[str, str]:
        """Build the environment for the gateway subprocess."""
        env = os.environ.copy()

        # Set HERMES_HOME to an isolated directory for tests
        if self._hermes_home:
            env["HERMES_HOME"] = str(self._hermes_home)

        # Allow all users in test mode (we control who sends messages)
        env["GATEWAY_ALLOW_ALL_USERS"] = "true"

        # Merge in test-specific env vars (bot tokens, etc.)
        env.update(self._extra_env)

        # Ensure the repo is on PYTHONPATH
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = f"{self.repo_dir}:{existing}" if existing else str(self.repo_dir)

        return env

    async def __aenter__(self) -> HermesRunner:
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.stop()
