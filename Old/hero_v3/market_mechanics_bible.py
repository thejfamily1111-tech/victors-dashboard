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
    _require_datetime_index(df)

    if df.index.tz is None:
        raise ValueError(
            "bars_df index is timezone-naive. Localize it at the data-source "
            "boundary before calling market mechanics."
        )

    out = _normalize_columns(df)
    out.index = out.index.tz_convert(ET)
    if out.index.has_duplicates:
        raise ValueError("DUPLICATE_BAR_TIMESTAMPS")
    values = out[["Open", "High", "Low", "Close"]].to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("NONFINITE_OHLC")
    if ((out["High"] < out[["Open", "Close", "Low"]].max(axis=1)) |
        (out["Low"] > out[["Open", "Close", "High"]].min(axis=1))).any():
        raise ValueError("INVALID_OHLC")
    return out.sort_index()


def _normalize_decision_ts(decision_ts: pd.Timestamp | str) -> pd.Timestamp:
    ts = pd.Timestamp(decision_ts)
    if ts.tzinfo is None:
        raise ValueError("decision_ts must be timezone-aware.")
    return ts.tz_convert(ET)


def infer_bar_minutes(df: pd.DataFrame) -> int:
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
# Opening Range
# ============================================================

def calculate_multi_orb(
    bars_df: pd.DataFrame,
    session_date: date,
    decision_ts: pd.Timestamp | str,
    atr: float,
    *,
    bar_label: BarLabel = "start",
) -> ORBState:
    df = _to_eastern(bars_df)
    decision = _normalize_decision_ts(decision_ts)

    bar_minutes = infer_bar_minutes(df)
    completed = _completed_bars(df, decision, bar_minutes, bar_label)
    if bar_label == "end":
        completed.index = completed.index - pd.Timedelta(minutes=bar_minutes)
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

    def complete_grid(w, count):
        grid = pd.date_range(lock_30_ts - pd.Timedelta(minutes=30), periods=count,
                             freq=f"{bar_minutes}min")
        return w.index.equals(grid)
    orb5_locked = decision >= lock_5_ts and complete_grid(w5, expected_5)
    orb15_locked = decision >= lock_15_ts and complete_grid(w15, expected_15)
    orb30_locked = decision >= lock_30_ts and complete_grid(w30, expected_30)

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


def compute_orb30_width_percentile(
    bars_df: pd.DataFrame,
    current_session_date: date,
    current_width: float,
    *,
    lookback_sessions: int = 40,
) -> Dict[str, float]:
    df = _to_eastern(bars_df)
    prior = df[df.index.date < current_session_date]
    unique_dates = sorted(set(prior.index.date))[-lookback_sessions:]

    widths = []
    for d in unique_dates:
        w = _session_slice(prior, d, "09:30", "10:00")
        interval = infer_bar_minutes(df)
        grid = pd.date_range(pd.Timestamp(f"{d} 09:30", tz=ET),
                             periods=30 // interval, freq=f"{interval}min")
        if not w.index.equals(grid):
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


def compute_bar_anatomy(candle: pd.Series) -> Dict[str, float]:
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
        "open": o, "high": h, "low": l, "close": c,
        "total_range": total_range, "body_pct": body_pct,
        "upper_wick_pct": upper_wick_pct, "lower_wick_pct": lower_wick_pct,
        "clv": clv, "close_location": close_location,
    }


def compute_extension_r(direction: Direction, spot: float, orb_high: float, orb_low: float, initial_r: float) -> Dict[str, float]:
    if initial_r <= 0:
        raise ValueError("initial_r must be > 0 and frozen at decision time.")
    if direction == "CALL":
        signed = (spot - orb_high) / initial_r
    elif direction == "PUT":
        signed = (orb_low - spot) / initial_r
    else:
        raise ValueError("direction must be CALL or PUT.")
    return {"extension_r_signed": float(signed), "extension_r_post_break": float(max(0.0, signed))}


def compute_effective_rr(direction: Direction, entry: float, stop: float, target: float) -> float:
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


def compute_same_clock_rvol(bars_df: pd.DataFrame, current_bar_ts: pd.Timestamp | str, *, lookback_sessions: int = 40) -> RVOLMetrics:
    df = _to_eastern(bars_df)
    if "Volume" not in df.columns:
        raise ValueError("Volume column is required for RVOL.")
    ts = _normalize_decision_ts(current_bar_ts)

    same_slot = df[(df.index.hour == ts.hour) & (df.index.minute == ts.minute) & (df.index.date < ts.date())].sort_index()
    same_slot = same_slot.groupby(same_slot.index.date).tail(1).tail(lookback_sessions)

    current_rows = df[df.index == ts]
    if current_rows.empty:
        raise ValueError(f"No current bar found at {ts.isoformat()}")

    current_volume = float(current_rows.iloc[-1]["Volume"])
    hist = same_slot["Volume"].astype(float).to_numpy()

    if len(hist) == 0:
        return RVOLMetrics(float("nan"), float("nan"), float("nan"), float("nan"), 0, ts.strftime("%H:%M"))

    mean = float(np.mean(hist))
    median = float(np.median(hist))
    std = float(np.std(hist, ddof=1)) if len(hist) > 1 else float("nan")

    return RVOLMetrics(
        ratio_mean=current_volume / mean if mean > 0 else float("nan"),
        ratio_median=current_volume / median if median > 0 else float("nan"),
        percentile=100.0 * float(np.mean(hist <= current_volume)),
        zscore=(current_volume - mean) / std if np.isfinite(std) and std > 0 else float("nan"),
        sample_size=len(hist),
        slot_time=ts.strftime("%H:%M"),
    )


def compute_breakout_attempt_state(bars_df: pd.DataFrame, session_date: date, decision_ts: pd.Timestamp | str, orb_high: float, orb_low: float, *, bar_label: BarLabel = "start") -> AttemptState:
    df = _to_eastern(bars_df)
    decision = _normalize_decision_ts(decision_ts)
    bar_minutes = infer_bar_minutes(df)
    completed = _completed_bars(df, decision, bar_minutes, bar_label)
    post_orb = _session_slice(completed, session_date, "10:00", "16:00")
    if post_orb.empty:
        return AttemptState(0, 0, "UNTESTED", "UNTESTED", None, None)

    closes = post_orb["Close"].astype(float)
    prev = closes.shift(1).fillna((orb_high + orb_low) / 2)
    bull_start = (closes > orb_high) & (prev <= orb_high)
    bear_start = (closes < orb_low) & (prev >= orb_low)
    bull_positions = np.flatnonzero(bull_start.fillna(False).to_numpy())
    bear_positions = np.flatnonzero(bear_start.fillna(False).to_numpy())

    return AttemptState(
        bullish_attempts=int(len(bull_positions)),
        bearish_attempts=int(len(bear_positions)),
        bullish_state="FIRST_BREAK" if len(bull_positions) == 1 else "REPEAT_BREAK" if len(bull_positions) > 1 else "UNTESTED",
        bearish_state="FIRST_BREAK" if len(bear_positions) == 1 else "REPEAT_BREAK" if len(bear_positions) > 1 else "UNTESTED",
        bars_since_last_bull_break=int(len(post_orb) - 1 - bull_positions[-1]) if len(bull_positions) else None,
        bars_since_last_bear_break=int(len(post_orb) - 1 - bear_positions[-1]) if len(bear_positions) else None,
    )


def to_dict(obj: Any) -> Dict[str, Any]:
    if hasattr(obj, "__dataclass_fields__"):
        return asdict(obj)
    if isinstance(obj, dict):
        return obj
    raise TypeError(f"Unsupported object type: {type(obj)}")


import hashlib

@dataclass(frozen=True)
class FadeConfig:
    acceptance_closes: int = 2
    failure_window_bars: int = 3
    confirmation_window_bars: int = 3
    stop_buffer_atr: float = 0.10
    retest_tolerance_atr: float = 0.10
    entry_mode: str = "B"
    target_model: str = "MIDPOINT"
    fixed_r: float = 1.0

    def __post_init__(self):
        if self.entry_mode not in {"A", "B", "C"}:
            raise ValueError("INVALID_ENTRY_MODE")
        if self.target_model not in {"VWAP", "MIDPOINT", "OPPOSITE", "FIXED_R"}:
            raise ValueError("INVALID_TARGET_MODEL")
        if min(self.acceptance_closes, self.failure_window_bars, self.confirmation_window_bars) < 1:
            raise ValueError("INVALID_BAR_THRESHOLD")


def stable_id(*parts) -> str:
    return hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:24]


def extension_bin(value):
    for upper, label in [(0.25,"0-0.25R"),(0.5,"0.25-0.50R"),(.75,"0.50-0.75R"),
                         (1,"0.75-1.00R"),(1.5,"1.00-1.50R"),(2,"1.50-2.00R")]:
        if value <= upper:
            return label
    return ">2.00R"


def new_fade_state(ticker, orb):
    return {"ticker": ticker, "session_date": orb.session_date, "orb": asdict(orb),
            "state": "IN_RANGE", "last_bar": None, "up_attempts": 0, "down_attempts": 0,
            "episode": None, "markers": []}


def advance_fade(state: dict, bar: pd.Series, bar_ts, decision_ts, atr: float,
                 vwap: float, config: FadeConfig) -> tuple[list, list]:
    ts, decision = _normalize_decision_ts(bar_ts), _normalize_decision_ts(decision_ts)
    end = ts + pd.Timedelta(minutes=5)
    if end > decision:
        raise ValueError("FORMING_BAR")
    if ts.minute % 5 or ts.second or ts.microsecond:
        raise ValueError("OFF_GRID_5M_BAR")
    orb = state["orb"]
    if not orb["orb30_locked"] or ts.strftime("%H:%M") < "10:00" or str(ts.date()) != state["session_date"]:
        return [], []
    if state["last_bar"] and ts <= pd.Timestamp(state["last_bar"]):
        return [], []
    events, candidates = [], []
    if state["last_bar"] and ts != pd.Timestamp(state["last_bar"]) + pd.Timedelta(minutes=5):
        state["episode"] = None
        state["state"] = "STALE"
        events.append({"state":"STALE", "reason_code":"MISSING_TACTICAL_BAR"})
        state["last_bar"] = ts.isoformat()
        return events, []
    state["last_bar"] = ts.isoformat()
    h,l,c = (float(bar[k]) for k in ("High","Low","Close"))
    oh,ol = orb["orb30_high"],orb["orb30_low"]
    inside = ol < c < oh
    ep = state["episode"]
    if h > oh and l < ol:
        state["episode"] = None
        state["state"] = "INVALIDATED"
        return [{"state":"INVALIDATED","reason_code":"DUAL_BOUNDARY_PATH_AMBIGUOUS",
                 "breach_id":stable_id(state["ticker"],ts,"DUAL")}], []
    if ep and ep.get("terminal"):
        state["state"] = ep["terminal"]
        if inside:
            state["episode"] = None
            state["state"] = "IN_RANGE"
        return events, []
    if ep is None:
        side = "UPSIDE" if h > oh else "DOWNSIDE" if l < ol else None
        if not side:
            if c < ol and c < vwap:
                state["state"] = "BEAR_IMBALANCE"
            elif c > oh and c > vwap:
                state["state"] = "BULL_IMBALANCE"
            else:
                state["state"] = "IN_RANGE"
            return events, []
        key = "up_attempts" if side == "UPSIDE" else "down_attempts"
        state[key] += 1
        ep = {"direction":side,"breach_timestamp":ts.isoformat(),
              "breach_id":stable_id(state["ticker"],ts,side),"attempt_number":state[key],
              "swing_high":h,"swing_low":l,"bars_since_breach":0,"bars_outside":0,
              "consecutive_outside":0,"emitted":[],"failure_timestamp":None,
              "breakout_breached":True,"acceptance_status":"TESTING","failure_status":"UNCONFIRMED",
              "attempt_label":"FIRST_BREAK" if state[key]==1 else "SECOND_BREAK" if state[key]==2 else "THIRD_PLUS_BREAK"}
        state["episode"] = ep
        state["markers"].append({"timestamp":ts.isoformat(),"price":h if side=="UPSIDE" else l,"kind":"BREACH"})
        events.append({**ep,"state":side+"_BREACH","reason_code":"BREACH_OBSERVED"})
    else:
        ep["bars_since_breach"] += 1
    upside = ep["direction"] == "UPSIDE"
    outside = c > oh if upside else c < ol
    if ep["failure_timestamp"] is None:
        ep["swing_high"] = max(ep["swing_high"],h)
        ep["swing_low"] = min(ep["swing_low"],l)
        ep["breach_depth"] = ep["swing_high"]-oh if upside else ol-ep["swing_low"]
        ep["maximum_extension"] = ep["breach_depth"]
        ep["breach_depth_atr"] = ep["breach_depth"]/atr
        ep["bars_outside"] += int(outside)
        ep["consecutive_outside"] = ep["consecutive_outside"]+1 if outside else 0
        ep["outside_close_minutes_proxy"] = ep["bars_outside"]*5
        if ep["consecutive_outside"] >= config.acceptance_closes:
            ep["acceptance_status"] = "ACCEPTED"
            ep["terminal"] = ep["direction"]+"_ACCEPTED"
            state["state"] = ep["terminal"]
            events.append({**ep,"state":state["state"],"reason_code":"SUSTAINED_ACCEPTANCE_NO_FADE"})
            return events, []
        if ep["bars_since_breach"] > config.failure_window_bars:
            ep["terminal"] = state["state"] = "STALE"
            events.append({**ep,"state":"STALE","reason_code":"FAILURE_WINDOW_EXPIRED"})
            return events, []
        if not inside:
            state["state"] = "TESTING_ACCEPTANCE"
            return events, []
        ep["failure_timestamp"] = end.isoformat()
        ep["failure_status"] = "CONFIRMED"
        ep["acceptance_status"] = "FAILED"
        ep["failed_attempt_label"] = "FAILED_"+ep["attempt_label"]
        ep["failure_close"] = c
        ep["failure_anatomy"] = compute_bar_anatomy(bar)
        ep["failure_bar_number"] = ep["bars_since_breach"]
        ep["stop"] = ep["swing_high"]+config.stop_buffer_atr*atr if upside else ep["swing_low"]-config.stop_buffer_atr*atr
        state["state"] = "FAILED_"+ep["direction"]+"_ACCEPTANCE"
        state["markers"].append({"timestamp":ts.isoformat(),"price":c,"kind":"FAILED_ACCEPTANCE"})
        events.append({**ep,"state":state["state"],"reason_code":"COMPLETED_CLOSE_INSIDE"})
    age = ep["bars_since_breach"]-ep["failure_bar_number"]
    if age > 0 and ((h >= ep["stop"] if upside else l <= ep["stop"]) or not inside):
        ep["terminal"] = state["state"] = "INVALIDATED"
        events.append({**ep,"state":"INVALIDATED","reason_code":"FAILURE_INVALIDATED"})
        return events, []
    if age > config.confirmation_window_bars:
        ep["terminal"] = state["state"] = "STALE"
        events.append({**ep,"state":"STALE","reason_code":"CONFIRMATION_EXPIRED"})
        return events, []
    for mode in ("A","B","C"):
        qualify = (mode=="A" and age==0) or (mode=="B" and age==1 and (c < ep["failure_close"] if upside else c > ep["failure_close"])) or (
            mode=="C" and age>0 and (h >= oh-config.retest_tolerance_atr*atr if upside else l <= ol+config.retest_tolerance_atr*atr))
        if not qualify or mode in ep["emitted"]:
            continue
        ep["emitted"].append(mode)
        sign = -1 if upside else 1
        r = abs(c-ep["stop"])
        if r <= 0:
            continue
        targets = {"VWAP":vwap,"MIDPOINT":orb["orb30_mid"],"OPPOSITE":ol if upside else oh,
                   "FIXED_R":c+sign*config.fixed_r*r,"PLUS_1R":c+sign*r,"PLUS_2R":c+sign*2*r}
        target = targets[config.target_model]
        sid = stable_id(ep["breach_id"],mode,"FADE_V3")
        candidates.append({"strategy_version":"HERO_FADE_CHALLENGER","hero_version":"3.0.0",
            "ticker":state["ticker"],"breach_id":ep["breach_id"],"setup_id":sid,
            "signal_id":stable_id(sid,end),"decision_ts":end.isoformat(),"mode":mode,
            "direction":"PUT" if upside else "CALL","setup_type":"FAILED_"+ep["direction"]+"_ACCEPTANCE",
            "entry_spot":c,"stop":ep["stop"],"initial_r":r,"target":target,"targets":targets,
            "target_model":config.target_model,"target_valid":sign*(target-c)>0,
            "extension_r":ep["breach_depth"]/r,"extension_bin":extension_bin(ep["breach_depth"]/r),
            "effective_rr":sign*(target-c)/r,"breach":dict(ep),"config":asdict(config)})
    if candidates:
        state["state"] = "FADE_CANDIDATE"
    elif age>0:
        state["state"] = "RETEST" if config.entry_mode=="C" else "FAILED_"+ep["direction"]+"_ACCEPTANCE"
    return events, candidates


def momentum_baseline(ticker, bar, ts, orb, atr, vwap, slope):
    c = float(bar["Close"])
    sign = 1 if c>orb.orb30_high and c>vwap and slope>0 else -1 if c<orb.orb30_low and c<vwap and slope<0 else 0
    if not sign:
        return None
    sid = stable_id(ticker,ts,"MOMENTUM_BASELINE")
    ext = max(0,(c-orb.orb30_high)/atr if sign==1 else (orb.orb30_low-c)/atr)
    return {"strategy_version":"HERO_MOMENTUM_BASELINE","hero_version":"3.0.0",
            "ticker":ticker,"setup_id":sid,"signal_id":sid,"breach_id":None,"mode":"BASELINE",
            "decision_ts":(pd.Timestamp(ts)+pd.Timedelta(minutes=5)).isoformat(),
            "direction":"CALL" if sign==1 else "PUT","entry_spot":c,"stop":c-sign*atr,
            "initial_r":atr,"target":c+sign*2*atr,"target_model":"PLUS_2R",
            "targets":{"PLUS_1R":c+sign*atr,"PLUS_2R":c+sign*2*atr},"extension_r":ext,
            "extension_bin":extension_bin(ext),"target_valid":True,
            "baseline_scope":"RAW_ENTRY_ONLY_LEGACY_GATES_NOT_REPLAYED"}


def completed_features(raw5, raw15, decision_ts, locked_orb=None):
    decision = _normalize_decision_ts(decision_ts)
    df5,df15 = _to_eastern(raw5),_to_eastern(raw15)
    c5 = _completed_bars(df5,decision,5,"start")
    c15 = _completed_bars(df15,decision,15,"start")
    today = _session_slice(c5,decision.date(),"09:30","16:00")
    if today.empty or len(c15)<25:
        raise ValueError("INSUFFICIENT_BARS")
    ts = today.index[-1]
    age = (decision-ts-pd.Timedelta(minutes=5)).total_seconds()
    age15 = (decision-c15.index[-1]-pd.Timedelta(minutes=15)).total_seconds()
    if not 0 <= age <= 180 or not 0 <= age15 <= 1080:
        raise ValueError("STALE_UNDERLYING_DATA")
    tr = pd.concat([c15.High-c15.Low,(c15.High-c15.Close.shift()).abs(),(c15.Low-c15.Close.shift()).abs()],axis=1).max(axis=1)
    atr = float(tr.rolling(14).mean().iloc[-1])
    ema = c15.Close.ewm(span=20,adjust=False).mean()
    if not np.isfinite(atr) or atr<=0:
        raise ValueError("INVALID_ATR")
    orb = ORBState(**locked_orb) if locked_orb else calculate_multi_orb(df5,decision.date(),decision,atr)
    if not orb.orb30_locked or orb.source_bar_minutes!=5:
        raise ValueError("ORB30_NOT_LOCKED")
    today=today.copy()
    today["VWAP"]=((today.High+today.Low+today.Close)/3*today.Volume).cumsum()/today.Volume.cumsum().replace(0,np.nan)
    vwap=float(today.VWAP.iloc[-1])
    if not np.isfinite(vwap):
        raise ValueError("INVALID_VWAP")
    rv=compute_same_clock_rvol(df5,ts)
    width=compute_orb30_width_percentile(df5,decision.date(),orb.orb30_width_dollars)
    return {"decision_ts":decision.isoformat(),"latest_5m_ts":ts.isoformat(),"orb":asdict(orb),
            "close":float(today.Close.iloc[-1]),"vwap":vwap,"atr_15m":atr,
            "ema20_15m":float(ema.iloc[-1]),"ema20_slope_15m":float(ema.iloc[-1]-ema.iloc[-2]),
            "rvol":asdict(rv),"orb_width_context":width,
            "anatomy":compute_bar_anatomy(today.iloc[-1]),"five_min_age_seconds":age,
            "fifteen_min_age_seconds":age15,"vwap_distance":float(today.Close.iloc[-1])-vwap,
            "rs_market":None,"rs_sector":None,
            "chart":[{"timestamp":i.isoformat(),**{k:float(row[k]) for k in ["Open","High","Low","Close","Volume","VWAP"]}} for i,row in today.iterrows()]}