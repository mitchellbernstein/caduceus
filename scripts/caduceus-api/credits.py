"""
Caduceus Credits Tracker — tracks cloud API usage and billing.

Usage is recorded per mission and aggregated for billing reports.
Tracks: model, tokens used, API calls, cost estimates.

Costs are estimated based on current LLM provider pricing.
Actual costs should be reconciled with provider billing.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field, asdict
from enum import Enum

CADUCEUS_BASE = Path.home() / ".hermes" / "caduceus"


# ─── Cost Model ────────────────────────────────────────────────────────────────

# Pricing per 1M tokens (input / output) — update as needed
COST_PER_MILLION = {
    "gpt-4o":        (2.50, 10.00),   # input, output
    "gpt-4o-mini":   (0.15,  0.60),
    "claude-3-5-sonnet": (3.00, 15.00),
    "claude-3-opus":  (15.00, 75.00),
    "gemini-1.5-pro": (1.25,  5.00),
    "gemini-1.5-flash": (0.075, 0.30),
    "default":        (1.00,  4.00),
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate cost in dollars based on token counts."""
    in_price, out_price = COST_PER_MILLION.get(model, COST_PER_MILLION["default"])
    return (input_tokens / 1_000_000) * in_price + (output_tokens / 1_000_000) * out_price


# ─── Usage Record ─────────────────────────────────────────────────────────────

@dataclass
class UsageRecord:
    mission_id: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    provider: str = ""           # openai, anthropic, google
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    api_calls: int = 1
    estimated_cost_usd: float = 0.0
    session_id: Optional[str] = None
    task_id: Optional[str] = None
    success: bool = True


# ─── Credits Store ─────────────────────────────────────────────────────────────

class CreditsStore:
    """Tracks and persists usage records per mission."""

    def __init__(self, base: Path = CADUCEUS_BASE):
        self.base = base
        self.usage_file = base / "credits" / "usage.jsonl"
        self.summary_file = base / "credits" / "summary.json"
        self.usage_file.parent.mkdir(parents=True, exist_ok=True)

    def record(self, record: UsageRecord):
        """Append a usage record."""
        with open(self.usage_file, "a") as f:
            f.write(json.dumps(asdict(record)) + "\n")

    def record_api_call(
        self,
        mission_id: str,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        session_id: str = "",
        task_id: str = "",
        success: bool = True,
    ):
        """Convenience method to record an API call with cost estimation."""
        cost = estimate_cost(model, input_tokens, output_tokens)
        record = UsageRecord(
            mission_id=mission_id,
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_usd=cost,
            session_id=session_id,
            task_id=task_id,
            success=success,
        )
        self.record(record)
        return cost

    def get_mission_usage(self, mission_id: str) -> dict:
        """Get total usage for a specific mission."""
        total_input = 0
        total_output = 0
        total_calls = 0
        total_cost = 0.0
        records = []

        if self.usage_file.exists():
            with open(self.usage_file) as f:
                for line in f:
                    try:
                        r = json.loads(line)
                        if r.get("mission_id") == mission_id:
                            total_input += r.get("input_tokens", 0)
                            total_output += r.get("output_tokens", 0)
                            total_calls += r.get("api_calls", 0)
                            total_cost += r.get("estimated_cost_usd", 0.0)
                            records.append(r)
                    except Exception:
                        pass

        return {
            "mission_id": mission_id,
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_api_calls": total_calls,
            "estimated_cost_usd": round(total_cost, 6),
            "records": records[-50:],  # last 50 records for detail
        }

    def get_all_usage(self, limit: int = 100) -> dict:
        """Get usage across all missions."""
        missions: dict[str, dict] = {}
        total_cost = 0.0
        total_calls = 0

        if self.usage_file.exists():
            with open(self.usage_file) as f:
                for line in f:
                    try:
                        r = json.loads(line)
                        mid = r.get("mission_id", "unknown")
                        if mid not in missions:
                            missions[mid] = {
                                "total_input_tokens": 0,
                                "total_output_tokens": 0,
                                "total_api_calls": 0,
                                "estimated_cost_usd": 0.0,
                            }
                        missions[mid]["total_input_tokens"] += r.get("input_tokens", 0)
                        missions[mid]["total_output_tokens"] += r.get("output_tokens", 0)
                        missions[mid]["total_api_calls"] += r.get("api_calls", 0)
                        missions[mid]["estimated_cost_usd"] += r.get("estimated_cost_usd", 0.0)
                        total_calls += r.get("api_calls", 0)
                        total_cost += r.get("estimated_cost_usd", 0.0)
                    except Exception:
                        pass

        return {
            "total_estimated_cost_usd": round(total_cost, 6),
            "total_api_calls": total_calls,
            "missions": [
                {"mission_id": mid, **v, "estimated_cost_usd": round(v["estimated_cost_usd"], 6)}
                for mid, v in sorted(missions.items(), key=lambda x: -x[1]["estimated_cost_usd"])
            ][:limit],
        }

    def get_budget_status(self, mission_id: str, budget_monthly_cents: int) -> dict:
        """Check if a mission is within its monthly budget."""
        usage = self.get_mission_usage(mission_id)
        spent_cents = int(usage["estimated_cost_usd"] * 100)
        budget_cents = budget_monthly_cents
        remaining = budget_cents - spent_cents

        return {
            "mission_id": mission_id,
            "budget_monthly_cents": budget_cents,
            "spent_monthly_cents": spent_cents,
            "remaining_cents": remaining,
            "remaining_pct": round(remaining / budget_cents * 100, 1) if budget_cents else 100,
            "over_budget": spent_cents > budget_cents if budget_cents else False,
            "estimated_cost_usd": usage["estimated_cost_usd"],
        }
