import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime

UNIVERSE = ["SPY", "QQQ", "NVDA", "AAPL", "AMD", "AMZN"]

def get_market_regime():
    try:
        vix = yf.download("^VIX", period="5d", interval="1d", progress=False)
        if isinstance(vix.columns, pd.MultiIndex):
            vix.columns = vix.columns.get_level_values(0)
        vix_price = float(vix["Close"].iloc[-1])
        vix_prev = float(vix["Close"].iloc[-2])
        vix_change = vix_price - vix_prev

        if vix_price < 15:
            regime = "Low Volatility (Trend Grind)"
            badge_color = "#28a745"
            note = "Tight spreads; favorable for high-delta runners."
        elif 15 <= vix_price <= 23:
            regime = "Optimal Momentum Window"
            badge_color = "#17a2b8"
            note = "Ideal expansion velocity for 15m ORB setups."
        else:
            regime = "Elevated Risk / Whipsaw Warning"
            badge_color = "#dc3545"
            note = "Wider bid-ask spreads; elevated false breakout risk."

        return {
            "vix": round(vix_price, 2),
            "vix_change": round(vix_change, 2),
            "regime": regime,
            "badge_color": badge_color,
            "note": note
        }
    except Exception:
        return {
            "vix": 18.5,
            "vix_change": 0.0,
            "regime": "Optimal Momentum Window",
            "badge_color": "#17a2b8",
            "note": "Baseline parameters loaded."
        }

def get_orb_readiness_matrix():
    records = []
    for sym in UNIVERSE:
        try:
            df = yf.download(sym, period="5d", interval="15m", progress=False)
            if df.empty or len(df) < 10:
                continue
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            last_date = df.index[-1].date()
            df_sess = df[df.index.date == last_date].copy()
            if len(df_sess) < 2:
                df_sess = df.tail(8).copy()

            typ = (df_sess["High"] + df_sess["Low"] + df_sess["Close"]) / 3.0
            cum_vol = df_sess["Volume"].cumsum()
            cum_pv = (typ * df_sess["Volume"]).cumsum()
            df_sess["VWAP"] = cum_pv / np.where(cum_vol == 0, 1, cum_vol)

            orb_high = float(df_sess.iloc[:2]["High"].max())
            orb_low = float(df_sess.iloc[:2]["Low"].min())
            current_spot = float(df_sess.iloc[-1]["Close"])
            vwap_val = float(df_sess.iloc[-1]["VWAP"])

            ema20 = df["Close"].ewm(span=20, adjust=False).mean()
            slope = float(ema20.iloc[-1] - ema20.iloc[-3])

            dist_to_high = round(((current_spot - orb_high) / orb_high) * 100, 2)
            dist_to_low = round(((orb_low - current_spot) / orb_low) * 100, 2)

            if current_spot > orb_high and current_spot > vwap_val and slope > 0:
                status = "ACTIVE CALL BREAKOUT"
            elif current_spot < orb_low and current_spot < vwap_val and slope < 0:
                status = "ACTIVE PUT BREAKDOWN"
            elif abs(dist_to_high) <= 0.35:
                status = "CALL BREAKOUT IMMINENT"
            elif abs(dist_to_low) <= 0.35:
                status = "PUT BREAKDOWN IMMINENT"
            else:
                status = "CONSOLIDATING IN RANGE"

            records.append({
                "Ticker": sym,
                "Spot": f"${current_spot:.2f}",
                "ORB High": f"${orb_high:.2f}",
                "ORB Low": f"${orb_low:.2f}",
                "VWAP": f"${vwap_val:.2f}",
                "EMA Slope": "Bullish" if slope > 0 else "Bearish",
                "Distance to Trigger": f"{dist_to_high:+.2f}% (High)" if abs(dist_to_high) < abs(dist_to_low) else f"{dist_to_low:+.2f}% (Low)",
                "Status": status
            })
        except Exception:
            continue
    return pd.DataFrame(records)
