from datetime import datetime
import numpy as np
import pandas as pd
import yfinance as yf

import market_barometer as mb
import rvol_engine as re


def evaluate_breakout_candle(candle: pd.Series, orb_high: float, atr: float) -> dict:
    """Evaluates the anatomical quality of the ORB breakout candle.
    
    CLV = ((Close - Low) - (High - Close)) / (High - Low)  -> Range: -1.0 to +1.0
    """
    c_open = float(candle["Open"])
    c_high = float(candle["High"])
    c_low = float(candle["Low"])
    c_close = float(candle["Close"])
    
    candle_range = max(c_high - c_low, 0.001)
    body_pct = abs(c_close - c_open) / candle_range * 100.0
    upper_wick_pct = (c_high - max(c_open, c_close)) / candle_range * 100.0
    lower_wick_pct = (min(c_open, c_close) - c_low) / candle_range * 100.0
    clv = ((c_close - c_low) - (c_high - c_close)) / candle_range
    
    breakout_distance = max(c_close - orb_high, 0.0)
    breakout_atr_multiple = breakout_distance / atr if atr > 0 else 0.0
    
    # 20 Points Max for Breakout Quality
    score = 0.0
    # Strong close near high (CLV > 0.5)
    if clv >= 0.70:
        score += 8.0
    elif clv >= 0.40:
        score += 5.0
    else:
        score += 2.0
        
    # Healthy body % (not a doji / spinning top)
    if body_pct >= 60.0:
        score += 6.0
    elif body_pct >= 40.0:
        score += 4.0
        
    # Small upper wick (conviction)
    if upper_wick_pct <= 15.0:
        score += 6.0
    elif upper_wick_pct <= 30.0:
        score += 3.0
        
    return {
        "score": round(score, 1),
        "body_pct": round(body_pct, 1),
        "upper_wick_pct": round(upper_wick_pct, 1),
        "lower_wick_pct": round(lower_wick_pct, 1),
        "clv": round(clv, 2),
        "breakout_atr_mult": round(breakout_atr_multiple, 2)
    }


def compute_alpha_score(ticker: str) -> dict:
    """Calculates the Hero Alpha Score (0–100) using purely technical & momentum factors."""
    try:
        # 1. Pull 15m intraday data
        df = yf.download(ticker, period="5d", interval="15m", progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
        if df.empty or len(df) < 25:
            return {"alpha_score": 50.0, "status": "INSUFFICIENT_DATA"}
            
        # Add EMA20 & True Range / ATR
        df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()
        high_low = df["High"] - df["Low"]
        high_cp = np.abs(df["High"] - df["Close"].shift())
        low_cp = np.abs(df["Low"] - df["Close"].shift())
        df["TR"] = np.maximum(high_low, np.maximum(high_cp, low_cp))
        df["ATR"] = df["TR"].rolling(window=14).mean()
        
        # VWAP
        df["cum_vol"] = df["Volume"].cumsum()
        df["cum_vp"] = (df["Close"] * df["Volume"]).cumsum()
        df["VWAP"] = df["cum_vp"] / df["cum_vol"]
        
        last_candle = df.iloc[-1]
        spot = float(last_candle["Close"])
        vwap = float(last_candle["VWAP"])
        ema20 = float(last_candle["EMA20"])
        ema_prev = float(df["EMA20"].iloc[-2])
        ema_slope = ema20 - ema_prev
        atr = float(last_candle["ATR"]) if not np.isnan(last_candle["ATR"]) else 1.0
        
        # Calculate 30m ORB bounds (first two 15m candles of current day)
        today_str = df.index[-1].strftime("%Y-%m-%d")
        today_candles = df[df.index.strftime("%Y-%m-%d") == today_str]
        
        if len(today_candles) >= 2:
            orb_high = float(today_candles.iloc[:2]["High"].max())
            orb_low = float(today_candles.iloc[:2]["Low"].min())
        else:
            orb_high = spot * 1.002
            orb_low = spot * 0.998
            
        # 2. Score Components
        
        # Component A: Breakout Candle Quality (20 pts max)
        breakout_metrics = evaluate_breakout_candle(last_candle, orb_high, atr)
        breakout_pts = breakout_metrics["score"] if spot >= orb_high else 5.0
        
        # Component B: Time-of-Day RVOL (20 pts max)
        rvol_data = re.get_time_adjusted_rvol(ticker, lookback_days=40, interval="15m")
        pctile = rvol_data.get("percentile", 50.0)
        if pctile >= 90.0:
            rvol_pts = 20.0
        elif pctile >= 75.0:
            rvol_pts = 16.0
        elif pctile >= 60.0:
            rvol_pts = 12.0
        elif pctile >= 40.0:
            rvol_pts = 8.0
        else:
            rvol_pts = 4.0
            
        # Component C: Relative Strength (15 pts max)
        rs_data = mb.calculate_relative_strength(ticker, lookback_minutes=30)
        rs_sec = rs_data.get("rs_sector", 0.0)
        if rs_sec >= 1.5:
            rs_pts = 15.0
        elif rs_sec >= 0.5:
            rs_pts = 12.0
        elif rs_sec >= 0.0:
            rs_pts = 9.0
        else:
            rs_pts = 4.0
            
        # Component D: VWAP Alignment (15 pts max)
        vwap_dist_pct = ((spot - vwap) / vwap * 100.0) if vwap > 0 else 0.0
        if spot > vwap:
            # Sweet spot is 0.1% to 1.2% above VWAP (not over-extended)
            vwap_pts = 15.0 if 0.1 <= vwap_dist_pct <= 1.5 else 10.0
        else:
            vwap_pts = 2.0
            
        # Component E: Market & Sector Regime Confluence (15 pts max)
        reg_data = mb.compute_market_regime_score(ticker)
        reg_score = reg_data.get("regime_score", 50.0)
        regime_pts = (reg_score / 100.0) * 15.0
        
        # Component F: EMA20 Slope (10 pts max)
        if ema_slope > 0.05:
            ema_pts = 10.0
        elif ema_slope > 0.0:
            ema_pts = 7.0
        else:
            ema_pts = 2.0
            
        # Component G: Consolidation Compression (5 pts max)
        recent_ranges = (df["High"].iloc[-5:] - df["Low"].iloc[-5:]) / atr
        compression_pts = 5.0 if recent_ranges.mean() < 0.85 else 2.5
        
        # Total Alpha Score
        total_alpha = (
            breakout_pts +
            rvol_pts +
            rs_pts +
            vwap_pts +
            regime_pts +
            ema_pts +
            compression_pts
        )
        total_alpha = min(max(round(total_alpha, 1), 0.0), 100.0)
        
        breakdown = {
            "breakout_quality": round(breakout_pts, 1),
            "time_rvol": round(rvol_pts, 1),
            "relative_strength": round(rs_pts, 1),
            "vwap_alignment": round(vwap_pts, 1),
            "market_regime": round(regime_pts, 1),
            "ema_slope": round(ema_pts, 1),
            "compression": round(compression_pts, 1)
        }
        
        return {
            "ticker": ticker,
            "spot": spot,
            "orb_high": orb_high,
            "orb_low": orb_low,
            "vwap": vwap,
            "ema20": ema20,
            "ema_slope": round(ema_slope, 4),
            "atr": round(atr, 2),
            "alpha_score": total_alpha,
            "breakdown": breakdown,
            "rvol_metrics": rvol_data,
            "regime_metrics": reg_data,
            "candle_metrics": breakout_metrics
        }
        
    except Exception as e:
        return {"alpha_score": 50.0, "status": f"ERROR: {e}"}