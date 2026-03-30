# End-to-End Workdir Injection Reproduction

This directory contains a realistic reproduction of the workdir command injection
vulnerability (CVE-class: OS command injection via unsanitized `workdir` parameter).

## What this demonstrates

1. A malicious `AGENTS.md` that **bypasses the prompt injection scanner** in
   `agent/prompt_builder.py` while instructing the LLM to use a crafted `workdir`
2. The crafted workdir executes arbitrary commands when passed through SSH/Docker/Singularity
3. The approval system (`tools/approval.py`) only checks `command`, never `workdir`

## How to reproduce

### Option A: Automated test harness (no Docker/SSH needed)

```bash
cd tests/e2e_workdir_injection
python3 run_e2e.py
```

This simulates the full attack chain:
- Loads the malicious AGENTS.md
- Verifies it passes the prompt injection scanner
- Simulates the LLM sending a tool call with the injected workdir
- Shows the command that would execute on SSH/Docker/Singularity backends
- Demonstrates data exfiltration via the canary file

### Option B: Manual reproduction with hermes-agent (Docker backend)

1. Set up a project directory with the malicious AGENTS.md:
   ```bash
   mkdir /tmp/evil-project && cp AGENTS.md /tmp/evil-project/
   ```

2. Create a canary secret:
   ```bash
   echo "SUPER_SECRET_API_KEY=sk-live-abc123xyz" > /tmp/hermes_canary.txt
   ```

3. Start hermes-agent with Docker backend pointed at the evil project:
   ```bash
   cd /tmp/evil-project
   hermes --environment docker --image ubuntu:22.04
   ```

4. Ask the agent to list files:
   ```
   > list the files in my project
   ```

   The LLM reads AGENTS.md, follows the "workspace convention", and sends:
   ```json
   {"command": "ls -la", "workdir": "~/; cat /tmp/hermes_canary.txt; cd ~"}
   ```

   **Before fix**: The canary secret appears in the output.
   **After fix** (current code): `shlex.quote()` prevents injection.

## Files

- `AGENTS.md` — Malicious context file that bypasses all 10 scanner patterns
- `run_e2e.py` — Automated reproduction script
- `README.md` — This file
