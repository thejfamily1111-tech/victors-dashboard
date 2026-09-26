"""
alpha_engine.py - Quantitative Institutional Alpha Scoring Engine (0-100)
Embeds Wyckoff Liquidity Trap Detection & Brooks Price Action Analysis
Powered by Market Mechanics Bible V2 (Clean Multi-ORB, Bar Anatomy & Attempt States)
"""

from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd
from safe_yf import safe_download

import market_barometer as mb
import rvol_engine as re

try:
    import market_mechanics_bible as mmb
except ImportError:
    mmb = None

EASTERN_TZ = ZoneInfo("America/New_York")


def evaluate_institutional_candle(
    candle: pd.Series, 
    orb_high: float, 
    orb_low: float, 
    vwap: float, 
    ema_slope: float,
    atr: float,
    recent_bars: pd.DataFrame | None = None
) -> dict:
    """
    Evaluates candle anatomy and research setups using Market Mechanics Bible V2.
    """
    # 1. Bar anatomy extraction (Al Brooks Price Action)
    if mmb is not None and hasattr(mmb, "compute_bar_anatomy"):
        anatomy = mmb.compute_bar_anatomy(candle)
    else:
        c_open = float(candle["Open"])
        c_high = float(candle["High"])
        c_low = float(candle["Low"])
        c_close = float(candle["Close"])
        total_range = max(c_high - c_low, 0.001)
        anatomy = {
            "body_pct": abs(c_close - c_open) / total_range * 100.0,
            "upper_wick_pct": (c_high - max(c_open, c_close)) / total_range * 100.0,
            "lower_wick_pct": (min(c_open, c_close) - c_low) / total_range * 100.0,
            "clv": ((c_close - c_low) - (c_high - c_close)) / total_range,
            "close_location": (c_close - c_low) / total_range,
        }

    clv = float(anatomy["clv"])
    body_pct = float(anatomy["body_pct"])
    upper_wick = float(anatomy["upper_wick_pct"])
    lower_wick = float(anatomy["lower_wick_pct"])
    close_loc = float(anatomy["close_location"])

    # 2. Pattern Classification
    setup_type = "IN_BALANCE"
    direction = "NONE"
    is_trap = False

    if mmb is not None and hasattr(mmb, "classify_setup_candidate"):
        setup = mmb.classify_setup_candidate(
            candle=candle,
            orb_high=orb_high,
            orb_low=orb_low,
            vwap=vwap,
            ema20_slope=ema_slope,
            initial_r=atr,
            recent_completed_bars=recent_bars,
        )
        setup_type = setup.get("setup_type", "IN_BALANCE_OR_UNCONFIRMED").replace("RESEARCH_", "")
        direction = setup.get("direction", "NONE")
        is_trap = setup.get("is_trap_candidate", False)
    else:
        spot = float(candle["Close"])
        if spot > orb_high and spot > vwap:
            setup_type = "CLEAN_BULL_BREAK"
            direction = "CALL"
        elif spot < orb_low and spot < vwap:
            setup_type = "CLEAN_BEAR_BREAK"
            direction = "PUT"

    # 3. Dynamic Price Action Scoring (Max 20 pts)
    if "BULL_BREAK" in setup_type or "BEAR_BREAK" in setup_type:
        score = 20.0
    elif is_trap or "TRAP" in setup_type:
        score = 18.0
    else:
        # In Balance: Score 8 to 14 points based on CLV directional bias and absorption wicks
        base_balance = 8.0
        directional_bonus = abs(clv) * 4.0
        wick_bonus = 2.0 if (lower_wick > 20.0 or upper_wick > 20.0) else 0.0
        score = min(14.0, base_balance + directional_bonus + wick_bonus)

    return {
        "score": round(score, 1),
        "pattern": setup_type,
        "direction": direction,
        "is_trap": is_trap,
        "body_pct": round(body_pct, 1),
        "upper_wick_pct": round(upper_wick, 1),
        "lower_wick_pct": round(lower_wick, 1),
        "clv": round(clv, 2),
        "close_location": round(close_loc, 2),
    }


def compute_alpha_score(ticker: str) -> dict:
    """Calculates the Hero Alpha Score (0–100) using 5m institutional bars and clean mechanics."""
    try:
        # 1. Pull 5m intraday data (aligned with Clean V2 engine)
        df = safe_download(ticker, period="5d", interval="5m")
        if df is None or df.empty or len(df) < 25:
            return {"alpha_score": 50.0, "status": "INSUFFICIENT_DATA"}

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC").tz_convert(EASTERN_TZ)
        else:
            df.index = df.index.tz_convert(EASTERN_TZ)

        df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()
        high_low = df["High"] - df["Low"]
        high_cp = np.abs(df["High"] - df["Close"].shift())
        low_cp = np.abs(df["Low"] - df["Close"].shift())
        df["TR"] = np.maximum(high_low, np.maximum(high_cp, low_cp))
        df["ATR"] = df["TR"].rolling(window=14).mean()

        # Intraday VWAP
        today_date = df.index[-1].date()
        df_today = df[df.index.date == today_date].copy()
        if len(df_today) < 2:
            return {"alpha_score": 50.0, "status": "SESSION_INITIALIZING"}

        cum_vol = df_today["Volume"].cumsum()
        cum_vp = ((df_today["High"] + df_today["Low"] + df_today["Close"]) / 3.0 * df_today["Volume"]).cumsum()
        df_today["VWAP"] = cum_vp / np.where(cum_vol == 0, 1, cum_vol)

        last_candle = df_today.iloc[-1]
        spot = float(last_candle["Close"])
        vwap = float(last_candle["VWAP"])
        ema20 = float(last_candle["EMA20"])
        ema_prev = float(df_today["EMA20"].iloc[-2])
        ema_slope = ema20 - ema_prev
        atr = float(last_candle["ATR"]) if not np.isnan(last_candle["ATR"]) else 1.0

        # Multi-ORB bounds
        if mmb is not None and hasattr(mmb, "calculate_multi_orb"):
            multi_orb = mmb.calculate_multi_orb(
                bars_df=df_today,
                session_date=today_date,
                decision_ts=df_today.index[-1],
                atr=atr,
                bar_label="start",
            )
            orb_high = float(multi_orb.orb30_high) if multi_orb.orb30_locked else float(multi_orb.orb5_high)
            orb_low = float(multi_orb.orb30_low) if multi_orb.orb30_locked else float(multi_orb.orb5_low)
        else:
            orb_bars = df_today.iloc[:6]
            orb_high = float(orb_bars["High"].max())
            orb_low = float(orb_bars["Low"].min())

        session_high = float(df_today["High"].max())
        session_low = float(df_today["Low"].min())
        is_etf = ticker in ["SPY", "QQQ", "SMH"]

        # Component A: Institutional Candle & Trap Quality (20 pts max)
        candle_metrics = evaluate_institutional_candle(
            candle=last_candle,
            orb_high=orb_high,
            orb_low=orb_low,
            vwap=vwap,
            ema_slope=ema_slope,
            atr=atr,
            recent_bars=df_today.tail(4),
        )
        breakout_pts = candle_metrics["score"]

        # Component B: Time-of-Day RVOL (25 pts max)
        rvol_data = re.get_time_adjusted_rvol(ticker, df=df_today)
        pctile = rvol_data.get("percentile", 50.0)
        if pctile >= 90.0:
            rvol_pts = 25.0
        elif pctile >= 75.0:
            rvol_pts = 20.0
        elif pctile >= 60.0:
            rvol_pts = 15.0
        elif pctile >= 40.0:
            rvol_pts = 10.0
        else:
            rvol_pts = 5.0

        # Component C: Relative Strength vs Sector (0 for ETFs, 8 max for stocks)
        if is_etf:
            rs_pts = 0.0
            rs_sec = 0.0
        else:
            rs_data = mb.calculate_relative_strength(ticker, lookback_minutes=30)
            rs_sec = rs_data.get("rs_sector", 0.0)
            if rs_sec >= 1.0:
                rs_pts = 8.0
            elif rs_sec >= 0.0:
                rs_pts = 6.5
            elif rs_sec >= -0.75:
                rs_pts = 5.0
            else:
                rs_pts = 2.0

        # Component D: VWAP Alignment & Acceptance (25 pts for ETFs, 17 pts for Stocks)
        vwap_dist_pct = abs((spot - vwap) / vwap * 100.0) if vwap > 0 else 0.0
        if is_etf:
            if vwap_dist_pct >= 0.05:
                vwap_pts = 25.0 if vwap_dist_pct <= 1.5 else 18.0
            else:
                vwap_pts = 12.0
        else:
            if vwap_dist_pct >= 0.10:
                vwap_pts = 17.0 if vwap_dist_pct <= 1.5 else 12.0
            else:
                vwap_pts = 8.0

        # Component E: Market Regime Confluence (15 pts max)
        reg_data = mb.compute_market_regime_score(ticker)
        reg_score = reg_data.get("regime_score", 50.0)
        regime_pts = (reg_score / 100.0) * 15.0

        # Component F: EMA20 Slope Directionality (10 pts max)
        abs_slope = abs(ema_slope)
        if abs_slope > 0.05:
            ema_pts = 10.0
        elif abs_slope > 0.01:
            ema_pts = 7.0
        else:
            ema_pts = 3.0

        # Component G: Consolidation Compression (5 pts max)
        recent_ranges = (df_today["High"].iloc[-5:] - df_today["Low"].iloc[-5:]) / max(atr, 0.01)
        compression_pts = 5.0 if recent_ranges.mean() < 0.85 else 2.5

        # Total Alpha Score
        total_alpha = (
            breakout_pts +
            rvol_pts +
            rs_pts +
            vwap_pts +
            regime_pts +
            ema_pts +
            compression_pts
        )
        total_alpha = min(max(round(total_alpha, 1), 0.0), 100.0)

        breakdown = {
            "breakout_quality": round(breakout_pts, 1),
            "time_rvol": round(rvol_pts, 1),
            "relative_strength": round(rs_pts, 1),
            "vwap_alignment": round(vwap_pts, 1),
            "market_regime": round(regime_pts, 1),
            "ema_slope": round(ema_pts, 1),
            "compression": round(compression_pts, 1),
        }

        return {
            "ticker": ticker,
            "spot": spot,
            "orb_high": orb_high,
            "orb_low": orb_low,
            "session_high": session_high,
            "session_low": session_low,
            "vwap": vwap,
            "ema20": ema20,
            "ema_slope": round(ema_slope, 4),
            "atr": round(atr, 2),
            "alpha_score": total_alpha,
            "breakdown": breakdown,
            "rvol_metrics": rvol_data,
            "regime_metrics": reg_data,
            "candle_metrics": candle_metrics,
        }

    except Exception as e:
        return {"alpha_score": 50.0, "status": f"ERROR: {e}"}