"""Compatibility facade over canonical same-clock completed 5m RVOL."""
from dataclasses import asdict
from market_mechanics_bible import compute_same_clock_rvol

def get_time_adjusted_rvol(ticker, df=None, current_bar_ts=None):
    if df is None or current_bar_ts is None:
        raise ValueError('Supply completed bars and explicit current_bar_ts')
    r=asdict(compute_same_clock_rvol(df,current_bar_ts))
    return {**r,'ratio':r['ratio_mean'],'status':'SUCCESS' if r['sample_size'] else 'MISSING_HISTORY'}
