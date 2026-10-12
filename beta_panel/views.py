"""Pure presentation helpers. They never infer orders or modify the trading ledger."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Any
from urllib.parse import urlparse


ACTIVE_STATES = {"reserved", "opening", "open", "closing", "quarantine"}


def number(value: Any) -> float | None:
    try:
        parsed = float(value)
        return parsed if parsed == parsed and abs(parsed) != float("inf") else None
    except (TypeError, ValueError, OverflowError):
        return None


def money(value: Any, signed: bool = False) -> str:
    parsed = number(value)
    if parsed is None:
        return "Unavailable"
    return f"{parsed:+,.2f}".replace("+", "+$", 1).replace("-", "−$", 1) if signed else f"${parsed:,.2f}"


def premium(position: dict[str, Any]) -> float | None:
    """For standard option contracts: entry quote is per share, multiplier is 100."""
    price, qty = number(position.get("entry_price")), number(position.get("qty"))
    if price is None or qty is None:
        return None
    return price * qty * 100


def timestamp(value: Any) -> str:
    if not value:
        return "Not recorded"
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.strftime("%Y-%m-%d %H:%M") + " (zone unspecified)"
        return parsed.astimezone(ZoneInfo('America/New_York')).strftime("%b %d, %I:%M:%S %p ET")
    except (ValueError, TypeError):
        return str(value)


def age_minutes(value: Any) -> float | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return (datetime.now(timezone.utc) - parsed).total_seconds() / 60
    except (ValueError, TypeError):
        return None


def safe_url(value: Any) -> str | None:
    text = str(value or "").strip()
    parsed = urlparse(text)
    return text if parsed.scheme in {"https", "http"} and parsed.netloc else None


def label(value: Any) -> str:
    return str(value or "Not available").replace("_", " ").strip().title()


def cell(value: Any) -> str:
    if value is None or value == "":
        return "Not available"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (dict, list)):
        import json

        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)


def rank_dossiers(dossiers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rank by research points; don't mix preliminary and final contract scores."""
    return sorted(dossiers, key=lambda item: (-(number((item.get('research_scorecard') or {}).get('research_points')) or 0), str(item.get("symbol", ""))))


def position_rows(positions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "Stock": p.get("symbol", ""),
            "Direction": label(p.get("direction")),
            "Contract": p.get("option_symbol", "Not selected"),
            "Expiration": p.get("expiration", "Not recorded"),
            "Strike": money(p.get("strike")),
            "Quantity": p.get("qty", "Not recorded"),
            "State": label(p.get("state")),
            "Entry premium": money(premium(p)),
            "Bid / share": money(p.get("current_bid")),
            "Open P/L": money(p.get("unrealized_pnl"), signed=True),
            "Realized P/L": money(p.get("realized_pnl"), signed=True),
            "Close deadline": timestamp(p.get("close_deadline")),
        }
        for p in positions
    ]
