"""
Natural Language Schedule Parser

Converts human-readable scheduling expressions into cron expressions.
Zero dependencies — pure regex pattern matching.

Adapted from Mission Control's schedule-parser.ts (builderz-labs/mission-control).
Supports the same patterns as the original TypeScript version.

Supported patterns:
    "every N minutes/hours"    -> */N * * * *
    "daily" / "every day"      -> 0 9 * * *
    "every morning at Xam"     -> 0 X * * *
    "every evening at Xpm"      -> 0 (X+12) * * *
    "weekly on DAYNAME"        -> 0 9 * * DAY_NUM
    "every DAYNAME at TIME"    -> 0 H * * DAY_NUM
    "hourly"                   -> 0 * * * *
    "at TIME every day"        -> M H * * *
    fallback: treat as raw cron expression
"""

from __future__ import annotations

import re
from typing import Optional


# =============================================================================
# Types
# =============================================================================

class ParsedSchedule:
    """Result of parsing a natural language schedule."""

    def __init__(self, cron_expr: str, human_readable: str):
        self.cron_expr = cron_expr
        self.human_readable = human_readable

    def __repr__(self) -> str:
        return f"ParsedSchedule(cron={self.cron_expr!r}, human={self.human_readable!r})"

    def to_dict(self) -> dict:
        return {"cron_expr": self.cron_expr, "human_readable": self.human_readable}


# =============================================================================
# Day / Time helpers
# =============================================================================

DAY_MAP: dict[str, int] = {
    "sunday": 0, "sun": 0,
    "monday": 1, "mon": 1,
    "tuesday": 2, "tue": 2,
    "wednesday": 3, "wed": 3,
    "thursday": 4, "thu": 4,
    "friday": 5, "fri": 5,
    "saturday": 6, "sat": 6,
}


def _parse_day_name(input: str) -> Optional[int]:
    return DAY_MAP.get(input.lower())


def _parse_time(input: str) -> Optional[tuple[int, int]]:
    """Parse time string like '9am', '9:30pm', '14:00', '9'.
    Returns (hour, minute) in 24h format. None if unparseable.
    """
    m = re.match(r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$", input.strip(), re.IGNORECASE)
    if not m:
        return None

    hour = int(m.group(1))
    minute = int(m.group(2) or "0")
    ampm = (m.group(3) or "").lower()

    if ampm == "pm" and hour < 12:
        hour += 12
    if ampm == "am" and hour == 12:
        hour = 0

    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return None

    return (hour, minute)


def _format_time(hour: int, minute: int) -> str:
    """Format 24h time as human-readable string like '9:00 AM'."""
    label = "AM" if hour < 12 else "PM"
    display_hour = hour % 12 or 12
    display_min = f":{minute:02d}" if minute else ""
    return f"{display_hour}{display_min} {label}"


# =============================================================================
# Cron validation
# =============================================================================

CRON_REGEX = re.compile(
    r"^(\*|[\d,\-/]+)\s+(\*|[\d,\-/]+)\s+(\*|[\d,\-/]+)\s+(\*|[\d,\-/]+)\s+(\*|[\d,\-/]+)$"
)


def is_valid_cron(expr: str) -> bool:
    """Check if a string is a valid 5-field cron expression."""
    return bool(CRON_REGEX.match(expr.strip()))


# =============================================================================
# Natural language parser
# =============================================================================

def parse(text: str) -> Optional[ParsedSchedule]:
    """Parse a natural language schedule string into a ParsedSchedule.
    Returns None if the input cannot be parsed.
    """
    s = text.strip()
    if not s:
        return None

    # Raw cron passthrough
    if is_valid_cron(s):
        return ParsedSchedule(s, f"Custom schedule ({s})")

    lower = s.lower()

    # "hourly"
    if lower == "hourly":
        return ParsedSchedule("0 * * * *", "Every hour")

    # "daily" / "every day"
    if lower in ("daily", "every day"):
        return ParsedSchedule("0 9 * * *", "Daily at 9:00 AM")

    # "weekly" (no day specified)
    if lower == "weekly":
        return ParsedSchedule("0 9 * * 1", "Weekly on Monday at 9:00 AM")

    # "every N minutes"
    m = re.match(r"^every\s+(\d+)\s+minutes?$", lower)
    if m:
        n = int(m.group(1))
        if 1 <= n <= 59:
            plural = "s" if n > 1 else ""
            return ParsedSchedule(f"*/{n} * * * *", f"Every {n} minute plural")

    # "every N hours"
    m = re.match(r"^every\s+(\d+)\s+hours?$", lower)
    if m:
        n = int(m.group(1))
        if 1 <= n <= 23:
            plural = "s" if n > 1 else ""
            return ParsedSchedule(f"0 */{n} * * *", f"Every {n} hour plural")

    # "every morning at TIME" / "every evening at TIME" / "every day at TIME" / "daily at TIME"
    m = re.match(
        r"^(?:every\s+(?:morning|evening|day)|daily)\s+at\s+(.+)$", lower
    )
    if m:
        t = _parse_time(m.group(1))
        if t:
            hour, minute = t
            human = f"Daily at {_format_time(hour, minute)}"
            return ParsedSchedule(f"{minute} {hour} * * *", human)

    # "at TIME every day"
    m = re.match(r"^at\s+(.+?)\s+every\s+day$", lower)
    if m:
        t = _parse_time(m.group(1))
        if t:
            hour, minute = t
            human = f"Daily at {_format_time(hour, minute)}"
            return ParsedSchedule(f"{minute} {hour} * * *", human)

    # "weekly on DAYNAME" / "every DAYNAME" (no time)
    m = re.match(r"^(?:weekly\s+on|every)\s+(\w+)$", lower)
    if m:
        day_num = _parse_day_name(m.group(1))
        if day_num is not None:
            day_name = m.group(1).capitalize()
            return ParsedSchedule(
                f"0 9 * * {day_num}", f"Weekly on {day_name} at 9:00 AM"
            )

    # "every DAYNAME at TIME"
    m = re.match(r"^every\s+(\w+)\s+at\s+(.+)$", lower)
    if m:
        day_num = _parse_day_name(m.group(1))
        if day_num is not None:
            t = _parse_time(m.group(2))
            if t:
                hour, minute = t
                day_name = m.group(1).capitalize()
                human = f"Every {day_name} at {_format_time(hour, minute)}"
                return ParsedSchedule(f"{minute} {hour} * * {day_num}", human)

    # "every N days"
    m = re.match(r"^every\s+(\d+)\s+days?$", lower)
    if m:
        n = int(m.group(1))
        if 1 <= n <= 31:
            plural = "s" if n > 1 else ""
            return ParsedSchedule(f"0 9 */{n} * *", f"Every {n} day plural")

    return None


# =============================================================================
# Cron field matching (for scheduler)
# =============================================================================

def matches_cron_field(expr: str, value: int) -> bool:
    """Check if a cron field matches a given value.
    Handles: *, */N, N, N-M, N,M,O
    """
    if expr == "*":
        return True

    # Step values: */N
    if expr.startswith("*/"):
        step = int(expr[2:])
        return step > 0 and value % step == 0

    # Comma-separated
    for part in expr.split(","):
        # Range: N-M
        if "-" in part:
            start, end = part.split("-")
            if start.isdigit() and end.isdigit():
                if start <= str(value) <= end:
                    return True
        else:
            # Single value
            if part.isdigit() and int(part) == value:
                return True

    return False


def is_due(cron_expr: str, now_ts: int, last_ts: int) -> bool:
    """Check if a cron expression is due given current and last-run timestamps.
    now_ts and last_ts are unix timestamps in seconds.
    """
    import datetime

    now = datetime.datetime.fromtimestamp(now_ts)
    parts = cron_expr.split()
    if len(parts) != 5:
        return False

    min_expr, hour_expr, dom_expr, mon_expr, dow_expr = parts

    # Check minute
    if not matches_cron_field(min_expr, now.minute):
        return False
    # Check hour
    if not matches_cron_field(hour_expr, now.hour):
        return False
    # Check day of month
    if not matches_cron_field(dom_expr, now.day):
        return False
    # Check month
    if not matches_cron_field(mon_expr, now.month):
        return False
    # Check day of week
    if not matches_cron_field(dow_expr, now.weekday()):
        return False

    # Prevent duplicate fires within the same minute
    if last_ts > 0:
        last = datetime.datetime.fromtimestamp(last_ts)
        if (
            last.year == now.year
            and last.month == now.month
            and last.day == now.day
            and last.hour == now.hour
            and last.minute == now.minute
        ):
            return False

    return True
