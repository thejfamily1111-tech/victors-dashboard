"""
market_barometer.py - Institutional Macro Risk, Regime & Confluence Engine
Supervised by VIC AI Gatekeeper & Quantitative Factor Auditor
"""

from datetime import datetime, timedelta
import math
import os
import time
from typing import Tuple
import numpy as np
import pandas as pd
import yfinance as yf

# -------------------------------------------------------------
# 0. VIC GOVERNOR OPERATING MODE
# -------------------------------------------------------------
# "SHADOW": Log verdict and telemetry, do NOT block HERO execution.
# "ENFORCE": Macro verdicts actively control execution and scaling.
# Environment variable override with default to ENFORCE
_env_vic = os.getenv("VIC_MODE", "ENFORCE").upper()
VIC_MODE = "ENFORCE" if _env_vic in {"ACTIVE", "ENFORCE"} else "SHADOW"

# Deterministic Relative Strength Mapping:
# Eliminates self-comparison bugs for index and sector ETFs.
TICKER_SECTOR_MAP = {
    "SPY": "QQQ",      # SPY benchmarks vs QQQ (Broad Market vs Tech Growth)
    "QQQ": "SPY",      # QQQ benchmarks vs SPY (Tech Outperformance vs Broad Market)
    "SMH": "QQQ",      # SMH benchmarks vs QQQ (Semis vs Tech)
    "NVDA": "SMH",     # Semis benchmark vs SMH
    "AMD": "SMH",
    "MSFT": "QQQ",     # Mega-cap Tech benchmarks vs QQQ
    "AAPL": "QQQ",
    "AMZN": "QQQ",
    "META": "QQQ",
    "TSLA": "QQQ",
    "COIN": "QQQ",
}

# -------------------------------------------------------------
# 1. Bar-Aware Completed Candle Cache
# -------------------------------------------------------------
HTF_BAR_CACHE = {}


def fetch_completed_htf_bars(
    ticker: str,
) -> tuple[pd.DataFrame, pd.DataFrame, str, str]:
    """Fetches and caches completed 1H and 4H bars (excluding currently forming candle)."""
    now_ts = time.time()
    cached = HTF_BAR_CACHE.get(ticker)

    # 3-minute in-memory cache TTL
    if cached and (now_ts - cached.get("fetched_at", 0) < 180):
        return (
            cached["data_1h"],
            cached["data_4h"],
            cached["last_1h_bar"],
            cached["last_4h_bar"],
        )

    try:
        raw_1h = yf.download(
            ticker, period="14d", interval="1h", progress=False, auto_adjust=True
        )
        if isinstance(raw_1h.columns, pd.MultiIndex):
            raw_1h.columns = raw_1h.columns.get_level_values(0)

        if raw_1h.empty or len(raw_1h) < 25:
            return pd.DataFrame(), pd.DataFrame(), "", ""

        # Discard unclosed, actively forming 1H bar
        df_1h = raw_1h.iloc[:-1].copy()

        df_1h["EMA20"] = df_1h["Close"].ewm(span=20, adjust=False).mean()
        tr1 = df_1h["High"] - df_1h["Low"]
        tr2 = (df_1h["High"] - df_1h["Close"].shift(1)).abs()
        tr3 = (df_1h["Low"] - df_1h["Close"].shift(1)).abs()
        df_1h["ATR14"] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1).rolling(14).mean()

        # Synthesize completed 4H bars from completed 1H bars
        df_4h = (
            df_1h.resample("4h")
            .agg({
                "Open": "first",
                "High": "max",
                "Low": "min",
                "Close": "last",
                "Volume": "sum",
            })
            .dropna()
        )

        if not df_4h.empty and len(df_4h) >= 5:
            df_4h["EMA20"] = df_4h["Close"].ewm(span=20, adjust=False).mean()
            last_4h_str = df_4h.index[-1].strftime("%Y-%m-%d %H:%M")
        else:
            last_4h_str = "N/A"

        last_1h_str = df_1h.index[-1].strftime("%Y-%m-%d %H:%M")

        HTF_BAR_CACHE[ticker] = {
            "data_1h": df_1h,
            "data_4h": df_4h,
            "last_1h_bar": last_1h_str,
            "last_4h_bar": last_4h_str,
            "fetched_at": now_ts,
        }
        return df_1h, df_4h, last_1h_str, last_4h_str

    except Exception:
        return pd.DataFrame(), pd.DataFrame(), "", ""


def find_swing_pivot_zones(df_4h: pd.DataFrame) -> tuple[list, list]:
    """Identifies confirmed 5-bar swing high resistance and swing low support zones."""
    swing_highs = []
    swing_lows = []

    if len(df_4h) < 7:
        return swing_highs, swing_lows

    highs = df_4h["High"].values
    lows = df_4h["Low"].values

    for i in range(2, len(df_4h) - 2):
        if (
            highs[i] > highs[i - 1]
            and highs[i] > highs[i - 2]
            and highs[i] > highs[i + 1]
            and highs[i] > highs[i + 2]
        ):
            swing_highs.append(float(highs[i]))

        if (
            lows[i] < lows[i - 1]
            and lows[i] < lows[i - 2]
            and lows[i] < lows[i + 1]
            and lows[i] < lows[i + 2]
        ):
            swing_lows.append(float(lows[i]))

    return swing_highs, swing_lows


# -------------------------------------------------------------
# 2. VIC AI Macro Risk Clearance Engine (The Governor)
# -------------------------------------------------------------
def evaluate_macro_clearance(
    ticker: str,
    direction: str,
    spot_price: float,
    stop_price: float,
    target_price: float,
) -> dict:
    """
    Audits 1H and 4H structural trend and obstacle runway.
    Fails closed on missing data. Measures obstacles strictly in R-multiples.
    """
    df_1h, df_4h, ts_1h, ts_4h = fetch_completed_htf_bars(ticker)

    if df_1h.empty or len(df_1h) < 15:
        return {
            "verdict": "VETO",
            "sizing_scalar": 0.0,
            "mode": VIC_MODE,
            "reason_code": "DATA_STALE_OR_MISSING",
            "reason": "Completed HTF bar data unavailable (Fail Closed).",
            "trend_1h": "UNKNOWN",
            "structure_4h": "UNKNOWN",
            "obstacle_distance_r": 0.0,
            "data_timestamp_1h": ts_1h,
            "data_timestamp_4h": ts_4h,
        }

    is_call = direction.upper() == "CALL"
    r_unit = max(abs(spot_price - stop_price), 0.25)

    c_1h = float(df_1h["Close"].iloc[-1])
    ema_1h = float(df_1h["EMA20"].iloc[-1])
    atr_1h = (
        float(df_1h["ATR14"].iloc[-1])
        if not pd.isna(df_1h["ATR14"].iloc[-1])
        else 1.0
    )
    ema_slope_3bar = float(df_1h["EMA20"].iloc[-1] - df_1h["EMA20"].iloc[-3])

    ema_buffer = 0.20 * atr_1h
    ema_dist_atr = (c_1h - ema_1h) / atr_1h

    swing_highs, swing_lows = find_swing_pivot_zones(df_4h)
    nearest_obstacle = None
    obstacle_dist_r = 999.0

    if is_call:
        overhead_walls = [h for h in swing_highs if h > spot_price]
        if overhead_walls:
            nearest_obstacle = min(overhead_walls)
            obstacle_dist_r = (nearest_obstacle - spot_price) / r_unit
    else:
        underfoot_floors = [l for l in swing_lows if l < spot_price]
        if underfoot_floors:
            nearest_obstacle = max(underfoot_floors)
            obstacle_dist_r = (spot_price - nearest_obstacle) / r_unit

    # 1. Check 1H Trend Alignment
    if is_call:
        if c_1h < (ema_1h - ema_buffer) and ema_slope_3bar < 0:
            verdict = "VETO"
            scalar = 0.0
            code = "1H_STRONG_BEAR_TREND"
            reason = f"Price (${c_1h:.2f}) < 1H EMA20 - 0.2ATR with negative slope ({ema_slope_3bar:+.2f})"
        elif c_1h < ema_1h or ema_slope_3bar < 0:
            verdict = "DOWNGRADE"
            scalar = 0.5
            code = "1H_CHOP_MARGINAL"
            reason = "1H EMA20 flat or minor counter-trend drift"
        else:
            verdict = "PERMIT"
            scalar = 1.0
            code = "1H_TREND_ALIGNED"
            reason = "1H price > EMA20 with positive slope"
    else:
        if c_1h > (ema_1h + ema_buffer) and ema_slope_3bar > 0:
            verdict = "VETO"
            scalar = 0.0
            code = "1H_STRONG_BULL_TREND"
            reason = f"Price (${c_1h:.2f}) > 1H EMA20 + 0.2ATR with positive slope ({ema_slope_3bar:+.2f})"
        elif c_1h > ema_1h or ema_slope_3bar > 0:
            verdict = "DOWNGRADE"
            scalar = 0.5
            code = "1H_CHOP_MARGINAL"
            reason = "1H EMA20 flat or minor bullish drift"
        else:
            verdict = "PERMIT"
            scalar = 1.0
            code = "1H_TREND_ALIGNED"
            reason = "1H price < EMA20 with negative slope"

    # 2. Check 4H Obstacle Runway
    if obstacle_dist_r < 1.0:
        verdict = "VETO"
        scalar = 0.0
        code = "4H_OBSTACLE_WITHIN_1R"
        reason = f"4H pivot wall at ${nearest_obstacle:.2f} is only {obstacle_dist_r:.2f}R away (< 1.0R)"
    elif obstacle_dist_r < 2.0 and verdict != "VETO":
        verdict = "DOWNGRADE"
        scalar = min(scalar, 0.5)
        code = "4H_OBSTACLE_INSIDE_2R"
        reason = f"4H obstacle at ${nearest_obstacle:.2f} sits at {obstacle_dist_r:.2f}R (blocks clear +2R target)"

    return {
        "verdict": verdict,
        "sizing_scalar": scalar,
        "mode": VIC_MODE,
        "reason_code": code,
        "reason": reason,
        "trend_1h": "BULLISH" if c_1h >= ema_1h else "BEARISH",
        "ema_distance_atr_1h": round(ema_dist_atr, 2),
        "structure_4h": "BULLISH" if is_call else "BEARISH",
        "nearest_obstacle": nearest_obstacle,
        "obstacle_distance_r": round(obstacle_dist_r, 2),
        "data_timestamp_1h": ts_1h,
        "data_timestamp_4h": ts_4h,
    }


# -------------------------------------------------------------
# 3. Market Regime & Volatility Calculations
# -------------------------------------------------------------
def get_market_regime() -> dict:
    """Evaluates CBOE Volatility (^VIX) and returns a granular regime classification."""
    try:
        vix = yf.Ticker("^VIX")
        hist = vix.history(period="5d")
        current_vix = float(hist["Close"].iloc[-1]) if not hist.empty else 16.5
        prev_vix = float(hist["Close"].iloc[-2]) if len(hist) > 1 else current_vix
        vix_pct_change = (
            ((current_vix - prev_vix) / prev_vix * 100.0) if prev_vix > 0 else 0.0
        )

        if current_vix < 14.0:
            regime = "LOW VOLATILITY"
            note = "Complacent / Slow Grind"
            color = "#00bc8c"
        elif 14.0 <= current_vix <= 19.0:
            regime = "NORMAL VOLATILITY"
            note = "Favorable Institutional ORB Conditions"
            color = "#2ecc71"
        elif 19.0 < current_vix <= 25.0:
            regime = "ELEVATED VOLATILITY"
            note = "Wide Ranges / Strict ATR Sizing Advised"
            color = "#f39c12"
        elif 25.0 < current_vix <= 32.0:
            regime = "HIGH VOL TRENDING" if abs(vix_pct_change) < 5.0 else "HIGH VOL CHOP"
            note = "High Velocity / Strict Invalidation Targets"
            color = "#e67e22"
        else:
            regime = "EXTREME / EVENT SHOCK"
            note = "Capital Preservation Priority"
            color = "#e74c3c"

        return {
            "vix": current_vix,
            "vix_change": vix_pct_change,
            "regime": regime,
            "note": note,
            "badge_color": color,
        }
    except Exception:
        return {
            "vix": 16.5,
            "vix_change": 0.0,
            "regime": "NORMAL VOLATILITY",
            "note": "Default Baseline",
            "badge_color": "#2ecc71",
        }


def get_trend_structure(ticker: str) -> dict:
    """Grades daily EMA20 and intraday session VWAP alignment into a 0-100 score."""
    try:
        df_daily = yf.download(ticker, period="60d", interval="1d", progress=False)
        if isinstance(df_daily.columns, pd.MultiIndex):
            df_daily.columns = df_daily.columns.get_level_values(0)

        close_d = float(df_daily["Close"].iloc[-1])
        ema20_d = float(df_daily["Close"].ewm(span=20, adjust=False).mean().iloc[-1])
        daily_trend = 100.0 if close_d > ema20_d else 25.0

        df_intra = yf.download(ticker, period="5d", interval="15m", progress=False)
        if isinstance(df_intra.columns, pd.MultiIndex):
            df_intra.columns = df_intra.columns.get_level_values(0)

        # Isolated intraday session VWAP (reset per date)
        df_intra["date"] = df_intra.index.date
        today_date = df_intra["date"].iloc[-1]
        df_today = df_intra[df_intra["date"] == today_date].copy()

        if not df_today.empty:
            typical_price = (df_today["High"] + df_today["Low"] + df_today["Close"]) / 3.0
            cum_vol = df_today["Volume"].astype(float).cumsum()
            cum_pv = (typical_price * df_today["Volume"].astype(float)).cumsum()
            df_today["vwap"] = cum_pv / cum_vol.replace(0, np.nan)
            spot = float(df_today["Close"].iloc[-1])
            vwap = float(df_today["vwap"].iloc[-1]) if not np.isnan(df_today["vwap"].iloc[-1]) else spot
        else:
            spot = close_d
            vwap = close_d

        intra_score = 100.0 if spot > vwap else 20.0
        composite = (daily_trend * 0.5) + (intra_score * 0.5)

        return {
            "score": composite,
            "spot": spot,
            "vwap": vwap,
            "ema20_daily": ema20_d,
        }
    except Exception:
        return {"score": 50.0, "spot": 0.0, "vwap": 0.0, "ema20_daily": 0.0}


def calculate_relative_strength(
    ticker: str, lookback_minutes: int = 30
) -> dict:
    """
    Calculates Stock vs Market (SPY) and Stock vs Sector ETF Relative Strength.
    """
    sector_etf = TICKER_SECTOR_MAP.get(ticker, "SPY")
    tickers_to_pull = list(set([ticker, "SPY", "QQQ", sector_etf]))

    try:
        raw = yf.download(
            tickers_to_pull, period="2d", interval="15m", progress=False
        )
        if raw.empty:
            raise ValueError("No data returned")

        # Safely extract Close series for all downloaded symbols
        if isinstance(raw.columns, pd.MultiIndex):
            close_df = raw["Close"]
        else:
            close_df = raw[["Close"]]

        periods = max(int(lookback_minutes / 15), 1)

        def _calc_ret(sym: str) -> float:
            if sym not in close_df.columns:
                return 0.0
            s = close_df[sym].dropna()
            if len(s) < periods + 1:
                return 0.0
            p_now = float(s.iloc[-1])
            p_prev = float(s.iloc[-1 - periods])
            return ((p_now - p_prev) / p_prev) * 100.0 if p_prev > 0 else 0.0

        r_stock = _calc_ret(ticker)
        r_spy = _calc_ret("SPY")
        r_sec = _calc_ret(sector_etf)

        rs_market = r_stock - r_spy
        rs_sector = r_stock - r_sec

        return {
            "sector_etf": sector_etf,
            "stock_return_pct": round(r_stock, 2),
            "spy_return_pct": round(r_spy, 2),
            "sector_return_pct": round(r_sec, 2),
            "rs_market": round(rs_market, 2),
            "rs_sector": round(rs_sector, 2),
        }
    except Exception:
        return {
            "sector_etf": sector_etf,
            "stock_return_pct": 0.0,
            "spy_return_pct": 0.0,
            "sector_return_pct": 0.0,
            "rs_market": 0.0,
            "rs_sector": 0.0,
        }


def compute_market_regime_score(ticker: str) -> dict:
    """Calculates composite market regime score (0-100)."""
    sector_etf = TICKER_SECTOR_MAP.get(ticker, "SPY")

    spy_data = get_trend_structure("SPY")
    qqq_data = get_trend_structure("QQQ")
    sector_data = get_trend_structure(sector_etf)
    vix_data = get_market_regime()
    rs_data = calculate_relative_strength(ticker)

    v_score = (
        85.0
        if "NORMAL" in vix_data["regime"] or "TRENDING" in vix_data["regime"]
        else 40.0
    )
    rs_contrib = 50.0 + min(max(rs_data["rs_sector"] * 15.0, -50.0), 50.0)

    regime_score = (
        (spy_data["score"] * 0.20)
        + (qqq_data["score"] * 0.20)
        + (sector_data["score"] * 0.25)
        + (v_score * 0.15)
        + (rs_contrib * 0.20)
    )

    return {
        "regime_score": round(regime_score, 1),
        "spy_score": spy_data["score"],
        "qqq_score": qqq_data["score"],
        "sector_etf": sector_etf,
        "sector_score": sector_data["score"],
        "volatility_regime": vix_data["regime"],
        "rs_market": rs_data["rs_market"],
        "rs_sector": rs_data["rs_sector"],
    }


def get_orb_readiness_matrix() -> pd.DataFrame:
    """Scans active universe and presents 15m breakout momentum matrix."""
    universe = [
        "SPY", "QQQ", "SMH", "NVDA", "AMD", 
        "MSFT", "AAPL", "AMZN", "COIN", "META", "TSLA"
    ]
    rows = []
    for t in universe:
        reg = compute_market_regime_score(t)
        status = (
            "READY (HIGH CONFLUENCE)"
            if reg["regime_score"] >= 75
            else (
                "MONITORING"
                if reg["regime_score"] >= 50
                else "DEFENSIVE / COUNTER"
            )
        )
        rows.append({
            "Ticker": t,
            "Sector": reg["sector_etf"],
            "Regime Score": f"{reg['regime_score']}/100",
            "RS vs Market": f"{reg['rs_market']:+.2f}%",
            "RS vs Sector": f"{reg['rs_sector']:+.2f}%",
            "Vol State": reg["volatility_regime"],
            "Execution Gate": status,
        })
    return pd.DataFrame(rows)