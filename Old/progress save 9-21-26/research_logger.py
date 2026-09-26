from datetime import datetime
import json
import os
from typing import Any, Dict, Optional
import pandas as pd

LOG_DIR = os.path.expanduser("~/trading_bot/research_data")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "hero_shadow_records.jsonl")


def log_shadow_record(
    ticker: str,
    action: str,  # "SETUP_DETECTED", "TRADE_ARMED", "TRADE_TAKEN", "TRADE_REJECTED", "TRADE_EXIT"
    spot_price: float,
    orb_high: float,
    orb_low: float,
    vwap: float,
    ema20: float,
    ema_slope: float,
    atr: float,
    # RVOL Metrics
    rvol_ratio: float,
    rvol_percentile: float,
    rvol_zscore: float,
    # Regime & Relative Strength
    spy_score: float,
    qqq_score: float,
    sector_etf: str,
    sector_score: float,
    rs_market: float,
    rs_sector: float,
    volatility_regime: str,
    # Scoring Layers
    alpha_score: float,
    alpha_breakdown: Dict[str, float],
    # VIC Macro Governance Engine Telemetry (New)
    vic_verdict: Optional[str] = "PERMIT",
    vic_mode: Optional[str] = "SHADOW",
    vic_sizing_scalar: Optional[float] = 1.0,
    vic_reason_code: Optional[str] = "NONE",
    vic_reason: Optional[str] = "",
    vic_obstacle_dist_r: Optional[float] = None,
    vic_1h_bar_ts: Optional[str] = None,
    vic_4h_bar_ts: Optional[str] = None,
    # Options Metrics
    contract_symbol: Optional[str] = None,
    delta: Optional[float] = None,
    dte: Optional[int] = None,
    bid: Optional[float] = None,
    ask: Optional[float] = None,
    spread_pct: Optional[float] = None,
    execution_score: Optional[float] = None,
    # Execution & PnL
    trade_taken: bool = False,
    rejection_reason: Optional[str] = None,
    entry_price: Optional[float] = None,
    exit_price: Optional[float] = None,
    pnl_usd: Optional[float] = None,
    result_r: Optional[float] = None,
    exit_reason: Optional[str] = None,
) -> Dict[str, Any]:
  """Appends a complete trade evaluation record with VIC governance telemetry to the research dataset."""
  record = {
      "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
      "ticker": ticker,
      "action": action,
      "spot_price": round(spot_price, 2),
      "orb_high": round(orb_high, 2),
      "orb_low": round(orb_low, 2),
      "vwap": round(vwap, 2),
      "ema20": round(ema20, 2),
      "ema_slope": round(ema_slope, 4),
      "atr": round(atr, 2),
      "rvol": {
          "ratio": round(rvol_ratio, 2),
          "percentile": round(rvol_percentile, 1),
          "zscore": round(rvol_zscore, 2),
      },
      "regime": {
          "spy_score": round(spy_score, 1),
          "qqq_score": round(qqq_score, 1),
          "sector_etf": sector_etf,
          "sector_score": round(sector_score, 1),
          "rs_market": round(rs_market, 2),
          "rs_sector": round(rs_sector, 2),
          "volatility_regime": volatility_regime,
      },
      "alpha_engine": {
          "alpha_score": round(alpha_score, 1),
          "breakdown": alpha_breakdown,
      },
      "vic_governor": {
          "verdict": vic_verdict,
          "mode": vic_mode,
          "sizing_scalar": (
              round(vic_sizing_scalar, 2)
              if vic_sizing_scalar is not None
              else 1.0
          ),
          "reason_code": vic_reason_code,
          "reason": vic_reason,
          "obstacle_distance_r": (
              round(vic_obstacle_dist_r, 2)
              if vic_obstacle_dist_r is not None
              else None
          ),
          "data_timestamp_1h": vic_1h_bar_ts,
          "data_timestamp_4h": vic_4h_bar_ts,
      },
      "options_engine": {
          "contract": contract_symbol,
          "delta": round(delta, 2) if delta is not None else None,
          "dte": dte,
          "bid": bid,
          "ask": ask,
          "spread_pct": (
              round(spread_pct, 2) if spread_pct is not None else None
          ),
          "execution_score": (
              round(execution_score, 1)
              if execution_score is not None
              else None
          ),
      },
      "trade_status": {
          "trade_taken": trade_taken,
          "rejection_reason": rejection_reason,
          "entry": entry_price,
          "exit": exit_price,
          "pnl_usd": pnl_usd,
          "result_r": round(result_r, 2) if result_r is not None else None,
          "exit_reason": exit_reason,
      },
  }

  with open(LOG_FILE, "a") as f:
    f.write(json.dumps(record) + "\n")

  return record


def get_research_dataframe() -> pd.DataFrame:
  """Reads the raw research JSON lines into a flat Pandas DataFrame for analysis."""
  if not os.path.exists(LOG_FILE):
    return pd.DataFrame()
  records = []
  with open(LOG_FILE, "r") as f:
    for line in f:
      if line.strip():
        records.append(json.loads(line))
  return pd.json_normalize(records)


def compute_vic_governance_expectancy() -> Dict[str, Any]:
  """Computes statistical expectancy comparison across PERMIT, DOWNGRADE, and VETO groups."""
  df = get_research_dataframe()
  if df.empty or "trade_status.result_r" not in df.columns:
    return {"message": "Insufficient completed trade logs."}

  # Filter completed exit records
  exits = df[df["action"] == "TRADE_EXIT"].dropna(
      subset=["trade_status.result_r"]
  )
  if exits.empty:
    return {"message": "No completed trade exits recorded yet."}

  summary = {}
  for group in ["PERMIT", "DOWNGRADE", "VETO"]:
    grp_df = exits[exits["vic_governor.verdict"] == group]
    count = len(grp_df)
    if count > 0:
      win_rate = (grp_df["trade_status.result_r"] > 0).mean() * 100.0
      avg_r = grp_df["trade_status.result_r"].mean()
      summary[group] = {
          "sample_size": count,
          "win_rate": f"{win_rate:.1f}%",
          "expectancy_r": f"{avg_r:+.2f}R",
      }
    else:
      summary[group] = {"sample_size": 0, "win_rate": "N/A", "expectancy_r": "N/A"}

  return summary