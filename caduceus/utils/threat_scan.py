"""
Caduceus Threat Scanner

Scans prompts, memory content, and context files for:
- Invisible unicode injection (U+200B, etc.)
- Prompt injection patterns
- Exfiltration patterns (curl/wget with secrets)
- Shell execution attacks

Adapted from Hermes Agent's threat scanning patterns
(hermes-agent/tools/cronjob_tools.py, tools/memory_tool.py, agent/prompt_builder.py).

This is a defense-in-depth layer — Hermes Agent already scans context files
and cron prompts. This scanner adds an additional check for the orchestrator's
own operations.
"""

from __future__ import annotations

import re
from typing import Optional


# =============================================================================
# Threat patterns
# =============================================================================

# Invisible unicode characters used in injection attacks
INVISIBLE_CHARS: set[str] = {
    "\u200b",  # Zero-width space
    "\u200c",  # Zero-width non-joiner
    "\u200d",  # Zero-width joiner
    "\u2060",  # Word joiner
    "\ufeff",  # BOM
    "\u202a",  # Left-to-right embedding
    "\u202b",  # Right-to-left embedding
    "\u202c",  # Pop directional formatting
    "\u202d",  # Left-to-right override
    "\u202e",  # Right-to-left override
}

# Prompt injection patterns
INJECTION_PATTERNS: list[tuple[str, str]] = [
    # Ignore previous instructions
    (
        r"ignore\s+(?:\w+\s+){0,4}?(?:previous|all|above|prior)\s+(?:\w+\s+){0,4}?instructions",
        "prompt_injection_ignore",
    ),
    # Role hijack: "you are now..."
    (
        r"\byou\s+are\s+now\b",
        "role_hijack",
    ),
    # Deception: don't tell the user
    (
        r"do\s+not\s+tell\s+the\s+user",
        "deception_hide",
    ),
    # System prompt override
    (
        r"system\s+prompt\s+override",
        "sys_prompt_override",
    ),
    # Disregard rules
    (
        r"disregard\s+(?:your|all|any)\s+(?:instructions|rules|guidelines)",
        "disregard_rules",
    ),
    # Bypass restrictions
    (
        r"act\s+as\s+(?:if|though)\s+you\s+(?:have\s+no|don.?t\s+have)\s+(?:restrictions|limits|rules)",
        "bypass_restrictions",
    ),
    # Hidden HTML comments with injection keywords
    (
        r"<!--[^>]{0,200}?(?:ignore|override|system|secret|hidden)[^>]{0,200}?>",
        "html_comment_injection",
    ),
    # Hidden divs (display: none)
    (
        r"<\s*div\s+style\s*=\s*[\"']{0,1}[^\"']*display\s*:\s*none",
        "hidden_div",
    ),
    # Translate and execute (injection via translation)
    (
        r"translate\s+[^\n]{10,200}\s+into\s+[^\n]{10,200}\s+and\s+(?:execute|run|eval)",
        "translate_execute",
    ),
]

# Exfiltration patterns
EXFIL_PATTERNS: list[tuple[str, str]] = [
    # curl with secret env vars
    (
        r"curl\s+[^\n]*\$\{?[\w]*(?:KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|API|PRIVATE)",
        "exfil_curl",
    ),
    # wget with secret env vars
    (
        r"wget\s+[^\n]*\$\{?[\w]*(?:KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|API|PRIVATE)",
        "exfil_wget",
    ),
    # Read secrets files
    (
        r"cat\s+[^\n]*(?:\.env|credentials|\.netrc|\.pgpass|\.npmrc|\.pypirc|\.ssh)",
        "read_secrets",
    ),
    # SSH backdoor
    (
        r"authorized_keys",
        "ssh_backdoor",
    ),
    # Hermes env theft
    (
        r"\$HOME[/\\]\.hermes[/\\]\.env|\$HOME[/\\]\.hermes[/\\]caduceus\.db",
        "hermes_env",
    ),
    # AWS keys
    (
        r"AKIA[0-9A-Z]{16}",
        "aws_key",
    ),
    # GitHub tokens
    (
        r"gh[pousr]_[0-9a-zA-Z]{36,}",
        "github_token",
    ),
    # Stripe keys
    (
        r"sk_live_[0-9a-zA-Z]{24,}",
        "stripe_key",
    ),
    # Anthropic / OpenAI keys
    (
        r"sk-ant-[a-zA-Z0-9_-]{48,}",
        "anthropic_key",
    ),
    (
        r"sk-[0-9a-zA-Z]{48,}",
        "openai_key",
    ),
]

# Dangerous shell commands
DANGEROUS_CMDS: list[tuple[str, str]] = [
    (
        r"rm\s+-rf\s+/(?:\*)?",
        "destructive_root_rm",
    ),
    (
        r">\s*/etc/sudoers",
        "sudoers_mod",
    ),
    (
        r"chmod\s+-R\s+777\s+/",
        "chmod_world_writable",
    ),
    (
        r"curl\s+[^\n]*\|\s*(?:bash|sh|zsh|perl|python|ruby)",
        "pipe_curl_to_shell",
    ),
    (
        r"wget\s+[^\n]*\|\s*(?:bash|sh|zsh|perl|python|ruby)",
        "pipe_wget_to_shell",
    ),
    # Fork bombs
    (
        r":\(\)\s*:\|\s*:&*\s*:",
        "fork_bomb",
    ),
    # DDOS
    (
        r"nmap\s+--script-exec\s+",
        "nmap_scan",
    ),
]


# =============================================================================
# Scanner
# =============================================================================

class ThreatScanResult:
    """Result of a threat scan."""

    def __init__(
        self,
        clean: bool = True,
        threats: Optional[list[dict]] = None,
        message: str = "Clean",
    ):
        self.clean = clean
        self.threats = threats or []
        self.message = message

    def __repr__(self) -> str:
        if self.clean:
            return f"ThreatScanResult(clean=True)"
        return f"ThreatScanResult(clean=False, threats={self.threats!r})"

    def to_dict(self) -> dict:
        return {
            "clean": self.clean,
            "threats": self.threats,
            "message": self.message,
        }


def scan_invisible_chars(text: str) -> list[dict]:
    """Detect invisible unicode characters in text."""
    found = []
    for char in INVISIBLE_CHARS:
        if char in text:
            found.append({
                "type": "invisible_unicode",
                "char": f"U+{ord(char):04X}",
                "description": f"Invisible unicode {f'U+{ord(char):04X}'} found",
            })
    return found


def scan_patterns(text: str, patterns: list[tuple[str, str]]) -> list[dict]:
    """Scan text for regex patterns. Returns list of matched threats."""
    found = []
    for pattern, pid in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            found.append({
                "type": pid,
                "pattern": pattern,
                "description": f"Text matches threat pattern '{pid}'",
            })
    return found


def scan(text: str, source: str = "unknown") -> ThreatScanResult:
    """Full threat scan of a text string.
    Returns ThreatScanResult with clean=True if no threats found.
    """
    threats = []

    # 1. Invisible unicode
    threats.extend(scan_invisible_chars(text))

    # 2. Prompt injection
    threats.extend(scan_patterns(text, INJECTION_PATTERNS))

    # 3. Exfiltration
    threats.extend(scan_patterns(text, EXFIL_PATTERNS))

    # 4. Dangerous shell commands
    threats.extend(scan_patterns(text, DANGEROUS_CMDS))

    if threats:
        threat_names = [t["type"] for t in threats]
        return ThreatScanResult(
            clean=False,
            threats=threats,
            message=(
                f"Blocked: '{source}' contains threat patterns: {', '.join(threat_names)}. "
                "Content not loaded or executed."
            ),
        )

    return ThreatScanResult(clean=True, message="Clean")


def scan_prompt(prompt: str) -> ThreatScanResult:
    """Scan a prompt before it gets sent to an agent."""
    return scan(prompt, source="prompt")


def scan_context_file(content: str, filename: str) -> ThreatScanResult:
    """Scan a context file (AGENTS.md, SOUL.md, etc.) before injecting into system prompt."""
    result = scan(content, source=f"file:{filename}")
    if not result.clean:
        result.message = (
            f"Blocked: {filename} contained potential prompt injection "
            f"({', '.join(t['type'] for t in result.threats)}). Content not loaded."
        )
    return result


def scan_memory_entry(content: str) -> ThreatScanResult:
    """Scan memory content before storing."""
    result = scan(content, source="memory")
    if not result.clean:
        result.message = (
            f"Blocked: memory entry contained potential injection "
            f"({', '.join(t['type'] for t in result.threats)}). Entry not saved."
        )
    return result


# =============================================================================
# Sanitizer (optional — just flagging, not auto-removing)
# =============================================================================

REMOVE_CHARS = {c for c in INVISIBLE_CHARS}


def strip_invisible(text: str) -> str:
    """Remove invisible unicode characters from text. Does not remove threats."""
    for char in REMOVE_CHARS:
        text = text.replace(char, "")
    return text


def remove_injection_block(text: str) -> str:
    """Strip invisible unicode and normalize whitespace.
    Use this before displaying user content to prevent homoglyph attacks.
    """
    text = strip_invisible(text)
    # Normalize unicode directional overrides
    text = re.sub(r"[\u202a-\u202e]", "", text)
    return text
