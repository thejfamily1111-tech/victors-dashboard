from datetime import datetime, timedelta
import numpy as np
import pandas as pd
import yfinance as yf

# Sector mapping for active universe
TICKER_SECTOR_MAP = {
    "NVDA": "SMH",
    "AMD": "SMH",
    "AAPL": "XLK",
    "MSFT": "XLK",
    "AMZN": "XLY",
    "TSLA": "XLY",
    "META": "XLC",
    "GOOGL": "XLC",
    "SPY": "SPY",
    "QQQ": "QQQ",
}


def get_market_regime():
  """Evaluates CBOE Volatility (^VIX) and returns a granular regime classification."""
  try:
    vix = yf.Ticker("^VIX")
    hist = vix.history(period="5d")
    current_vix = (
        float(hist["Close"].iloc[-1]) if not hist.empty else 16.5
    )
    prev_vix = (
        float(hist["Close"].iloc[-2]) if len(hist) > 1 else current_vix
    )
    vix_pct_change = (
        ((current_vix - prev_vix) / prev_vix * 100.0) if prev_vix > 0 else 0.0
    )

    # Classify Volatility
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
      regime = (
          "HIGH VOL TRENDING"
          if abs(vix_pct_change) < 5.0
          else "HIGH VOL CHOP"
      )
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
  """Grades daily EMA20 and intraday VWAP alignment into a 0-100 score."""
  try:
    df_daily = yf.download(ticker, period="60d", interval="1d", progress=False)
    if isinstance(df_daily.columns, pd.MultiIndex):
      df_daily.columns = df_daily.columns.get_level_values(0)

    close_d = float(df_daily["Close"].iloc[-1])
    ema20_d = float(
        df_daily["Close"].ewm(span=20, adjust=False).mean().iloc[-1]
    )
    daily_trend = 100.0 if close_d > ema20_d else 25.0

    df_intra = yf.download(ticker, period="5d", interval="15m", progress=False)
    if isinstance(df_intra.columns, pd.MultiIndex):
      df_intra.columns = df_intra.columns.get_level_values(0)

    # Intraday VWAP calculation
    df_intra["cum_vol"] = df_intra["Volume"].cumsum()
    df_intra["cum_vol_price"] = (
        (df_intra["Close"] * df_intra["Volume"]).cumsum()
    )
    df_intra["vwap"] = df_intra["cum_vol_price"] / df_intra["cum_vol"]

    spot = float(df_intra["Close"].iloc[-1])
    vwap = float(df_intra["vwap"].iloc[-1])
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
  """Calculates Stock vs Market (SPY) and Stock vs Sector ETF Relative Strength."""
  sector_etf = TICKER_SECTOR_MAP.get(ticker, "SPY")
  tickers_to_pull = list(set([ticker, "SPY", sector_etf]))

  try:
    data = yf.download(
        tickers_to_pull, period="2d", interval="15m", progress=False
    )["Close"]
    if isinstance(data.columns, pd.MultiIndex):
      data.columns = data.columns.get_level_values(0)

    periods = max(int(lookback_minutes / 15), 1)

    r_stock = (
        float(data[ticker].iloc[-1] - data[ticker].iloc[-1 - periods])
        / data[ticker].iloc[-1 - periods]
        * 100.0
    )
    r_spy = (
        float(data["SPY"].iloc[-1] - data["SPY"].iloc[-1 - periods])
        / data["SPY"].iloc[-1 - periods]
        * 100.0
    )
    r_sec = (
        float(
            data[sector_etf].iloc[-1] - data[sector_etf].iloc[-1 - periods]
        )
        / data[sector_etf].iloc[-1 - periods]
        * 100.0
    )

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
  """Calculates the full composite market regime score (0-100) without binary vetos."""
  sector_etf = TICKER_SECTOR_MAP.get(ticker, "SPY")

  spy_data = get_trend_structure("SPY")
  qqq_data = get_trend_structure("QQQ")
  sector_data = get_trend_structure(sector_etf)
  vix_data = get_market_regime()
  rs_data = calculate_relative_strength(ticker)

  # Volatility score contribution
  v_score = (
      85.0
      if "NORMAL" in vix_data["regime"] or "TRENDING" in vix_data["regime"]
      else 40.0
  )

  # RS score contribution
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
  """Scans universe and presents 15m breakout momentum matrix."""
  universe = ["SPY", "QQQ", "NVDA", "AAPL", "META", "TSLA"]
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