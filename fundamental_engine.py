import yfinance as yf
import pandas as pd
import numpy as np

def get_company_fundamentals(ticker_symbol: str):
    tk = yf.Ticker(ticker_symbol)
    info = tk.info or {}
    
    bs = tk.balance_sheet
    cf = tk.cashflow
    inc = tk.financials

    # 1. Balance Sheet & Liquidity Core
    total_cash = info.get("totalCash", 0) or 0
    total_debt = info.get("totalDebt", 0) or 0
    net_cash = total_cash - total_debt
    free_cash_flow = info.get("freeCashflow", 0) or 0
    total_revenue = info.get("totalRevenue", 0) or 0
    net_income = info.get("netIncomeToCommon", 0) or 0
    current_ratio = info.get("currentRatio", 0.0) or 0.0
    shares_out = info.get("sharesOutstanding", 1) or 1
    current_price = info.get("currentPrice", info.get("regularMarketPrice", 0.0)) or 0.0
    trailing_pe = info.get("trailingPE", 0.0) or 0.0
    forward_pe = info.get("forwardPE", 0.0) or 0.0
    profit_margin = info.get("profitMargins", 0.0) or 0.0
    fcf_margin = (free_cash_flow / total_revenue) if total_revenue > 0 else 0.0
    rev_growth_1y = info.get("revenueGrowth", 0.0) or 0.0

    # 2. 12-Month Wall Street Market Forecast
    target_mean = info.get("targetMeanPrice", info.get("targetMedianPrice", current_price)) or current_price
    target_high = info.get("targetHighPrice", target_mean * 1.15) or (target_mean * 1.15)
    target_low = info.get("targetLowPrice", target_mean * 0.85) or (target_mean * 0.85)
    rec_key = (info.get("recommendationKey", "N/A") or "N/A").upper().replace("_", " ")
    num_analysts = info.get("numberOfAnalystOpinions", 0) or 0
    
    upside_12m = ((target_mean - current_price) / current_price * 100) if current_price > 0 else 0.0

    forecast_12m = {
        "target_mean": float(target_mean),
        "target_high": float(target_high),
        "target_low": float(target_low),
        "upside_mean_pct": float(upside_12m),
        "recommendation": rec_key,
        "analysts_count": int(num_analysts)
    }

    # 3. ROIC Calculation
    try:
        ebit = inc.loc["EBIT"].iloc[0] if "EBIT" in inc.index else net_income * 1.15
        assets = bs.loc["Total Assets"].iloc[0] if "Total Assets" in bs.index else 1
        curr_liab = bs.loc["Current Liabilities"].iloc[0] if "Current Liabilities" in bs.index else 0
        invested_cap = max(assets - curr_liab, 1)
        roic = float(ebit / invested_cap)
    except Exception:
        roic = 0.10

    # 4. 8-Pillars Evaluation
    p1_pe = 0 < trailing_pe < 22.5
    p2_roic = roic >= 0.09
    p3_rev_growth = rev_growth_1y > 0
    p4_net_income = net_income > 0
    p5_fcf_pos = free_cash_flow > 0
    p6_debt_coverage = (total_debt < (free_cash_flow * 5)) if free_cash_flow > 0 else False
    p7_curr_ratio = current_ratio >= 1.2
    p8_margin = profit_margin > 0.10

    pillars = [
        {"Pillar": "1. P/E Under 22.5", "Criteria": "< 22.5", "Current Value": f"{trailing_pe:.1f}x", "Pass": p1_pe},
        {"Pillar": "2. ROIC > 9%", "Criteria": "≥ 9.0%", "Current Value": f"{roic*100:.1f}%", "Pass": p2_roic},
        {"Pillar": "3. Revenue Growth (1Y/5Y)", "Criteria": "Positive Growth", "Current Value": f"{rev_growth_1y*100:+.1f}%", "Pass": p3_rev_growth},
        {"Pillar": "4. Net Income Profitable", "Criteria": "> $0", "Current Value": f"${net_income/1e9:.2f} B", "Pass": p4_net_income},
        {"Pillar": "5. Free Cash Flow Positive", "Criteria": "> $0", "Current Value": f"${free_cash_flow/1e9:.2f} B", "Pass": p5_fcf_pos},
        {"Pillar": "6. Debt Covered by 5Y FCF", "Criteria": "Debt < 5x FCF", "Current Value": f"${total_debt/1e9:.2f}B Debt", "Pass": p6_debt_coverage},
        {"Pillar": "7. Current Ratio ≥ 1.2", "Criteria": "≥ 1.2", "Current Value": f"{current_ratio:.2f}", "Pass": p7_curr_ratio},
        {"Pillar": "8. Profit Margin ≥ 10%", "Criteria": "≥ 10.0%", "Current Value": f"{profit_margin*100:.1f}%", "Pass": p8_margin},
    ]

    return {
        "ticker": ticker_symbol,
        "current_price": float(current_price),
        "total_revenue": total_revenue,
        "net_income": net_income,
        "total_cash": total_cash,
        "total_debt": total_debt,
        "net_cash": net_cash,
        "free_cash_flow": free_cash_flow,
        "current_ratio": current_ratio,
        "shares_out": shares_out,
        "profit_margin": profit_margin,
        "fcf_margin": fcf_margin,
        "trailing_pe": trailing_pe,
        "forward_pe": forward_pe,
        "rev_growth_1y": rev_growth_1y,
        "roic": roic,
        "forecast_12m": forecast_12m,
        "pillars": pillars,
        "passed_pillars_count": sum(1 for p in pillars if p["Pass"])
    }

def calculate_fair_values(fund: dict, assumptions: dict):
    years = 5
    current_rev = max(fund["total_revenue"], 1)
    shares = max(fund["shares_out"], 1)
    
    results = {}
    for case in ["Low", "Mid", "High"]:
        g = assumptions[case]["rev_growth"] / 100.0
        pm = assumptions[case]["profit_margin"] / 100.0
        pe = assumptions[case]["target_pe"]
        discount_rate = assumptions[case]["desired_return"] / 100.0
        
        future_rev = current_rev * ((1 + g) ** years)
        future_earnings = future_rev * pm
        future_market_cap = future_earnings * pe
        future_stock_price = future_market_cap / shares
        
        fair_price_today = future_stock_price / ((1 + discount_rate) ** years)
        
        results[case] = {
            "future_price": round(future_stock_price, 2),
            "fair_value_today": round(fair_price_today, 2),
            "upside_vs_fair": round(((fair_price_today - fund["current_price"]) / fund["current_price"]) * 100, 1) if fund["current_price"] > 0 else 0.0
        }
        
    return results
