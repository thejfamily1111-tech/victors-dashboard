from datetime import date, datetime, timedelta
import math
import os
import time
from dotenv import load_dotenv
import numpy as np
import pandas as pd
from scipy.stats import norm
import yfinance as yf

from alpaca.data.historical.option import OptionHistoricalDataClient
from alpaca.data.requests import OptionSnapshotRequest
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import ContractType, OrderSide, TimeInForce
from alpaca.trading.requests import GetOptionContractsRequest, LimitOrderRequest

# Quantitative & Logging Layers
import alpha_engine as ae
import option_engine as oe
import research_logger as rl

# 1. Environment & API Clients
for path in [
    "/Users/vic/Desktop/Coding/.env",
    "/Users/vic/trading_bot/.env",
    ".env",
]:
    if os.path.exists(path):
        load_dotenv(path)

API_KEY = os.getenv("APCA_API_KEY_ID") or os.getenv("ALPACA_API_KEY")
SECRET_KEY = os.getenv("APCA_API_SECRET_KEY") or os.getenv("ALPACA_SECRET_KEY")

if API_KEY and SECRET_KEY:
    trading_client = TradingClient(API_KEY, SECRET_KEY, paper=True)
    data_client = OptionHistoricalDataClient(API_KEY, SECRET_KEY)
else:
    trading_client = None
    data_client = None

# 2. Institutional Research Parameters
UNIVERSE = ["SPY", "QQQ", "NVDA", "AAPL", "AMD", "AMZN"]
RISK_PER_TRADE_PERCENT = 0.005  # 0.5% max equity risk per trade
MAX_CONCURRENT_POSITIONS = 3
TARGET_DELTA = 0.65  # Target ~0.65 Delta (Slightly ITM)
DELTA_TOLERANCE = 0.10  # Accept Delta between 0.55 and 0.75
MAX_RELATIVE_SPREAD = 0.06  # Max 6% spread vs midpoint
MIN_DTE = 1
MAX_DTE = 7
FLATTEN_TIME_STR = "15:45:00"

active_trades = {}
pending_setups = {}  # Tracks ARMED setups awaiting fill or revalidation


def calculate_delta(
    spot: float,
    strike: float,
    dte_days: float,
    is_call: bool = True,
    iv: float = 0.22,
    r: float = 0.045,
) -> float:
    """Calculates Black-Scholes Delta locally."""
    t = max(dte_days, 0.5) / 365.0
    d1 = (math.log(spot / strike) + (r + 0.5 * iv**2) * t) / (iv * math.sqrt(t))
    return float(norm.cdf(d1)) if is_call else float(norm.cdf(d1) - 1.0)


def is_regular_market_hours() -> bool:
    """Checks US Regular Trading Hours (9:30 AM - 4:00 PM EDT)."""
    if trading_client:
        try:
            clock = trading_client.get_clock()
            return clock.is_open
        except Exception:
            pass

    now = datetime.now()
    if now.weekday() >= 5:  # Weekend
        return False
    market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)
    return market_open <= now <= market_close


def fetch_underlying_features(symbol: str):
    """Downloads 15-minute intraday bars and computes ORB, VWAP, EMA20 Slope, and ATR."""
    df = yf.download(symbol, period="5d", interval="15m", progress=False)
    if df.empty or len(df) < 25:
        return None

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()
    df["EMA20_Slope"] = df["EMA20"] - df["EMA20"].shift(1)

    tr1 = df["High"] - df["Low"]
    tr2 = (df["High"] - df["Close"].shift()).abs()
    tr3 = (df["Low"] - df["Close"].shift()).abs()
    df["TR"] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df["ATR14"] = df["TR"].rolling(window=14).mean()

    today_str = df.index[-1].strftime("%Y-%m-%d")
    df_today = df[df.index.strftime("%Y-%m-%d") == today_str].copy()
    if len(df_today) < 2:
        return None

    cum_vol = df_today["Volume"].cumsum()
    cum_pv = (
        (df_today["High"] + df_today["Low"] + df_today["Close"])
        / 3.0
        * df_today["Volume"]
    ).cumsum()
    df_today["VWAP"] = cum_pv / np.where(cum_vol == 0, 1, cum_vol)

    first_bars = df_today.iloc[:2]  # First two 15m bars = 30m ORB
    orb_high = float(first_bars["High"].max())
    orb_low = float(first_bars["Low"].min())
    latest = df_today.iloc[-1]

    return {
        "close": float(latest["Close"]),
        "vwap": float(latest["VWAP"]),
        "orb_high": orb_high,
        "orb_low": orb_low,
        "ema20": float(latest["EMA20"]),
        "ema20_slope": float(latest["EMA20_Slope"]),
        "atr": float(latest["ATR14"]),
    }


def select_research_contract(
    symbol: str, spot: float, contract_type: ContractType
):
    """Selects active contract matching 0.60-0.75 Delta with low spread."""
    if not trading_client or not data_client:
        return None

    today = date.today()
    is_call = contract_type == ContractType.CALL
    strike_min = spot * 0.95 if is_call else spot * 0.98
    strike_max = spot * 1.02 if is_call else spot * 1.05

    req = GetOptionContractsRequest(
        underlying_symbols=[symbol],
        status="active",
        type=contract_type,
        expiration_date_gte=today + timedelta(days=MIN_DTE),
        expiration_date_lte=today + timedelta(days=MAX_DTE),
        strike_price_gte=str(round(strike_min, 2)),
        strike_price_lte=str(round(strike_max, 2)),
        limit=50,
    )

    try:
        res = trading_client.get_option_contracts(req)
        if not res.option_contracts:
            return None

        symbols = [c.symbol for c in res.option_contracts]
        snaps = data_client.get_option_snapshot(
            OptionSnapshotRequest(symbol_or_symbols=symbols)
        )

        candidates = []
        for c in res.option_contracts:
            snap = snaps.get(c.symbol)
            if not snap or not snap.latest_quote:
                continue

            bid = float(snap.latest_quote.bid_price)
            ask = float(snap.latest_quote.ask_price)
            if bid <= 0.05 or ask <= 0:
                continue

            mid = round((bid + ask) / 2.0, 2)
            rel_spread = (ask - bid) / mid
            dte = (c.expiration_date - today).days
            strike = float(c.strike_price)
            delta = calculate_delta(spot, strike, dte, is_call=is_call)

            if rel_spread > MAX_RELATIVE_SPREAD:
                continue
            if abs(abs(delta) - TARGET_DELTA) > DELTA_TOLERANCE:
                continue

            candidates.append({
                "symbol": c.symbol,
                "strike": strike,
                "delta": abs(delta),
                "bid": bid,
                "ask": ask,
                "mid": mid,
                "spread_pct": rel_spread,
                "dte": dte,
            })

        if not candidates:
            return None

        return min(candidates, key=lambda x: abs(x["delta"] - TARGET_DELTA))

    except Exception as e:
        print(f"⚠️ Contract selection error on {symbol}: {e}")
        return None


def calculate_position_qty(
    equity: float, estimated_loss_per_contract: float
) -> int:
    risk_budget = equity * RISK_PER_TRADE_PERCENT
    qty = int(risk_budget // max(estimated_loss_per_contract, 50.0))
    return max(1, qty)


def check_orb_revalidation(
    symbol: str, setup_state: dict, latest_15m_close: float, max_wait_bars: int = 2
) -> dict:
    """
    Evaluates an ARMED setup at each 15-minute bar close.
    Disarms stale trades or false breakouts that slipped back inside the range.
    """
    if setup_state.get("status") != "ARMED":
        return setup_state

    direction = setup_state.get("direction")
    orb_high = setup_state.get("orb_high", 0.0)
    orb_low = setup_state.get("orb_low", 0.0)
    bars_elapsed = setup_state.get("bars_elapsed", 0) + 1
    setup_state["bars_elapsed"] = bars_elapsed

    # 1. Closed back inside 30m ORB (Breakout Failure)
    if direction == "CALL" and latest_15m_close < orb_high:
        setup_state["status"] = "DISARMED"
        setup_state["audit_reason"] = (
            f"Failed breakout: 15m closed back inside range at ${latest_15m_close:.2f} "
            f"(ORB High: ${orb_high:.2f})"
        )
        return setup_state

    if direction == "PUT" and latest_15m_close > orb_low:
        setup_state["status"] = "DISARMED"
        setup_state["audit_reason"] = (
            f"Failed breakdown: 15m closed back inside range at ${latest_15m_close:.2f} "
            f"(ORB Low: ${orb_low:.2f})"
        )
        return setup_state

    # 2. Time-to-Live Expired (stalled for 2 bars / 30m without fill)
    if bars_elapsed >= max_wait_bars:
        setup_state["status"] = "EXPIRED"
        setup_state["audit_reason"] = f"TTL Expired: Unfilled after {bars_elapsed} bars (30m window)"
        return setup_state

    return setup_state


def run_continuous_risk_loop():
    """Checks stops, targets, and cleans up disarmed pending orders."""
    now_str = datetime.now().strftime("%H:%M:%S")

    # 1. Auto-Flatten at 15:45 EDT
    if now_str >= FLATTEN_TIME_STR:
        if trading_client:
            try:
                positions = trading_client.get_all_positions()
                if positions:
                    print(
                        f"\n🛑 [EOD CUTOFF] {now_str} >= {FLATTEN_TIME_STR}. Liquidating intraday trades."
                    )
                    trading_client.close_all_positions(cancel_orders=True)
                    active_trades.clear()
                    pending_setups.clear()
            except Exception as e:
                print(f"⚠️ Flatten error: {e}")
        return

    # 2. Revalidate and purge pending / armed setups
    for sym in list(pending_setups.keys()):
        setup = pending_setups[sym]
        feat = fetch_underlying_features(sym)
        if not feat:
            continue

        updated = check_orb_revalidation(sym, setup, feat["close"])
        if updated.get("status") in ["DISARMED", "EXPIRED"]:
            print(f"\n⚪ [{updated['status']}] {sym} - {updated.get('audit_reason')}")
            # Cancel pending limit order at Alpaca if order was placed
            order_id = updated.get("order_id")
            if order_id and trading_client:
                try:
                    trading_client.cancel_order_by_id(order_id)
                    print(f"   🗑️ Canceled pending Alpaca order {order_id} for {sym}")
                except Exception as ce:
                    print(f"   ⚠️ Could not cancel order {order_id}: {ce}")
            del pending_setups[sym]

    # 3. Evaluate active open positions
    for sym in list(active_trades.keys()):
        trade = active_trades[sym]
        try:
            tk = yf.Ticker(sym)
            fast = getattr(tk, "fast_info", {})
            current_spot = float(getattr(fast, "last_price", 0.0))
            if current_spot <= 0:
                continue

            hit_stop = (
                (current_spot <= trade["stop"])
                if trade["direction"] == "CALL"
                else (current_spot >= trade["stop"])
            )
            hit_target = (
                (current_spot >= trade["target"])
                if trade["direction"] == "CALL"
                else (current_spot <= trade["target"])
            )

            if hit_stop or hit_target:
                tag = "🎯 [TARGET HIT]" if hit_target else "🚨 [STOP HIT]"
                print(f"\n{tag} {sym} @ ${current_spot:.2f} (Exit: {trade['contract']})")
                if trading_client:
                    trading_client.close_position(trade["contract"])

                result_r = 2.0 if hit_target else -1.0
                rl.log_shadow_record(
                    ticker=sym,
                    action="TRADE_EXIT",
                    spot_price=current_spot,
                    orb_high=trade.get("orb_h", current_spot),
                    orb_low=trade.get("orb_l", current_spot),
                    vwap=current_spot,
                    ema20=current_spot,
                    ema_slope=0.0,
                    atr=trade.get("atr", 1.0),
                    rvol_ratio=1.0,
                    rvol_percentile=50.0,
                    rvol_zscore=0.0,
                    spy_score=50.0,
                    qqq_score=50.0,
                    sector_etf="SPY",
                    sector_score=50.0,
                    rs_market=0.0,
                    rs_sector=0.0,
                    volatility_regime="NORMAL",
                    alpha_score=trade.get("alpha_score", 50.0),
                    alpha_breakdown={},
                    contract_symbol=trade["contract"],
                    delta=TARGET_DELTA,
                    dte=trade.get("dte", 5),
                    bid=trade.get("entry_mid", 1.0),
                    ask=trade.get("entry_mid", 1.0),
                    spread_pct=trade.get("spread_pct", 2.0),
                    execution_score=trade.get("exec_score", 85.0),
                    trade_taken=True,
                    entry_price=trade["entry_spot"],
                    exit_price=current_spot,
                    result_r=result_r,
                )
                del active_trades[sym]

        except Exception as err:
            print(f"⚠️ Monitoring check error on {sym}: {err}")


def scan_alpha_signals():
    """Evaluates 30m ORB signals for both CALL and PUT setups."""
    now = datetime.now()
    if now.hour == 9 and now.minute < 30:
        return

    print(f"\n========================================================")
    print(f"📈 Scanning Universe at: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"========================================================")

    equity = 100000.0  # Default fallback if client is offline
    if trading_client:
        try:
            account = trading_client.get_account()
            equity = float(account.equity)
            positions = trading_client.get_all_positions()
            if len(positions) >= MAX_CONCURRENT_POSITIONS:
                print(
                    f"⚪ Max positions ({MAX_CONCURRENT_POSITIONS}) reached. Skipping entries."
                )
                return
        except Exception as e:
            print(f"⚠️ Account fetch error: {e}")
            return

    for ticker in UNIVERSE:
        if ticker in active_trades or ticker in pending_setups:
            continue

        feat = fetch_underlying_features(ticker)
        if not feat:
            continue

        spot = feat["close"]
        vwap = feat["vwap"]
        orb_h = feat["orb_high"]
        orb_l = feat["orb_low"]
        slope = feat["ema20_slope"]
        atr = feat["atr"]

        alpha_info = ae.compute_alpha_score(ticker)
        alpha_score = alpha_info.get("alpha_score", 50.0)
        bd = alpha_info.get("breakdown", {})
        rvol = alpha_info.get("rvol_metrics", {})
        reg = alpha_info.get("regime_metrics", {})

        is_bullish = (spot > orb_h) and (spot > vwap) and (slope > 0)
        is_bearish = (spot < orb_l) and (spot < vwap) and (slope < 0)

        if not (is_bullish or is_bearish):
            continue

        direction = "CALL" if is_bullish else "PUT"
        contract_type = ContractType.CALL if is_bullish else ContractType.PUT

        match = select_research_contract(ticker, spot, contract_type)
        if not match:
            continue

        # Dynamic ATR targets
        if is_bullish:
            stop_level = round(spot - (1.0 * atr), 2)
            target_level = round(spot + (2.0 * atr), 2)
        else:
            stop_level = round(spot + (1.0 * atr), 2)
            target_level = round(spot - (2.0 * atr), 2)

        qty = calculate_position_qty(
            equity, estimated_loss_per_contract=atr * 100 * TARGET_DELTA
        )

        tag = "🚀 [BULLISH ORB]" if is_bullish else "🔻 [BEARISH ORB]"
        print(f"{tag} {ticker} | Spot: ${spot:.2f} | Alpha Score: {alpha_score}/100")
        print(
            f"   Selected: {match['symbol']} (Delta: {match['delta']:.2f}, Mid: ${match['mid']:.2f})"
        )

        order_id = None
        if trading_client:
            try:
                order = LimitOrderRequest(
                    symbol=match["symbol"],
                    qty=qty,
                    side=OrderSide.BUY,
                    time_in_force=TimeInForce.DAY,
                    limit_price=match["mid"],
                )
                res = trading_client.submit_order(order)
                order_id = res.id
            except Exception as oe_err:
                print(f"⚠️ Order submission error for {ticker}: {oe_err}")
                continue

        # Register setup in pending_setups with revalidation state
        pending_setups[ticker] = {
            "contract": match["symbol"],
            "direction": direction,
            "entry_spot": spot,
            "entry_mid": match["mid"],
            "stop": stop_level,
            "target": target_level,
            "orb_high": orb_h,
            "orb_low": orb_l,
            "atr": atr,
            "alpha_score": alpha_score,
            "exec_score": 88.0,
            "dte": match.get("dte", 5),
            "spread_pct": match["spread_pct"] * 100.0,
            "order_id": order_id,
            "status": "ARMED",
            "bars_elapsed": 0,
        }

        # Log Shadow Record
        rl.log_shadow_record(
            ticker=ticker,
            action="TRADE_ARMED",
            spot_price=spot,
            orb_high=orb_h,
            orb_low=orb_l,
            vwap=vwap,
            ema20=feat["ema20"],
            ema_slope=slope,
            atr=atr,
            rvol_ratio=rvol.get("ratio", 1.0),
            rvol_percentile=rvol.get("percentile", 50.0),
            rvol_zscore=rvol.get("zscore", 0.0),
            spy_score=reg.get("spy_score", 50.0),
            qqq_score=reg.get("qqq_score", 50.0),
            sector_etf=reg.get("sector_etf", "SPY"),
            sector_score=reg.get("sector_score", 50.0),
            rs_market=reg.get("rs_market", 0.0),
            rs_sector=reg.get("rs_sector", 0.0),
            volatility_regime=reg.get("volatility_regime", "NORMAL"),
            alpha_score=alpha_score,
            alpha_breakdown=bd,
            contract_symbol=match["symbol"],
            delta=match["delta"],
            dte=match.get("dte", 5),
            bid=match["bid"],
            ask=match["ask"],
            spread_pct=match["spread_pct"] * 100.0,
            execution_score=88.0,
            trade_taken=True,
            entry_price=spot,
        )


if __name__ == "__main__":
    print("🤖 Research Momentum Options Bot Active (Production Shadow Mode).")

    while True:
        try:
            if not is_regular_market_hours():
                print(f"\n🌙 Outside Regular Market Hours. Standby polling...")
                time.sleep(120)
                continue

            run_continuous_risk_loop()

            now = datetime.now()
            if now.minute in [0, 15, 30, 45] and now.second <= 15:
                scan_alpha_signals()
                time.sleep(20)

            time.sleep(10)

        except KeyboardInterrupt:
            print("\n🛑 Bot terminated.")
            break
        except Exception as e:
            print(f"⚠️ Main loop error: {e}")
            time.sleep(15)