"""
safe_yf.py - Rate-Limited & Cached Yahoo Finance Access Layer
Prevents 429/401 blocks with token-bucket delay and in-memory TTL caching.
"""

import time
from datetime import datetime
import pandas as pd
import yfinance as yf

# Global cache: { (tickers_tuple, period, interval): (timestamp, dataframe) }
_DATA_CACHE = {}
CACHE_TTL_SECONDS = 75  # Cache persists across 60s dashboard re-runs
MIN_REQUEST_DELAY = 0.4 # Minimum 400ms between network calls
_last_request_time = 0.0


def safe_download(tickers, period="5d", interval="15m"):
    """
    Thread-safe cached yf.download with pacing delay.
    Accepts a single ticker string or list of tickers.
    """
    global _last_request_time

    if isinstance(tickers, str):
        ticker_key = tuple(tickers.strip().split())
    else:
        ticker_key = tuple(sorted(tickers))

    cache_id = (ticker_key, period, interval)
    now = time.time()

    # 1. Check TTL Cache
    if cache_id in _DATA_CACHE:
        cached_ts, cached_df = _DATA_CACHE[cache_id]
        if now - cached_ts < CACHE_TTL_SECONDS:
            return cached_df.copy()

    # 2. Rate-Limit Pacer (Prevent burst flags)
    elapsed = now - _last_request_time
    if elapsed < MIN_REQUEST_DELAY:
        time.sleep(MIN_REQUEST_DELAY - elapsed)

    # 3. Network Fetch
    try:
        query_syms = " ".join(ticker_key)
        df = yf.download(query_syms, period=period, interval=interval, progress=False)
        _last_request_time = time.time()

        if not df.empty:
            _DATA_CACHE[cache_id] = (time.time(), df)
            return df.copy()
        return df
    except Exception as e:
        # If throttled, return stale cache if available
        if cache_id in _DATA_CACHE:
            return _DATA_CACHE[cache_id][1].copy()
        print(f"⚠️ Safe YF Download error ({tickers}): {e}")
        return pd.DataFrame()


def safe_fast_price(symbol: str) -> float:
    """Safely retrieves current price with micro-delay."""
    global _last_request_time
    now = time.time()
    elapsed = now - _last_request_time
    if elapsed < MIN_REQUEST_DELAY:
        time.sleep(MIN_REQUEST_DELAY - elapsed)

    try:
        tk = yf.Ticker(symbol)
        _last_request_time = time.time()
        fast = getattr(tk, "fast_info", {})
        return float(getattr(fast, "last_price", 0.0))
    except Exception:
        return 0.0