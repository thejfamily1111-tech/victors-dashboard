"""Paced, locked Yahoo access. Failure never returns stale cache as fresh data."""
import threading
import time
import pandas as pd

_LOCK=threading.Lock()
_CACHE={}
_LAST=0.0

def safe_download(tickers,period="60d",interval="5m"):
    import yfinance as yf
    global _LAST
    key=(str(tickers),period,interval)
    with _LOCK:
        now=time.monotonic()
        cached=_CACHE.get(key)
        # Cache cannot straddle a bar completion boundary.
        slot=int(time.time()//300)
        if cached and cached[2]==slot and now-cached[0]<15:
            return cached[1].copy()
        time.sleep(max(0,0.4-(now-_LAST)))
        try:
            df=yf.download(tickers,period=period,interval=interval,progress=False,
                           auto_adjust=False,prepost=False,threads=False,timeout=8)
        finally:
            _LAST=time.monotonic()
        if df is None or df.empty:
            raise RuntimeError("MARKET_DATA_UNAVAILABLE")
        _CACHE[key]=(time.monotonic(),df.copy(),slot)
        return df
