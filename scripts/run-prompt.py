#!/usr/bin/env python3
"""
run-prompt.py — Run a prompt via Hermes, replacing @file references with file contents.

Usage:
    python run-prompt.py "@prompt.md @refs/api.md Your question here" [timeout_secs]

Example:
    python run-prompt.py "@skills/caduceus-kairos/SKILL.md What is Kairos?" 300
"""
import subprocess
import sys
import re
import os
import time
from pathlib import Path


def expand_refs(text):
    """Replace @file references with file contents."""
    result = []
    for part in re.split(r'(\S+)', text):
        if part.startswith('@'):
            fpath = part[1:].strip()
            # Try relative to cwd, then absolute
            if os.path.exists(fpath):
                result.append(open(fpath).read())
            elif os.path.exists(os.path.expanduser(fpath)):
                result.append(open(os.path.expanduser(fpath)).read())
            else:
                result.append(part)  # keep as-is
        else:
            result.append(part)
    return ''.join(result)


def run_hermes(prompt, timeout=300):
    """Run a prompt via hermes chat -q and return the text response."""
    # Expand @file references
    expanded = expand_refs(prompt)

    # Call hermes
    proc = subprocess.run(
        ['hermes', 'chat', '-q', expanded],
        capture_output=True,
        text=True,
        timeout=timeout + 10
    )

    raw = proc.stdout + proc.stderr

    # Parse the output — hermes prints a separator line of ─ characters
    # The response text appears before that separator
    lines = raw.split('\n')

    # Find the separator and take everything after it that's not blank or session info
    response_lines = []
    in_session_info = False
    for line in lines:
        if re.match(r'^─+\s*$', line):
            in_session_info = True
            continue
        if in_session_info:
            if line.strip().startswith('Session:') or line.strip().startswith('Duration:') or line.strip().startswith('Messages:'):
                continue
            if line.strip().startswith('Resume'):
                continue
            if line.strip():
                response_lines.append(line)

    response = '\n'.join(response_lines).strip()

    # Fallback: if parsing failed, just return last substantial lines
    if not response:
        # Try last non-empty lines before session block
        for line in reversed(lines):
            if line.strip() and not line.strip().startswith('─') and 'Session' not in line:
                response_lines.insert(0, line.strip())

    return response


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: run-prompt.py '<prompt with @file refs>' [timeout_secs]")
        sys.exit(1)

    prompt = sys.argv[1]
    timeout = int(sys.argv[2]) if len(sys.argv) > 2 else 300

    try:
        result = run_hermes(prompt, timeout)
        print(result)
    except subprocess.TimeoutExpired:
        print(f"TIMEOUT after {timeout}s", file=sys.stderr)
        sys.exit(124)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
