"""
resolve_daily_candidates.py
Runs post-market (e.g., 4:05 PM EDT) to parse hero_eval_records.jsonl,
download completed 1-minute historical paths, calculate MFE/MAE,
and resolve binary target ordering (+2R before -1R).
"""

from datetime import datetime
import json
import os
from zoneinfo import ZoneInfo
import pandas as pd
import yfinance as yf

import learn_tracker as lt

EASTERN_TZ = ZoneInfo("America/New_York")
LEARN_FILE = lt.LEARN_LOG_FILE


def run_eod_resolution():
  if not os.path.exists(LEARN_FILE):
    print("⚪ No candidate record file found.")
    return

  records = []
  with open(LEARN_FILE, "r") as f:
    for line in f:
      if line.strip():
        records.append(json.loads(line))

  unresolved = [r for r in records if not r.get("outcome", {}).get("resolved")]
  print(
      f"\n📋 [EOD RESOLUTION] Found {len(records)} total records |"
      f" {len(unresolved)} pending resolution."
  )

  if not unresolved:
    print("✅ All candidate paths are already resolved.")
    return

  # Group by ticker to batch download 1-minute intraday bars
  tickers = list({r["ticker"] for r in unresolved})
  intraday_data = {}

  print(f"📥 Downloading 1-minute intraday bars for: {', '.join(tickers)}...")
  for t in tickers:
    try:
      df = yf.download(t, period="1d", interval="1m", progress=False)
      if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
      intraday_data[t] = df
    except Exception as e:
      print(f"⚠️ Failed to fetch 1m bars for {t}: {e}")
      intraday_data[t] = pd.DataFrame()

  resolved_count = 0
  updated_records = []

  for rec in records:
    if not rec.get("outcome", {}).get("resolved"):
      t = rec["ticker"]
      df_1m = intraday_data.get(t)
      if df_1m is not None and not df_1m.empty:
        rec = lt.resolve_candidate_path(rec, df_1m)
        resolved_count += 1
    updated_records.append(rec)

  # Atomic rewrite of the JSONL ledger
  temp_file = LEARN_FILE + ".tmp"
  with open(temp_file, "w") as f:
    for r in updated_records:
      f.write(json.dumps(r) + "\n")
  os.replace(temp_file, LEARN_FILE)

  print(f"✅ Successfully resolved and saved {resolved_count} candidate paths.")


if __name__ == "__main__":
  run_eod_resolution()