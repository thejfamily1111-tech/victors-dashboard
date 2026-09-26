"""
rvol_engine.py - Volume & RVOL Analysis Engine with Minute Pacing
"""

import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime
from zoneinfo import ZoneInfo

EASTERN_TZ = ZoneInfo("America/New_York")

def get_time_adjusted_rvol(ticker: str, df: pd.DataFrame = None) -> dict:
    """
    Calculates time-adjusted relative volume (RVOL) comparing the current
    15-minute intraday candle to historical distributions for that exact time slot.
    Applies linear minute-pacing extrapolation for in-progress bars.
    """
    try:
        if df is None:
            tk = yf.Ticker(ticker)
            df = tk.history(period="10d", interval="15m")
            if df.empty:
                return {
                    "ratio": 1.0,
                    "percentile": 50.0,
                    "zscore": 0.0,
                    "current_vol": 0,
                    "paced_vol": 0,
                    "hist_median": 0,
                    "status": "DATA_UNAVAILABLE"
                }

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        if df.empty or len(df) < 50:
            return {
                "ratio": 1.0,
                "percentile": 50.0,
                "zscore": 0.0,
                "current_vol": 0,
                "paced_vol": 0,
                "hist_median": 0,
                "status": "INSUFFICIENT_DATA"
            }

        # Extract time string (e.g., '10:30')
        df["time_slot"] = df.index.strftime("%H:%M")
        current_slot = df["time_slot"].iloc[-1]
        current_vol = float(df["Volume"].iloc[-1])

        # Elapsed minutes into current 15m candle (1 to 15)
        last_dt = df.index[-1]
        minute_offset = (last_dt.minute % 15) + 1
        paced_vol = current_vol * (15.0 / max(1, minute_offset))

        # Slice past trading sessions for the exact same time slot (excluding current candle)
        slot_history = df[
            (df["time_slot"] == current_slot) & (df.index < df.index[-1])
        ]["Volume"].dropna()

        if len(slot_history) < 10:
            return {
                "time_slot": current_slot,
                "ratio": 1.0,
                "percentile": 50.0,
                "zscore": 0.0,
                "current_vol": int(current_vol),
                "paced_vol": int(paced_vol),
                "hist_median": int(current_vol),
                "status": "SAMPLE_TOO_SMALL"
            }

        hist_mean = float(slot_history.mean())
        hist_median = float(slot_history.median())
        hist_std = float(slot_history.std()) if slot_history.std() > 0 else 1.0

        ratio = paced_vol / hist_median if hist_median > 0 else 1.0
        percentile = float((slot_history < paced_vol).mean() * 100.0)
        zscore = float((paced_vol - hist_mean) / hist_std)

        return {
            "time_slot": current_slot,
            "ratio": round(ratio, 2),
            "percentile": round(percentile, 1),
            "zscore": round(zscore, 2),
            "current_vol": int(current_vol),
            "paced_vol": int(paced_vol),
            "hist_median": int(hist_median),
            "hist_mean": int(hist_mean),
            "sample_size": len(slot_history),
            "status": "SUCCESS"
        }
    except Exception as e:
        return {
            "ratio": 1.0,
            "percentile": 50.0,
            "zscore": 0.0,
            "current_vol": 0,
            "paced_vol": 0,
            "hist_median": 0,
            "status": f"ERROR: {e}"
        }