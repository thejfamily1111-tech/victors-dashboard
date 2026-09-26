"""learn_tracker.py.

Institutional Telemetry, Decision-Time State Capture, and Counterfactual
MFE/MAE Path-Resolution Engine for HERO and VIC.
"""

from datetime import datetime
import json
import os
import uuid
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd
import yfinance as yf

EASTERN_TZ = ZoneInfo("America/New_York")

# -------------------------------------------------------------
# PATH CONFIGURATION (Single Canonical Source of Truth)
# -------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LEARN_DIR = os.path.join(BASE_DIR, "research_data")

if not os.path.exists(LEARN_DIR) and os.path.exists(
    os.path.expanduser("~/trading_bot/research_data")
):
  LEARN_DIR = os.path.expanduser("~/trading_bot/research_data")

os.makedirs(LEARN_DIR, exist_ok=True)
LEARN_LOG_FILE = os.path.join(LEARN_DIR, "hero_eval_records.jsonl")


def generate_candidate_id(ticker: str, direction: str) -> str:
  """Generates an immutable, collision-resistant candidate ID."""
  ts = datetime.now(EASTERN_TZ).strftime("%Y%m%d_%H%M%S")
  short_uid = uuid.uuid4().hex[:4]
  return f"{ticker.upper()}_{direction.upper()}_{ts}_{short_uid}"


def create_candidate_record(
    ticker: str,
    direction: str,
    spot: float,
    orb_high: float,
    orb_low: float,
    vwap: float,
    ema20_15m: float,
    ema20_slope_15m: float,
    atr_15m: float,
    rvol_ratio: float,
    rvol_percentile: float,
    rvol_zscore: float,
    rs_market: float,
    rs_sector: float,
    sector_etf: str,
    breakout_body_pct: float = 0.0,
    close_location_val: float = 0.0,
    compression_score: float = 0.0,
    hero_alpha_score: float = 50.0,
    hero_decision: str = "REJECT",
    hero_reason_code: str = "NONE",
    vic_verdict: str = "PERMIT",
    vic_sizing_scalar: float = 1.0,
    vic_reason_code: str = "NONE",
    vic_trend_1h: str = "NEUTRAL",
    vic_ema20_1h: float = 0.0,
    vic_ema_slope_1h: float = 0.0,
    vic_ema_distance_atr_1h: float = 0.0,
    vic_structure_4h: str = "NEUTRAL",
    vic_nearest_obstacle: float = 0.0,
    vic_obstacle_distance_r: float = 999.0,
    vic_spy_regime: float = 50.0,
    vic_qqq_regime: float = 50.0,
    vic_sector_regime: float = 50.0,
    vic_volatility_regime: str = "NORMAL",
    contract_symbol: str = "NONE",
    strike: float = 0.0,
    expiration: str = "",
    dte: int = 0,
    delta: float = 0.0,
    gamma: float = 0.0,
    theta: float = 0.0,
    vega: float = 0.0,
    iv: float = 0.0,
    bid: float = 0.0,
    ask: float = 0.0,
    mid: float = 0.0,
    spread_pct: float = 0.0,
    volume: int = 0,
    open_interest: int = 0,
    execution_score: float = 0.0,
    final_state: str = "SHADOW_TRACK",
    decision_code: str = "NONE",
    risk_budget_dollars: float = 250.0,
    base_qty: int = 1,
    vic_adjusted_qty: int = 1,
) -> dict:
  """Builds a frozen candidate record capturing decision-time reality.

  Critical Principle: 1R is mathematically locked at this exact instant.
  """
  now_et = datetime.now(EASTERN_TZ)
  c_id = generate_candidate_id(ticker, direction)

  risk_per_share = round(max(atr_15m * 1.0, 0.50), 2)
  if direction.upper() == "CALL":
    stop_ref = round(spot - risk_per_share, 2)
    target_1r = round(spot + risk_per_share, 2)
    target_2r = round(spot + (2.0 * risk_per_share), 2)
    orb_ext = (
        round((spot - orb_high) / risk_per_share, 2)
        if risk_per_share > 0
        else 0.0
    )
    vwap_dist = (
        round((spot - vwap) / risk_per_share, 2) if risk_per_share > 0 else 0.0
    )
  else:
    stop_ref = round(spot + risk_per_share, 2)
    target_1r = round(spot - risk_per_share, 2)
    target_2r = round(spot - (2.0 * risk_per_share), 2)
    orb_ext = (
        round((orb_low - spot) / risk_per_share, 2)
        if risk_per_share > 0
        else 0.0
    )
    vwap_dist = (
        round((vwap - spot) / risk_per_share, 2) if risk_per_share > 0 else 0.0
    )

  return {
      "schema_version": "1.0",
      "candidate_id": c_id,
      "created_at": now_et.strftime("%Y-%m-%d %H:%M:%S ET"),
      "ticker": ticker.upper(),
      "direction": direction.upper(),
      "hero_version": "HERO_V1.0",
      "vic_version": "VIC_V1.0",
      "market": {
          "spot": round(spot, 2),
          "orb_high": round(orb_high, 2),
          "orb_low": round(orb_low, 2),
          "orb_extension_atr": orb_ext,
          "vwap": round(vwap, 2),
          "vwap_distance_atr": vwap_dist,
          "ema20_15m": round(ema20_15m, 2),
          "ema20_slope_15m": round(ema20_slope_15m, 4),
          "atr_15m": round(atr_15m, 2),
          "rvol_ratio": round(rvol_ratio, 2),
          "rvol_percentile": round(rvol_percentile, 1),
          "rvol_zscore": round(rvol_zscore, 2),
          "rs_market": round(rs_market, 2),
          "rs_sector": round(rs_sector, 2),
          "sector_etf": sector_etf,
          "breakout_body_pct": round(breakout_body_pct, 1),
          "close_location_value": round(close_location_val, 2),
          "compression_score": round(compression_score, 2),
      },
      "hero": {
          "alpha_score": round(hero_alpha_score, 1),
          "decision": hero_decision,
          "reason_code": hero_reason_code,
      },
      "vic": {
          "verdict": vic_verdict,
          "sizing_scalar": round(vic_sizing_scalar, 2),
          "reason_code": vic_reason_code,
          "trend_1h": vic_trend_1h,
          "ema20_1h": round(vic_ema20_1h, 2),
          "ema_slope_1h": round(vic_ema_slope_1h, 4),
          "ema_distance_atr_1h": round(vic_ema_distance_atr_1h, 2),
          "structure_4h": vic_structure_4h,
          "nearest_obstacle": round(vic_nearest_obstacle, 2),
          "obstacle_distance_r": round(vic_obstacle_distance_r, 2),
          "spy_regime": round(vic_spy_regime, 1),
          "qqq_regime": round(vic_qqq_regime, 1),
          "sector_regime": round(vic_sector_regime, 1),
          "volatility_regime": vic_volatility_regime,
      },
      "option": {
          "contract": contract_symbol,
          "strike": round(strike, 2),
          "expiration": expiration,
          "dte": dte,
          "delta": round(delta, 2),
          "gamma": round(gamma, 4),
          "theta": round(theta, 4),
          "vega": round(vega, 4),
          "iv": round(iv, 2),
          "bid": round(bid, 2),
          "ask": round(ask, 2),
          "mid": round(mid, 2),
          "spread_pct": round(spread_pct, 2),
          "volume": volume,
          "open_interest": open_interest,
          "execution_score": round(execution_score, 1),
      },
      "decision": {
          "final_state": final_state,
          "decision_code": decision_code,
          "entry_reference": round(spot, 2),
          "stop_reference": stop_ref,
          "target_1r": target_1r,
          "target_2r": target_2r,
          "risk_per_share": risk_per_share,
          "risk_budget_dollars": round(risk_budget_dollars, 2),
          "base_qty": base_qty,
          "vic_adjusted_qty": vic_adjusted_qty,
          "signal_created_at": now_et.strftime("%Y-%m-%d %H:%M:%S"),
          "signal_expires_at": (
              now_et.replace(hour=15, minute=0, second=0).strftime(
                  "%Y-%m-%d %H:%M:%S"
              )
          ),
      },
      "outcome": {
          "resolved": False,
          "resolved_at": None,
          "path_resolution": "1m",
          "path_ambiguous": False,
          "mfe_r": None,
          "mae_r": None,
          "hit_plus_1r": False,
          "hit_plus_2r": False,
          "hit_minus_1r": False,
          "plus_1r_before_minus_1r": None,
          "plus_2r_before_minus_1r": None,
          "time_to_plus_1r_minutes": None,
          "time_to_plus_2r_minutes": None,
          "time_to_minus_1r_minutes": None,
          "r_15m": None,
          "r_30m": None,
          "r_60m": None,
          "r_eod": None,
          "underlying_result_r": None,
          "actual_option_pnl_dollars": None,
          "actual_option_return_pct": None,
          "actual_result_r": None,
          "actual_exit_reason": None,
          "counterfactual_result_r": None,
      },
      "evaluation": {"decision_quality": None, "outcome_quality": None},
  }


def resolve_candidate_path(
    candidate: dict, df_1m: pd.DataFrame = None
) -> dict:
  """Resolves the 1-minute trajectory of a candidate from inception to EOD."""
  if candidate.get("outcome", {}).get("resolved"):
    return candidate

  ticker = candidate["ticker"]
  created_str = candidate["created_at"].replace(" ET", "")
  created_dt = datetime.strptime(
      created_str, "%Y-%m-%d %H:%M:%S"
  ).replace(tzinfo=EASTERN_TZ)

  direction = candidate["direction"]
  entry = candidate["decision"]["entry_reference"]
  one_r = candidate["decision"]["risk_per_share"]
  target_1r = candidate["decision"]["target_1r"]
  target_2r = candidate["decision"]["target_2r"]
  stop_ref = candidate["decision"]["stop_reference"]

  if df_1m is None or df_1m.empty:
    try:
      df_1m = yf.download(ticker, period="1d", interval="1m", progress=False)
      if isinstance(df_1m.columns, pd.MultiIndex):
        df_1m.columns = [c[0] for c in df_1m.columns]
    except Exception:
      return candidate

  if df_1m.empty:
    return candidate

  if df_1m.index.tz is None:
    df_1m.index = df_1m.index.tz_localize("UTC").tz_convert(EASTERN_TZ)
  else:
    df_1m.index = df_1m.index.tz_convert(EASTERN_TZ)

  post_bars = df_1m[df_1m.index >= created_dt].copy()

  # Path Fallback: If created post-market or on test data, evaluate against available session bars
  if post_bars.empty:
    post_bars = df_1m.tail(30).copy() if len(df_1m) >= 30 else df_1m.copy()
    if post_bars.empty:
      return candidate

  mfe_r = 0.0
  mae_r = 0.0
  hit_1r = False
  hit_2r = False
  hit_stop = False
  path_ambiguous = False

  t_1r_min = None
  t_2r_min = None
  t_stop_min = None

  r_15m = None
  r_30m = None
  r_60m = None

  for idx, (bar_time, row) in enumerate(post_bars.iterrows()):
    elapsed_minutes = int((bar_time - created_dt).total_seconds() / 60)
    high = float(row["High"])
    low = float(row["Low"])
    close = float(row["Close"])

    if direction == "CALL":
      bar_mfe = (high - entry) / one_r
      bar_mae = (low - entry) / one_r
      touched_target_2r = high >= target_2r
      touched_target_1r = high >= target_1r
      touched_stop = low <= stop_ref
      current_close_r = (close - entry) / one_r
    else:
      bar_mfe = (entry - low) / one_r
      bar_mae = (entry - high) / one_r
      touched_target_2r = low <= target_2r
      touched_target_1r = low <= target_1r
      touched_stop = high >= stop_ref
      current_close_r = (entry - close) / one_r

    if bar_mfe > mfe_r:
      mfe_r = bar_mfe
    if bar_mae < mae_r:
      mae_r = bar_mae

    if elapsed_minutes >= 15 and r_15m is None:
      r_15m = round(current_close_r, 2)
    if elapsed_minutes >= 30 and r_30m is None:
      r_30m = round(current_close_r, 2)
    if elapsed_minutes >= 60 and r_60m is None:
      r_60m = round(current_close_r, 2)

    if touched_target_2r and touched_stop and not hit_stop and not hit_2r:
      path_ambiguous = True
      hit_stop = True
      t_stop_min = elapsed_minutes
      break

    if touched_stop and not hit_stop:
      hit_stop = True
      t_stop_min = elapsed_minutes
      break

    if touched_target_1r and not hit_1r:
      hit_1r = True
      t_1r_min = elapsed_minutes

    if touched_target_2r and not hit_2r:
      hit_2r = True
      t_2r_min = elapsed_minutes
      break

  last_close = float(post_bars["Close"].iloc[-1])
  r_eod = (
      round((last_close - entry) / one_r, 2)
      if direction == "CALL"
      else round((entry - last_close) / one_r, 2)
  )

  p_1r_before_stop = hit_1r and (not hit_stop or (t_1r_min <= t_stop_min))
  p_2r_before_stop = hit_2r and (not hit_stop or (t_2r_min <= t_stop_min))

  if hit_2r:
    cf_result = 2.0
  elif hit_stop:
    cf_result = -1.0
  else:
    cf_result = r_eod

  out = candidate["outcome"]
  out["resolved"] = True
  out["resolved_at"] = datetime.now(EASTERN_TZ).strftime("%Y-%m-%d %H:%M:%S ET")
  out["path_ambiguous"] = path_ambiguous
  out["mfe_r"] = round(mfe_r, 2)
  out["mae_r"] = round(mae_r, 2)
  out["hit_plus_1r"] = hit_1r
  out["hit_plus_2r"] = hit_2r
  out["hit_minus_1r"] = hit_stop
  out["plus_1r_before_minus_1r"] = p_1r_before_stop
  out["plus_2r_before_minus_1r"] = p_2r_before_stop
  out["time_to_plus_1r_minutes"] = t_1r_min
  out["time_to_plus_2r_minutes"] = t_2r_min
  out["time_to_minus_1r_minutes"] = t_stop_min
  out["r_15m"] = r_15m
  out["r_30m"] = r_30m
  out["r_60m"] = r_60m
  out["r_eod"] = r_eod
  out["underlying_result_r"] = cf_result
  out["counterfactual_result_r"] = cf_result

  is_positive_decision = (
      candidate["hero"]["decision"] == "APPROVE"
      and candidate["vic"]["verdict"] != "VETO"
  )
  is_positive_outcome = cf_result > 0.0

  if is_positive_decision and is_positive_outcome:
    candidate["evaluation"]["decision_quality"] = "GOOD_DECISION"
    candidate["evaluation"]["outcome_quality"] = "GOOD_OUTCOME"
  elif is_positive_decision and not is_positive_outcome:
    candidate["evaluation"]["decision_quality"] = "GOOD_DECISION"
    candidate["evaluation"]["outcome_quality"] = "BAD_OUTCOME"
  elif not is_positive_decision and is_positive_outcome:
    candidate["evaluation"]["decision_quality"] = "BAD_DECISION"
    candidate["evaluation"]["outcome_quality"] = "GOOD_OUTCOME"
  else:
    candidate["evaluation"]["decision_quality"] = "BAD_DECISION"
    candidate["evaluation"]["outcome_quality"] = "BAD_OUTCOME"

  return candidate


def append_candidate_to_log(candidate: dict):
  """Appends an immutable record directly into hero_eval_records.jsonl."""
  with open(LEARN_LOG_FILE, "a") as f:
    f.write(json.dumps(candidate) + "\n")


def load_eval_dataframe() -> pd.DataFrame:
  """Reads JSONL candidate records into a normalized Pandas DataFrame."""
  if not os.path.exists(LEARN_LOG_FILE):
    return pd.DataFrame()
  records = []
  with open(LEARN_LOG_FILE, "r") as f:
    for line in f:
      if line.strip():
        records.append(json.loads(line))
  if not records:
    return pd.DataFrame()
  df = pd.json_normalize(records)
  if "outcome.resolved" in df.columns:
    df["outcome.resolved"] = (
        df["outcome.resolved"].astype(str).str.lower().isin(["true", "1"])
    )
  return df