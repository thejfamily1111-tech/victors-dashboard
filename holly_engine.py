import numpy as np
import pandas as pd
import yfinance as yf


def fetch_intraday_data(ticker: str, period="5d", interval="5m") -> pd.DataFrame:
    """Fetch intraday data with technical indicator baselines."""
    df = yf.download(ticker, period=period, interval=interval, progress=False)
    if df.empty:
        return df

    # Flatten MultiIndex columns if present
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # Calculate Intraday ATR (14 periods)
    high_low = df["High"] - df["Low"]
    high_close = (df["High"] - df["Close"].shift()).abs()
    low_close = (df["Low"] - df["Close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df["ATR"] = tr.rolling(14).mean()

    # Calculate VWAP
    typical_price = (df["High"] + df["Low"] + df["Close"]) / 3.0
    df["Cum_Vol"] = df["Volume"].cumsum()
    df["Cum_VP"] = (typical_price * df["Volume"]).cumsum()
    df["VWAP"] = df["Cum_VP"] / df["Cum_Vol"]

    return df.dropna()


def strategy_vwap_bounce(df: pd.DataFrame) -> pd.DataFrame:
    """Strategy 1: Price touches or dips near VWAP, then closes back above."""
    signals = []
    for i in range(1, len(df)):
        prev_row = df.iloc[i - 1]
        curr_row = df.iloc[i]

        # Condition: Previous bar dipped below or near VWAP; current bar bounces back above
        condition = (
            (prev_row["Low"] <= prev_row["VWAP"] * 1.002)
            and (curr_row["Close"] > curr_row["VWAP"])
            and (curr_row["Close"] > curr_row["Open"])
        )

        if condition:
            signals.append(
                {
                    "Timestamp": curr_row.name,
                    "Entry_Price": curr_row["Close"],
                    "ATR": curr_row["ATR"],
                    "Index": i,
                }
            )

    return pd.DataFrame(signals)


def strategy_breakout(df: pd.DataFrame) -> pd.DataFrame:
    """Strategy 2: 20-period High breakout with volume surge."""
    signals = []
    df["High_20"] = df["High"].shift(1).rolling(20).max()
    df["Vol_Mean"] = df["Volume"].shift(1).rolling(20).mean()

    for i in range(20, len(df)):
        curr = df.iloc[i]
        if (curr["Close"] > curr["High_20"]) and (
            curr["Volume"] > curr["Vol_Mean"] * 1.5
        ):
            signals.append(
                {
                    "Timestamp": curr.name,
                    "Entry_Price": curr["Close"],
                    "ATR": curr["ATR"],
                    "Index": i,
                }
            )

    return pd.DataFrame(signals)


def backtest_strategy(
    df: pd.DataFrame,
    signals_df: pd.DataFrame,
    atr_stop_mult=1.0,
    atr_target_mult=2.0,
    max_hold_bars=12,
) -> dict:
    """Simulates trade bracket execution on intraday bars."""
    if signals_df.empty:
        return {
            "Total_Trades": 0,
            "Win_Rate": 0.0,
            "Profit_Factor": 0.0,
            "Total_Return": 0.0,
        }

    pnl_list = []

    for _, sig in signals_df.iterrows():
        idx = int(sig["Index"])
        entry = sig["Entry_Price"]
        stop = entry - (sig["ATR"] * atr_stop_mult)
        target = entry + (sig["ATR"] * atr_target_mult)

        # Slice future bars up to max hold limit
        future_bars = df.iloc[idx + 1 : idx + 1 + max_hold_bars]
        trade_closed = False

        for _, bar in future_bars.iterrows():
            # Check Stop Loss first (conservative evaluation)
            if bar["Low"] <= stop:
                pnl_list.append(stop - entry)
                trade_closed = True
                break
            # Check Profit Target
            if bar["High"] >= target:
                pnl_list.append(target - entry)
                trade_closed = True
                break

        # Time-based exit if neither stop nor target hit
        if not trade_closed and not future_bars.empty:
            final_exit = future_bars.iloc[-1]["Close"]
            pnl_list.append(final_exit - entry)

    if not pnl_list:
        return {
            "Total_Trades": 0,
            "Win_Rate": 0.0,
            "Profit_Factor": 0.0,
            "Total_Return": 0.0,
        }

    wins = [p for p in pnl_list if p > 0]
    losses = [abs(p) for p in pnl_list if p < 0]

    win_rate = (len(wins) / len(pnl_list)) * 100.0
    total_profit = sum(wins)
    total_loss = sum(losses)
    profit_factor = (
        (total_profit / total_loss)
        if total_loss > 0
        else (2.5 if total_profit > 0 else 0.0)
    )

    return {
        "Total_Trades": len(pnl_list),
        "Win_Rate": round(win_rate, 2),
        "Profit_Factor": round(profit_factor, 2),
        "Total_Return": round(sum(pnl_list), 2),
    }


def run_holly_overnight_optimization(universe: list) -> pd.DataFrame:
    """Executes the overnight parameter optimization matrix and applies the Holly Gate filter."""
    strategies = [
        ("VWAP Pullback Bounce", strategy_vwap_bounce),
        ("20-Bar Volume Breakout", strategy_breakout),
    ]

    param_grid = [
        {"atr_stop": 1.0, "atr_target": 1.5},
        {"atr_stop": 1.0, "atr_target": 2.0},
        {"atr_stop": 1.5, "atr_target": 3.0},
    ]

    results = []

    for ticker in universe:
        df = fetch_intraday_data(ticker)
        if df.empty:
            continue

        for strat_name, strat_func in strategies:
            signals = strat_func(df)
            if signals.empty:
                continue

            for params in param_grid:
                metrics = backtest_strategy(
                    df,
                    signals,
                    atr_stop_mult=params["atr_stop"],
                    atr_target_mult=params["atr_target"],
                )

                # The Holly Filter: Require statistical significance, high win rate, and profit factor
                if (
                    metrics["Total_Trades"] >= 5
                    and metrics["Win_Rate"] >= 60.0
                    and metrics["Profit_Factor"] >= 1.5
                ):
                    results.append(
                        {
                            "Ticker": ticker,
                            "Strategy": strat_name,
                            "Stop (xATR)": params["atr_stop"],
                            "Target (xATR)": params["atr_target"],
                            "Trades": metrics["Total_Trades"],
                            "Win Rate (%)": metrics["Win_Rate"],
                            "Profit Factor": metrics["Profit_Factor"],
                            "Expectancy ($)": metrics["Total_Return"],
                            "Status": "ACTIVE FOR NEXT SESSION",
                        }
                    )

    return (
        pd.DataFrame(results).sort_values("Profit Factor", ascending=False)
        if results
        else pd.DataFrame()
    )


if __name__ == "__main__":
    # Test across a sample liquid universe
    test_universe = ["SPY", "QQQ", "NVDA", "AAPL", "META", "TSLA"]
    qualified_trades = run_holly_overnight_optimization(test_universe)

    if qualified_trades.empty:
        print(
            "No strategies passed the Holly filter today (expectancy requirements not met)."
        )
    else:
        print("\n=== HOLLY AI ACTIVE STRATEGIES FOR TOMORROW ===")
        print(qualified_trades.to_string(index=False))