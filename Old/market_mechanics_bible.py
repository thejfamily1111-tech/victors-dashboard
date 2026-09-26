from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from typing import Any, Dict, Literal, Optional, Tuple
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd


ET = ZoneInfo("America/New_York")
Direction = Literal["CALL", "PUT"]
BarLabel = Literal["start", "end"]


# ============================================================
# Data containers
# ============================================================

@dataclass(frozen=True)
class ORBState:
    session_date: str
    source_bar_minutes: int

    orb5_high: float
    orb5_low: float
    orb15_high: float
    orb15_low: float
    orb30_high: float
    orb30_low: float

    accepted_or_high: float
    accepted_or_low: float
    orb30_mid: float

    orb30_width_dollars: float
    orb30_width_atr: float

    bars_5m: int
    bars_15m: int
    bars_30m: int

    orb5_locked: bool
    orb15_locked: bool
    orb30_locked: bool

    locked_at: Optional[str]


@dataclass(frozen=True)
class RVOLMetrics:
    ratio_mean: float
    ratio_median: float
    percentile: float
    zscore: float
    sample_size: int
    slot_time: str


@dataclass(frozen=True)
class AttemptState:
    bullish_attempts: int
    bearish_attempts: int
    bullish_state: str
    bearish_state: str
    bars_since_last_bull_break: Optional[int]
    bars_since_last_bear_break: Optional[int]


@dataclass(frozen=True)
class ResearchThresholds:
    """
    Research defaults only. These are NOT claimed to be optimal.
    LEARN should validate them out-of-sample before HERO/VIC enforce them.
    """
    clean_body_pct_min: float = 45.0
    clean_wick_pct_max: float = 20.0
    clean_clv_abs_min: float = 0.50
    trap_wick_pct_min: float = 25.0
    trap_close_location_mid: float = 0.50
    extension_warning_r: float = 1.00
    retest_tolerance_atr: float = 0.10
    trap_max_bars_since_breach: int = 2


# ============================================================
# Time / dataframe hygiene
# ============================================================

def _require_datetime_index(df: pd.DataFrame) -> None:
    if not isinstance(df.index, pd.DatetimeIndex):
        raise TypeError("bars_df must use a pandas.DatetimeIndex.")


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    if isinstance(out.columns, pd.MultiIndex):
        out.columns = out.columns.get_level_values(0)

    rename_map = {}
    for col in out.columns:
        low = str(col).strip().lower()
        if low == "open":
            rename_map[col] = "Open"
        elif low == "high":
            rename_map[col] = "High"
        elif low == "low":
            rename_map[col] = "Low"
        elif low == "close":
            rename_map[col] = "Close"
        elif low == "volume":
            rename_map[col] = "Volume"

    out = out.rename(columns=rename_map)

    required = {"Open", "High", "Low", "Close"}
    missing = required.difference(out.columns)
    if missing:
        raise ValueError(f"Missing required OHLC columns: {sorted(missing)}")

    return out


def _to_eastern(df: pd.DataFrame) -> pd.DataFrame:
    """
    Converts timezone-aware input bars to America/New_York.

    Intentionally refuses timezone-naive data. Guessing whether a naive
    timestamp is UTC or ET can corrupt the opening-range window.
    """
    _require_datetime_index(df)

    if df.index.tz is None:
        raise ValueError(
            "bars_df index is timezone-naive. Localize it at the data-source "
            "boundary before calling market mechanics."
        )

    out = _normalize_columns(df)
    out.index = out.index.tz_convert(ET)
    return out.sort_index()


def _normalize_decision_ts(decision_ts: pd.Timestamp | str) -> pd.Timestamp:
    ts = pd.Timestamp(decision_ts)
    if ts.tzinfo is None:
        raise ValueError("decision_ts must be timezone-aware.")
    return ts.tz_convert(ET)


def infer_bar_minutes(df: pd.DataFrame) -> int:
    """
    Infers the source bar interval from the median timestamp spacing.
    Multi-ORB research requires 1-minute or 5-minute source bars.
    """
    if len(df.index) < 2:
        raise ValueError("Need at least two bars to infer bar interval.")

    diffs = df.index.to_series().diff().dropna().dt.total_seconds() / 60.0
    if diffs.empty:
        raise ValueError("Unable to infer bar interval.")

    minutes = int(round(float(diffs.median())))
    if minutes not in {1, 5}:
        raise ValueError(
            f"Unsupported source bar interval: {minutes}m. "
            "Use 1m or 5m bars so ORB5/15/30 are not contaminated by larger bars."
        )
    return minutes


def _completed_bars(
    bars_df: pd.DataFrame,
    decision_ts: pd.Timestamp,
    bar_minutes: int,
    bar_label: BarLabel,
) -> pd.DataFrame:
    """
    Returns only bars that were fully completed at decision_ts.
    Assumes timestamps label either bar START or bar END explicitly.
    """
    if bar_label == "start":
        completion_ts = bars_df.index + pd.Timedelta(minutes=bar_minutes)
        mask = completion_ts <= decision_ts
    else:
        mask = bars_df.index <= decision_ts

    return bars_df.loc[mask].copy()


def _session_slice(
    df: pd.DataFrame,
    session_date: date,
    start_hhmm: str,
    end_hhmm: str,
) -> pd.DataFrame:
    start = pd.Timestamp(f"{session_date} {start_hhmm}:00", tz=ET)
    end = pd.Timestamp(f"{session_date} {end_hhmm}:00", tz=ET)
    return df[(df.index >= start) & (df.index < end)].copy()


def _window(
    completed_session_df: pd.DataFrame,
    session_date: date,
    minutes: int,
) -> pd.DataFrame:
    start = pd.Timestamp(f"{session_date} 09:30:00", tz=ET)
    end = start + pd.Timedelta(minutes=minutes)
    return completed_session_df[
        (completed_session_df.index >= start)
        & (completed_session_df.index < end)
    ].copy()


# ============================================================
# Opening Range — single source of truth
# ============================================================

def calculate_multi_orb(
    bars_df: pd.DataFrame,
    session_date: date,
    decision_ts: pd.Timestamp | str,
    atr: float,
    *,
    bar_label: BarLabel = "start",
) -> ORBState:
    """
    Computes ORB5 / ORB15 / ORB30 from 1m or 5m bars with strict no-lookahead logic.

    Rules:
    - Input bars must be timezone-aware.
    - All calculations are converted to America/New_York.
    - Only bars fully completed by decision_ts are eligible.
    - ORB30 is LOCKED only after 10:00 ET AND all expected opening bars exist.
    - The ORB values themselves are never rounded here; round only for display.
    """
    df = _to_eastern(bars_df)
    decision = _normalize_decision_ts(decision_ts)

    bar_minutes = infer_bar_minutes(df)
    completed = _completed_bars(df, decision, bar_minutes, bar_label)
    session = _session_slice(completed, session_date, "09:30", "16:00")

    w5 = _window(session, session_date, 5)
    w15 = _window(session, session_date, 15)
    w30 = _window(session, session_date, 30)

    def hi_lo(window_df: pd.DataFrame) -> Tuple[float, float]:
        if window_df.empty:
            return float("nan"), float("nan")
        return float(window_df["High"].max()), float(window_df["Low"].min())

    orb5_h, orb5_l = hi_lo(w5)
    orb15_h, orb15_l = hi_lo(w15)
    orb30_h, orb30_l = hi_lo(w30)

    accepted_h = float(w30["Close"].max()) if not w30.empty else float("nan")
    accepted_l = float(w30["Close"].min()) if not w30.empty else float("nan")

    orb30_mid = (
        (orb30_h + orb30_l) / 2.0
        if np.isfinite(orb30_h) and np.isfinite(orb30_l)
        else float("nan")
    )
    width_dollars = (
        max(orb30_h - orb30_l, 0.0)
        if np.isfinite(orb30_h) and np.isfinite(orb30_l)
        else float("nan")
    )
    width_atr = (
        width_dollars / max(float(atr), 1e-9)
        if np.isfinite(width_dollars)
        else float("nan")
    )

    expected_5 = 5 // bar_minutes
    expected_15 = 15 // bar_minutes
    expected_30 = 30 // bar_minutes

    lock_5_ts = pd.Timestamp(f"{session_date} 09:35:00", tz=ET)
    lock_15_ts = pd.Timestamp(f"{session_date} 09:45:00", tz=ET)
    lock_30_ts = pd.Timestamp(f"{session_date} 10:00:00", tz=ET)

    orb5_locked = decision >= lock_5_ts and len(w5) >= expected_5
    orb15_locked = decision >= lock_15_ts and len(w15) >= expected_15
    orb30_locked = decision >= lock_30_ts and len(w30) >= expected_30

    return ORBState(
        session_date=str(session_date),
        source_bar_minutes=bar_minutes,
        orb5_high=orb5_h,
        orb5_low=orb5_l,
        orb15_high=orb15_h,
        orb15_low=orb15_l,
        orb30_high=orb30_h,
        orb30_low=orb30_l,
        accepted_or_high=accepted_h,
        accepted_or_low=accepted_l,
        orb30_mid=orb30_mid,
        orb30_width_dollars=width_dollars,
        orb30_width_atr=width_atr,
        bars_5m=len(w5),
        bars_15m=len(w15),
        bars_30m=len(w30),
        orb5_locked=orb5_locked,
        orb15_locked=orb15_locked,
        orb30_locked=orb30_locked,
        locked_at=lock_30_ts.isoformat() if orb30_locked else None,
    )


# ============================================================
# ORB width context
# ============================================================

def compute_orb30_width_percentile(
    bars_df: pd.DataFrame,
    current_session_date: date,
    current_width: float,
    *,
    lookback_sessions: int = 40,
) -> Dict[str, float]:
    """
    Compares today's ORB30 dollar width with prior sessions' ORB30 widths.

    Research feature only. For cross-ticker comparability, also keep
    orb30_width_atr from calculate_multi_orb().
    """
    df = _to_eastern(bars_df)

    prior = df[df.index.date < current_session_date]
    unique_dates = sorted(set(prior.index.date))[-lookback_sessions:]

    widths = []
    for d in unique_dates:
        w = _session_slice(prior, d, "09:30", "10:00")
        if w.empty:
            continue
        width = float(w["High"].max() - w["Low"].min())
        if np.isfinite(width) and width >= 0:
            widths.append(width)

    if not widths or not np.isfinite(current_width):
        return {
            "percentile": float("nan"),
            "sample_size": 0.0,
            "historical_median": float("nan"),
            "historical_mean": float("nan"),
        }

    arr = np.asarray(widths, dtype=float)
    percentile = 100.0 * float(np.mean(arr <= current_width))

    return {
        "percentile": percentile,
        "sample_size": float(len(arr)),
        "historical_median": float(np.median(arr)),
        "historical_mean": float(np.mean(arr)),
    }


# ============================================================
# Bar anatomy
# ============================================================

def compute_bar_anatomy(candle: pd.Series) -> Dict[str, float]:
    """Pure descriptive features; no threshold here is treated as universal."""
    o = float(candle["Open"])
    h = float(candle["High"])
    l = float(candle["Low"])
    c = float(candle["Close"])

    total_range = max(h - l, 1e-9)
    body = abs(c - o)

    body_pct = (body / total_range) * 100.0
    upper_wick_pct = ((h - max(o, c)) / total_range) * 100.0
    lower_wick_pct = ((min(o, c) - l) / total_range) * 100.0
    clv = ((c - l) - (h - c)) / total_range
    close_location = (c - l) / total_range

    return {
        "open": o,
        "high": h,
        "low": l,
        "close": c,
        "total_range": total_range,
        "body_pct": body_pct,
        "upper_wick_pct": upper_wick_pct,
        "lower_wick_pct": lower_wick_pct,
        "clv": clv,
        "close_location": close_location,
    }


# ============================================================
# Extension / effective reward-risk
# ============================================================

def compute_extension_r(
    direction: Direction,
    spot: float,
    orb_high: float,
    orb_low: float,
    initial_r: float,
) -> Dict[str, float]:
    """
    Returns both signed extension and post-break extension.
    Negative signed values mean the relevant ORB boundary has not been crossed.
    """
    if initial_r <= 0:
        raise ValueError("initial_r must be > 0 and frozen at decision time.")

    if direction == "CALL":
        signed = (spot - orb_high) / initial_r
    elif direction == "PUT":
        signed = (orb_low - spot) / initial_r
    else:
        raise ValueError("direction must be CALL or PUT.")

    return {
        "extension_r_signed": float(signed),
        "extension_r_post_break": float(max(0.0, signed)),
    }


def compute_effective_rr(
    direction: Direction,
    entry: float,
    stop: float,
    target: float,
) -> float:
    """Remaining reward/risk at the proposed entry."""
    if direction == "CALL":
        risk = entry - stop
        reward = target - entry
    elif direction == "PUT":
        risk = stop - entry
        reward = entry - target
    else:
        raise ValueError("direction must be CALL or PUT.")

    if risk <= 0:
        return float("nan")
    return float(reward / risk)


# ============================================================
# Same-clock RVOL
# ============================================================

def compute_same_clock_rvol(
    bars_df: pd.DataFrame,
    current_bar_ts: pd.Timestamp | str,
    *,
    lookback_sessions: int = 40,
) -> RVOLMetrics:
    """
    Time-normalized RVOL:
      current bar volume vs the same clock slot over prior sessions.
    """
    df = _to_eastern(bars_df)
    if "Volume" not in df.columns:
        raise ValueError("Volume column is required for RVOL.")

    ts = _normalize_decision_ts(current_bar_ts)

    same_slot = df[
        (df.index.hour == ts.hour)
        & (df.index.minute == ts.minute)
        & (df.index.date < ts.date())
    ].sort_index()

    same_slot = same_slot.groupby(same_slot.index.date).tail(1)
    same_slot = same_slot.tail(lookback_sessions)

    current_rows = df[df.index == ts]
    if current_rows.empty:
        raise ValueError(f"No current bar found at {ts.isoformat()}")

    current_volume = float(current_rows.iloc[-1]["Volume"])
    hist = same_slot["Volume"].astype(float).to_numpy()

    if len(hist) == 0:
        return RVOLMetrics(
            ratio_mean=float("nan"),
            ratio_median=float("nan"),
            percentile=float("nan"),
            zscore=float("nan"),
            sample_size=0,
            slot_time=ts.strftime("%H:%M"),
        )

    mean = float(np.mean(hist))
    median = float(np.median(hist))
    std = float(np.std(hist, ddof=1)) if len(hist) > 1 else float("nan")

    ratio_mean = current_volume / mean if mean > 0 else float("nan")
    ratio_median = current_volume / median if median > 0 else float("nan")
    percentile = 100.0 * float(np.mean(hist <= current_volume))
    zscore = (
        (current_volume - mean) / std
        if np.isfinite(std) and std > 0
        else float("nan")
    )

    return RVOLMetrics(
        ratio_mean=ratio_mean,
        ratio_median=ratio_median,
        percentile=percentile,
        zscore=zscore,
        sample_size=len(hist),
        slot_time=ts.strftime("%H:%M"),
    )


# ============================================================
# Breakout attempt state
# ============================================================

def compute_breakout_attempt_state(
    bars_df: pd.DataFrame,
    session_date: date,
    decision_ts: pd.Timestamp | str,
    orb_high: float,
    orb_low: float,
    *,
    bar_label: BarLabel = "start",
) -> AttemptState:
    """Counts outside-close breakout attempts after 10:00 ET."""
    df = _to_eastern(bars_df)
    decision = _normalize_decision_ts(decision_ts)
    bar_minutes = infer_bar_minutes(df)
    completed = _completed_bars(df, decision, bar_minutes, bar_label)

    post_orb = _session_slice(completed, session_date, "10:00", "16:00")
    if post_orb.empty:
        return AttemptState(0, 0, "UNTESTED", "UNTESTED", None, None)

    closes = post_orb["Close"].astype(float)
    prev = closes.shift(1)

    bull_start = (closes > orb_high) & (prev <= orb_high)
    bear_start = (closes < orb_low) & (prev >= orb_low)

    bull_positions = np.flatnonzero(bull_start.fillna(False).to_numpy())
    bear_positions = np.flatnonzero(bear_start.fillna(False).to_numpy())

    bull_n = int(len(bull_positions))
    bear_n = int(len(bear_positions))

    def state_for(direction: str, count: int, close: float) -> str:
        if count == 0:
            return "UNTESTED"
        outside = close > orb_high if direction == "BULL" else close < orb_low
        if count == 1 and outside:
            return "FIRST_BREAK"
        if count >= 2 and outside:
            return "REPEAT_BREAK"
        return "FAILED_BREAK"

    last_pos = len(post_orb) - 1
    bars_since_bull = int(last_pos - bull_positions[-1]) if bull_n else None
    bars_since_bear = int(last_pos - bear_positions[-1]) if bear_n else None
    last_close = float(closes.iloc[-1])

    return AttemptState(
        bullish_attempts=bull_n,
        bearish_attempts=bear_n,
        bullish_state=state_for("BULL", bull_n, last_close),
        bearish_state=state_for("BEAR", bear_n, last_close),
        bars_since_last_bull_break=bars_since_bull,
        bars_since_last_bear_break=bars_since_bear,
    )


# ============================================================
# Retest / false-break features
# ============================================================

def detect_recent_false_break(
    recent_completed_bars: pd.DataFrame,
    direction: Direction,
    orb_high: float,
    orb_low: float,
    vwap: float,
    *,
    max_bars_since_breach: int = 2,
) -> Dict[str, Any]:
    """
    Detects a LOCAL false break, not a stale session-high/session-low event.
    """
    if recent_completed_bars.empty:
        return {
            "false_break": False,
            "bars_since_breach": None,
            "reason_code": "NO_RECENT_BARS",
        }

    recent = _normalize_columns(recent_completed_bars).tail(max_bars_since_breach + 1)
    current_close = float(recent.iloc[-1]["Close"])

    if direction == "CALL":
        breach_mask = recent["Low"].astype(float) < orb_low
        reclaimed = current_close >= orb_low and current_close >= vwap
        code = "RECENT_BEAR_TRAP_RECLAIM"
    elif direction == "PUT":
        breach_mask = recent["High"].astype(float) > orb_high
        reclaimed = current_close <= orb_high and current_close <= vwap
        code = "RECENT_BULL_TRAP_REJECTION"
    else:
        raise ValueError("direction must be CALL or PUT.")

    breach_positions = np.flatnonzero(breach_mask.to_numpy())
    if len(breach_positions) == 0:
        return {
            "false_break": False,
            "bars_since_breach": None,
            "reason_code": "NO_RECENT_BREACH",
        }

    bars_since = int((len(recent) - 1) - breach_positions[-1])

    return {
        "false_break": bool(reclaimed and bars_since <= max_bars_since_breach),
        "bars_since_breach": bars_since,
        "reason_code": code if reclaimed else "BREACH_NOT_RECLAIMED",
    }


def detect_retest(
    recent_completed_bars: pd.DataFrame,
    direction: Direction,
    boundary: float,
    atr: float,
    *,
    tolerance_atr: float = 0.10,
) -> Dict[str, Any]:
    """Simple research retest detector."""
    if recent_completed_bars.empty:
        return {"retest_occurred": False, "retest_held": False}

    recent = _normalize_columns(recent_completed_bars)
    tol = max(float(atr), 0.0) * tolerance_atr

    if direction == "CALL":
        touched = recent["Low"].astype(float) <= boundary + tol
        held = recent["Close"].astype(float) >= boundary
    elif direction == "PUT":
        touched = recent["High"].astype(float) >= boundary - tol
        held = recent["Close"].astype(float) <= boundary
    else:
        raise ValueError("direction must be CALL or PUT.")

    qualifying = touched & held

    return {
        "retest_occurred": bool(touched.any()),
        "retest_held": bool(qualifying.any()),
        "bars_observed": int(len(recent)),
    }


# ============================================================
# Research-only setup labels
# ============================================================

def classify_setup_candidate(
    candle: pd.Series,
    orb_high: float,
    orb_low: float,
    vwap: float,
    ema20_slope: float,
    initial_r: float,
    *,
    recent_completed_bars: Optional[pd.DataFrame] = None,
    thresholds: ResearchThresholds = ResearchThresholds(),
) -> Dict[str, Any]:
    """
    Produces RESEARCH LABELS only.

    This function deliberately does NOT:
      - size positions
      - place orders
      - choose option contracts
      - set production stops/targets
      - claim thresholds are optimal
    """
    anatomy = compute_bar_anatomy(candle)
    spot = anatomy["close"]

    call_ext = compute_extension_r("CALL", spot, orb_high, orb_low, initial_r)
    put_ext = compute_extension_r("PUT", spot, orb_high, orb_low, initial_r)

    recent = (
        recent_completed_bars
        if recent_completed_bars is not None
        else pd.DataFrame([candle])
    )

    bear_trap = detect_recent_false_break(
        recent,
        "CALL",
        orb_high,
        orb_low,
        vwap,
        max_bars_since_breach=thresholds.trap_max_bars_since_breach,
    )
    bull_trap = detect_recent_false_break(
        recent,
        "PUT",
        orb_high,
        orb_low,
        vwap,
        max_bars_since_breach=thresholds.trap_max_bars_since_breach,
    )

    lower_wick_ok = (
        anatomy["lower_wick_pct"] >= thresholds.trap_wick_pct_min
        or anatomy["close_location"] >= thresholds.trap_close_location_mid
    )
    upper_wick_ok = (
        anatomy["upper_wick_pct"] >= thresholds.trap_wick_pct_min
        or anatomy["close_location"] <= (1.0 - thresholds.trap_close_location_mid)
    )

    if bear_trap["false_break"] and lower_wick_ok:
        return {
            "setup_type": "RESEARCH_BEAR_TRAP_RECLAIM",
            "direction": "CALL",
            "reason_code": "LOCAL_ORB_LOW_RECLAIM",
            "is_trap_candidate": True,
            "extension_r_signed": call_ext["extension_r_signed"],
            "extension_r_post_break": call_ext["extension_r_post_break"],
            "anatomy": anatomy,
            "trap_meta": bear_trap,
        }

    if bull_trap["false_break"] and upper_wick_ok:
        return {
            "setup_type": "RESEARCH_BULL_TRAP_REJECTION",
            "direction": "PUT",
            "reason_code": "LOCAL_ORB_HIGH_REJECTION",
            "is_trap_candidate": True,
            "extension_r_signed": put_ext["extension_r_signed"],
            "extension_r_post_break": put_ext["extension_r_post_break"],
            "anatomy": anatomy,
            "trap_meta": bull_trap,
        }

    clean_bull = (
        spot > orb_high
        and spot > vwap
        and ema20_slope > 0
        and anatomy["upper_wick_pct"] <= thresholds.clean_wick_pct_max
        and anatomy["clv"] >= thresholds.clean_clv_abs_min
        and anatomy["body_pct"] >= thresholds.clean_body_pct_min
    )

    clean_bear = (
        spot < orb_low
        and spot < vwap
        and ema20_slope < 0
        and anatomy["lower_wick_pct"] <= thresholds.clean_wick_pct_max
        and anatomy["clv"] <= -thresholds.clean_clv_abs_min
        and anatomy["body_pct"] >= thresholds.clean_body_pct_min
    )

    if clean_bull:
        extension = call_ext["extension_r_post_break"]
        return {
            "setup_type": "RESEARCH_CLEAN_BULL_BREAK",
            "direction": "CALL",
            "reason_code": (
                "EXTENSION_WARNING"
                if extension > thresholds.extension_warning_r
                else "CLEAN_BREAKOUT"
            ),
            "is_trap_candidate": False,
            "extension_r_signed": call_ext["extension_r_signed"],
            "extension_r_post_break": extension,
            "anatomy": anatomy,
        }

    if clean_bear:
        extension = put_ext["extension_r_post_break"]
        return {
            "setup_type": "RESEARCH_CLEAN_BEAR_BREAK",
            "direction": "PUT",
            "reason_code": (
                "EXTENSION_WARNING"
                if extension > thresholds.extension_warning_r
                else "CLEAN_BREAKDOWN"
            ),
            "is_trap_candidate": False,
            "extension_r_signed": put_ext["extension_r_signed"],
            "extension_r_post_break": extension,
            "anatomy": anatomy,
        }

    return {
        "setup_type": "IN_BALANCE_OR_UNCONFIRMED",
        "direction": "NONE",
        "reason_code": "NO_RESEARCH_SETUP",
        "is_trap_candidate": False,
        "extension_r_signed": 0.0,
        "extension_r_post_break": 0.0,
        "anatomy": anatomy,
    }


# ============================================================
# Serialization helper
# ============================================================

def to_dict(obj: Any) -> Dict[str, Any]:
    if hasattr(obj, "__dataclass_fields__"):
        return asdict(obj)
    if isinstance(obj, dict):
        return obj
    raise TypeError(f"Unsupported object type: {type(obj)}")
