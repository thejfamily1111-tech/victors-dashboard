from datetime import datetime
import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf


@st.cache_data(ttl=900)
def get_company_fundamentals(ticker_symbol: str):
  tk = yf.Ticker(ticker_symbol)

  # Fetch info safely
  try:
    info = tk.info or {}
  except Exception:
    info = {}

  # Fallback to fast_info for market price and shares if info is throttled
  fast = getattr(tk, "fast_info", {})
  current_price = (
      float(info.get("currentPrice") or info.get("regularMarketPrice") or 0.0)
      if info
      else 0.0
  )
  if current_price == 0.0 and hasattr(fast, "last_price"):
    current_price = float(fast.last_price or 0.0)

  shares_out = float(info.get("sharesOutstanding") or 1) if info else 1.0
  if shares_out <= 1.0 and hasattr(fast, "shares"):
    shares_out = float(fast.shares or 1.0)

  # Pull Financial Statements
  try:
    bs = tk.balance_sheet
  except Exception:
    bs = pd.DataFrame()

  try:
    inc = tk.financials
  except Exception:
    inc = pd.DataFrame()

  try:
    cf = tk.cashflow
  except Exception:
    cf = pd.DataFrame()

  # Total Revenue Fallback
  total_revenue = float(info.get("totalRevenue") or 0.0) if info else 0.0
  if total_revenue == 0.0 and not inc.empty:
    for rev_key in ["Total Revenue", "Operating Revenue"]:
      if rev_key in inc.index:
        total_revenue = float(inc.loc[rev_key].dropna().iloc[0])
        break

  # Net Income Fallback
  net_income = (
      float(info.get("netIncomeToCommon") or 0.0) if info else 0.0
  )
  if net_income == 0.0 and not inc.empty:
    if "Net Income" in inc.index:
      net_income = float(inc.loc["Net Income"].dropna().iloc[0])

  # Free Cash Flow Fallback
  free_cash_flow = (
      float(info.get("freeCashflow") or 0.0) if info else 0.0
  )
  if free_cash_flow == 0.0 and not cf.empty:
    if "Free Cash Flow" in cf.index:
      free_cash_flow = float(cf.loc["Free Cash Flow"].dropna().iloc[0])

  # Balance sheet cash and debt
  total_cash = float(info.get("totalCash") or 0.0) if info else 0.0
  total_debt = float(info.get("totalDebt") or 0.0) if info else 0.0
  if total_cash == 0.0 and not bs.empty:
    for c_key in [
        "Cash And Cash Equivalents",
        "Cash Cash Equivalents And Short Term Investments",
    ]:
      if c_key in bs.index:
        total_cash = float(bs.loc[c_key].dropna().iloc[0])
        break

  if total_debt == 0.0 and not bs.empty:
    for d_key in ["Total Debt", "Long Term Debt"]:
      if d_key in bs.index:
        total_debt = float(bs.loc[d_key].dropna().iloc[0])
        break

  net_cash = total_cash - total_debt
  current_ratio = float(info.get("currentRatio") or 0.0) if info else 0.0
  trailing_pe = float(info.get("trailingPE") or 0.0) if info else 0.0
  forward_pe = float(info.get("forwardPE") or 0.0) if info else 0.0

  profit_margin = (
      float(info.get("profitMargins") or 0.0) if info else 0.0
  )
  if profit_margin == 0.0 and total_revenue > 0:
    profit_margin = net_income / total_revenue

  fcf_margin = (
      (free_cash_flow / total_revenue) if total_revenue > 0 else 0.0
  )
  rev_growth_1y = (
      float(info.get("revenueGrowth") or 0.0) if info else 0.0
  )

  # 12M Analyst Forecast
  target_mean = (
      float(
          info.get("targetMeanPrice")
          or info.get("targetMedianPrice")
          or current_price
      )
      if info
      else current_price
  )
  target_high = (
      float(info.get("targetHighPrice") or target_mean * 1.15)
      if info
      else target_mean * 1.15
  )
  target_low = (
      float(info.get("targetLowPrice") or target_mean * 0.85)
      if info
      else target_mean * 0.85
  )
  rec_key = (
      str(info.get("recommendationKey") or "N/A")
      .upper()
      .replace("_", " ")
  )
  num_analysts = int(info.get("numberOfAnalystOpinions") or 0)

  upside_12m = (
      ((target_mean - current_price) / current_price * 100.0)
      if current_price > 0
      else 0.0
  )

  forecast_12m = {
      "target_mean": target_mean,
      "target_high": target_high,
      "target_low": target_low,
      "upside_mean_pct": float(upside_12m),
      "recommendation": rec_key,
      "analysts_count": num_analysts,
  }

  # ROIC Calculation
  try:
    ebit = (
        inc.loc["EBIT"].dropna().iloc[0]
        if ("EBIT" in inc.index and not inc.empty)
        else net_income * 1.15
    )
    assets = (
        bs.loc["Total Assets"].dropna().iloc[0]
        if ("Total Assets" in bs.index and not bs.empty)
        else 1
    )
    curr_liab = (
        bs.loc["Current Liabilities"].dropna().iloc[0]
        if ("Current Liabilities" in bs.index and not bs.empty)
        else 0
    )
    invested_cap = max(assets - curr_liab, 1)
    roic = float(ebit / invested_cap)
  except Exception:
    roic = 0.10

  # 8-Pillars Evaluation
  pillars = [
      {
          "Pillar": "1. P/E Under 22.5",
          "Criteria": "< 22.5",
          "Current Value": f"{trailing_pe:.1f}x",
          "Pass": 0 < trailing_pe < 22.5,
      },
      {
          "Pillar": "2. ROIC > 9%",
          "Criteria": "≥ 9.0%",
          "Current Value": f"{roic*100:.1f}%",
          "Pass": roic >= 0.09,
      },
      {
          "Pillar": "3. Revenue Growth (1Y/5Y)",
          "Criteria": "Positive Growth",
          "Current Value": f"{rev_growth_1y*100:+.1f}%",
          "Pass": rev_growth_1y > 0,
      },
      {
          "Pillar": "4. Net Income Profitable",
          "Criteria": "> $0",
          "Current Value": f"${net_income/1e9:.2f} B",
          "Pass": net_income > 0,
      },
      {
          "Pillar": "5. Free Cash Flow Positive",
          "Criteria": "> $0",
          "Current Value": f"${free_cash_flow/1e9:.2f} B",
          "Pass": free_cash_flow > 0,
      },
      {
          "Pillar": "6. Debt Covered by 5Y FCF",
          "Criteria": "Debt < 5x FCF",
          "Current Value": f"${total_debt/1e9:.2f}B Debt",
          "Pass": (total_debt < (free_cash_flow * 5))
          if free_cash_flow > 0
          else False,
      },
      {
          "Pillar": "7. Current Ratio ≥ 1.2",
          "Criteria": "≥ 1.2",
          "Current Value": f"{current_ratio:.2f}",
          "Pass": current_ratio >= 1.2,
      },
      {
          "Pillar": "8. Profit Margin ≥ 10%",
          "Criteria": "≥ 10.0%",
          "Current Value": f"{profit_margin*100:.1f}%",
          "Pass": profit_margin >= 0.10,
      },
  ]

  return {
      "ticker": ticker_symbol,
      "current_price": current_price,
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
      "passed_pillars_count": sum(1 for p in pillars if p["Pass"]),
  }


def calculate_fair_values(fund: dict, assumptions: dict, years: int = 5):
  years = max(int(years), 1)
  current_rev = max(float(fund.get("total_revenue") or 0.0), 1.0)
  shares = max(float(fund.get("shares_out") or 1.0), 1.0)
  spot = float(fund.get("current_price") or 0.0)

  results = {}
  for case in ["Low", "Mid", "High"]:
    g = float(assumptions[case]["rev_growth"]) / 100.0
    pm = float(assumptions[case]["profit_margin"]) / 100.0
    pe = max(float(assumptions[case]["target_pe"]), 1.0)
    discount_rate = float(assumptions[case]["desired_return"]) / 100.0

    future_rev = current_rev * ((1.0 + max(g, -0.90)) ** years)
    future_earnings = future_rev * max(pm, 0.001)
    future_market_cap = future_earnings * pe
    future_stock_price = future_market_cap / shares

    fair_price_today = future_stock_price / (
        (1.0 + max(discount_rate, 0.01)) ** years
    )

    margin_of_safety_pct = (
        ((fair_price_today - spot) / spot * 100.0) if spot > 0 else 0.0
    )
    projected_return_pct = (
        ((future_stock_price - spot) / spot * 100.0) if spot > 0 else 0.0
    )

    results[case] = {
        "future_price": round(future_stock_price, 2),
        "fair_value_today": round(fair_price_today, 2),
        "upside_vs_fair": round(margin_of_safety_pct, 1),
        "total_upside": round(projected_return_pct, 1),
    }

  return results