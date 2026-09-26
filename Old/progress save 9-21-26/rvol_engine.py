from datetime import datetime, timedelta
import numpy as np
import pandas as pd
import yfinance as yf


def get_time_adjusted_rvol(
    ticker: str, lookback_days: int = 40, interval: str = "15m"
) -> dict:
  """Calculates time-of-day RVOL metrics against the prior N trading sessions.

  Returns:
      ratio, percentile (0-100), zscore, current_vol, historical_median
  """
  try:
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=lookback_days + 15)

    df = yf.download(
        ticker,
        start=start_dt.strftime("%Y-%m-%d"),
        interval=interval,
        progress=False,
    )
    if isinstance(df.columns, pd.MultiIndex):
      df.columns = df.columns.get_level_values(0)

    if df.empty or len(df) < 50:
      return {
          "ratio": 1.0,
          "percentile": 50.0,
          "zscore": 0.0,
          "current_vol": 0,
          "hist_median": 0,
          "status": "INSUFFICIENT_DATA",
      }

    # Extract time string (e.g., '10:30')
    df["time_slot"] = df.index.strftime("%H:%M")
    current_slot = df["time_slot"].iloc[-1]
    current_vol = float(df["Volume"].iloc[-1])

    # Slice past trading sessions for the exact same time slot (excluding current candle)
    slot_history = df[
        (df["time_slot"] == current_slot) & (df.index < df.index[-1])
    ]["Volume"].dropna()

    if len(slot_history) < 10:
      return {
          "ratio": 1.0,
          "percentile": 50.0,
          "zscore": 0.0,
          "current_vol": current_vol,
          "hist_median": current_vol,
          "status": "SAMPLE_TOO_SMALL",
      }

    hist_mean = float(slot_history.mean())
    hist_median = float(slot_history.median())
    hist_std = float(slot_history.std()) if slot_history.std() > 0 else 1.0

    ratio = current_vol / hist_median if hist_median > 0 else 1.0
    percentile = float((slot_history < current_vol).mean() * 100.0)
    zscore = float((current_vol - hist_mean) / hist_std)

    return {
        "time_slot": current_slot,
        "ratio": round(ratio, 2),
        "percentile": round(percentile, 1),
        "zscore": round(zscore, 2),
        "current_vol": int(current_vol),
        "hist_median": int(hist_median),
        "hist_mean": int(hist_mean),
        "sample_size": len(slot_history),
        "status": "SUCCESS",
    }
  except Exception as e:
    return {
        "ratio": 1.0,
        "percentile": 50.0,
        "zscore": 0.0,
        "current_vol": 0,
        "hist_median": 0,
        "status": f"ERROR: {e}",
    }