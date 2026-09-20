from datetime import datetime
import os
from dotenv import load_dotenv
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

for path in [
    "/Users/vic/Desktop/Coding/.env",
    "/Users/vic/trading_bot/.env",
    ".env",
]:
  if os.path.exists(path):
    load_dotenv(path)

import economic_calendar as ec
import fundamental_engine as fe
from holly_engine import run_holly_overnight_optimization
import market_barometer as mb

st.set_page_config(
    page_title="Victor's Dashboard",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# -------------------------------------------------------------
# STYLING: HIGH-SPECIFICITY RESPONSIVE CSS & TOOLBAR REMOVAL
# -------------------------------------------------------------
st.markdown(
    """
    <style>
    [data-testid="stToolbar"] {visibility: hidden !important; display: none !important;}
    [data-testid="stDecoration"] {visibility: hidden !important; display: none !important;}
    [data-testid="stStatusWidget"] {visibility: hidden !important; display: none !important;}
    header[data-testid="stHeader"] {visibility: hidden !important; display: none !important;}
    #MainMenu {visibility: hidden !important; display: none !important;}
    footer {visibility: hidden !important; display: none !important;}
    .stAppToolbar {visibility: hidden !important; display: none !important;}

    /* Force Vertical Tab Stacking on Mobile Screens */
    @media (max-width: 768px) {
        div[data-baseweb="tab-list"],
        div[role="tablist"],
        .stTabs [data-baseweb="tab-list"] {
            display: flex !important;
            flex-direction: column !important;
            flex-wrap: wrap !important;
            gap: 10px !important;
            width: 100% !important;
            min-width: 100% !important;
        }
        div[data-baseweb="tab-list"] > button,
        div[role="tablist"] > button,
        .stTabs [data-baseweb="tab-list"] button {
            width: 100% !important;
            max-width: 100% !important;
            flex: 1 1 100% !important;
            text-align: center !important;
            justify-content: center !important;
            padding: 12px 14px !important;
            border-radius: 8px !important;
            background: #161b22 !important;
            border: 1px solid #30363d !important;
            margin: 0 !important;
        }
        div[data-baseweb="tab-list"] > button[aria-selected="true"],
        div[role="tablist"] > button[aria-selected="true"],
        .stTabs [data-baseweb="tab-list"] button[aria-selected="true"] {
            border-color: #ff4b4b !important;
            background: #21262d !important;
            box-shadow: 0 0 10px rgba(255, 75, 75, 0.25) !important;
        }
        div[data-baseweb="tab-highlight"] {
            display: none !important;
        }
    }

    /* Unit Suffix Labels for Simulator Inputs */
    .unit-tag {
        font-size: 0.72rem;
        color: #8b949e;
        font-weight: 600;
        margin-bottom: 2px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }

    /* Footer Legal Disclaimer */
    .legal-disclaimer {
        margin-top: 50px;
        padding: 16px 20px;
        border-top: 1px solid #2a3447;
        font-size: 0.75rem;
        color: #8b949e;
        line-height: 1.5;
        text-align: center;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# -------------------------------------------------------------
# ACCESS GATE (PIN: Tactical)
# -------------------------------------------------------------
ACCESS_PIN = os.getenv("DASHBOARD_PIN", "Tactical")

if "authenticated" not in st.session_state:
  st.session_state.authenticated = False

if not st.session_state.authenticated:
  st.markdown(
      """
        <div style="max-width: 420px; margin: 80px auto; padding: 30px; background: #1a1e29; border-radius: 16px; border: 1px solid #2a3447; text-align: center;">
            <div style="font-size: 32px; margin-bottom: 10px;">⚡</div>
            <h2 style="color: #fff; margin-bottom: 6px;">Victor's Dashboard</h2>
            <p style="color: #8e9bb0; font-size: 0.85rem; margin-bottom: 24px;">Apex Quantitative Intelligence Terminal</p>
        </div>
    """,
      unsafe_allow_html=True,
  )

  col1, col2, col3 = st.columns([1, 1.2, 1])
  with col2:
    pin_input = st.text_input(
        "Enter Access PIN", type="password", placeholder="••••••••"
    )
    if st.button("Authenticate Session", use_container_width=True):
      if pin_input == ACCESS_PIN:
        st.session_state.authenticated = True
        st.rerun()
      else:
        st.error("Invalid PIN. Access denied.")
  st.stop()

# -------------------------------------------------------------
# SIDEBAR CONTROLS & BRANDING
# -------------------------------------------------------------
with st.sidebar:
  logo_path = "avatar_logo.png"
  if os.path.exists(logo_path):
    c_left, c_mid, c_right = st.columns([1, 4, 1])
    with c_mid:
      st.image(logo_path, use_container_width=True)

  st.markdown(
      """
        <div style="text-align: center; margin-top: -10px; margin-bottom: 20px;">
            <div style="font-size: 1.3rem; font-weight: 800; letter-spacing: 1px; color: #ffffff;">VICTOR'S DASHBOARD</div>
            <div style="font-size: 0.75rem; color: #f39c12; letter-spacing: 1.2px; font-weight: 600;">APEX INTELLIGENCE TERMINAL</div>
        </div>
    """,
      unsafe_allow_html=True,
  )

  if st.button("Lock Terminal", use_container_width=True):
    st.session_state.authenticated = False
    st.rerun()

# -------------------------------------------------------------
# TOP HEADER BAR & TICKER CONTROLS (MOBILE & DESKTOP)
# -------------------------------------------------------------
st.title("⚡ Victor's Dashboard")
st.caption(
    "Apex Quantitative Intelligence Terminal | Live Confluence & Valuation"
    " Engine"
)

# Responsive Top-Level Input Bar
search_col1, search_col2 = st.columns([2, 2])
with search_col1:
  selected_ticker = (
      st.text_input("Asset Ticker Symbol", value="META", max_chars=8)
      .upper()
      .strip()
  )
with search_col2:
  lookback_days = st.slider(
      "Lookback (Days)", min_value=30, max_value=365, value=180
  )

st.markdown("---")

tab_analysis, tab_engine, tab_calendar = st.tabs([
    "📈 Deep-Dive Ticker Analysis",
    "🎯 Intraday Options Engine",
    "📅 Catalysts & Macro Schedule",
])

# =============================================================
# TAB 1: DEEP-DIVE TICKER ANALYSIS
# =============================================================
with tab_analysis:

  # --- Hero AI Quantitative Engine ---
  with st.expander(
      "⚡ Hero AI Active Strategies (Overnight Quantitative Optimization)"
  ):
    st.caption(
        "Hero AI simulates intraday setups across momentum universe and filters"
        " by >60% Win Rate & >1.5 Profit Factor."
    )
    if st.button(
        "Run Hero AI Strategy Screen",
        key="btn_hero_screen",
        use_container_width=True,
    ):
      with st.spinner(
          "Hero AI simulating intraday setups & testing parameter gates..."
      ):
        universe = ["SPY", "QQQ", "NVDA", "AAPL", "META", "TSLA"]
        qualified = run_holly_overnight_optimization(universe)

        if not qualified.empty:
          st.dataframe(
              qualified[[
                  "Ticker",
                  "Strategy",
                  "Stop (xATR)",
                  "Target (xATR)",
                  "Trades",
                  "Win Rate (%)",
                  "Profit Factor",
                  "Expectancy ($)",
              ]],
              use_container_width=True,
          )
        else:
          st.info(
              "Market conditions did not yield setups meeting Hero AI's"
              " statistical gates today."
          )

  st.subheader(f"⚡ Technical Confluence: {selected_ticker}")

  try:
    df = yf.download(
        selected_ticker,
        period=f"{lookback_days}d",
        interval="1d",
        progress=False,
    )
    if isinstance(df.columns, pd.MultiIndex):
      df.columns = df.columns.get_level_values(0)

    if not df.empty:
      df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()
      df["EMA50"] = df["Close"].ewm(span=50, adjust=False).mean()
      last_close = float(df["Close"].iloc[-1])

      m1, m2, m3, m4 = st.columns(4)
      m1.metric("Market Price", f"${last_close:.2f}")
      m2.metric("Apex Verdict", "MONITORING", "Setup Active")
      m3.metric("Setup Quality", "75/100")
      m4.metric("Active Pattern", "Momentum Continuation")

      fig = go.Figure()
      fig.add_trace(
          go.Candlestick(
              x=df.index,
              open=df["Open"],
              high=df["High"],
              low=df["Low"],
              close=df["Close"],
              name="Price",
          )
      )
      fig.add_trace(
          go.Scatter(
              x=df.index,
              y=df["EMA20"],
              line=dict(color="#00bc8c", width=1.5),
              name="20 EMA",
          )
      )
      fig.add_trace(
          go.Scatter(
              x=df.index,
              y=df["EMA50"],
              line=dict(color="#f39c12", width=1.5),
              name="50 EMA",
          )
      )
      fig.update_layout(
          template="plotly_dark",
          xaxis_rangeslider_visible=False,
          height=450,
          margin=dict(l=10, r=10, t=10, b=10),
      )
      st.plotly_chart(fig, use_container_width=True)

  except Exception as e:
    st.error(f"Error loading {selected_ticker}: {e}")

  with st.spinner(
      f"Extracting balance sheet, forecast, and 8-pillars data for"
      f" {selected_ticker}..."
  ):
    fund = fe.get_company_fundamentals(selected_ticker)

  # ---------------------------------------------------------
  # SECTION 1: BALANCE SHEET & 12-MONTH MARKET FORECAST
  # ---------------------------------------------------------
  st.markdown("---")
  st.subheader(
      "🏛️ Section 1: Balance Sheet, Liquidity & 12-Month Market Forecast:"
      f" {selected_ticker}"
  )

  st.markdown("##### 🎯 12-Month Wall Street Consensus Forecast")
  fc = fund.get(
      "forecast_12m",
      {
          "target_mean": fund.get("current_price", 0.0),
          "target_high": fund.get("current_price", 0.0),
          "target_low": fund.get("current_price", 0.0),
          "upside_mean_pct": 0.0,
          "recommendation": "N/A",
      },
  )

  f1, f2, f3, f4 = st.columns(4)
  f1.metric(
      "12M Mean Target",
      f"${fc['target_mean']:.2f}",
      delta=f"{fc['upside_mean_pct']:+.1f}% Return",
  )
  f2.metric("Analyst Consensus", str(fc["recommendation"]))
  f3.metric("12M High Target", f"${fc['target_high']:.2f}")
  f4.metric("12M Low Target", f"${fc['target_low']:.2f}")

  st.markdown("##### 💼 Balance Sheet Health & Liquidity Core")
  col_c1, col_c2, col_c3, col_c4 = st.columns(4)
  col_c1.metric("Total Cash & Equivalents", f"${fund['total_cash'] / 1e9:.2f} B")
  col_c2.metric("Total Debt (Liabilities)", f"${fund['total_debt'] / 1e9:.2f} B")
  net_val = fund["net_cash"] / 1e9
  col_c3.metric(
      "Net Cash Position",
      f"${net_val:.2f} B",
      delta=f"{'+' if net_val >= 0 else ''}{net_val:.2f} B",
  )
  col_c4.metric(
      "Free Cash Flow (TTM)", f"${fund['free_cash_flow'] / 1e9:.2f} B"
  )

  col_sub1, col_sub2, col_sub3, col_sub4 = st.columns(4)
  col_sub1.metric("Current Ratio (Solvency)", f"{fund['current_ratio']:.2f}")
  col_sub2.metric("Net Income (TTM)", f"${fund['net_income'] / 1e9:.2f} B")
  col_sub3.metric("Total Revenue (TTM)", f"${fund['total_revenue'] / 1e9:.2f} B")
  col_sub4.metric("Shares Outstanding", f"{fund['shares_out'] / 1e6:.1f} M")

  # ---------------------------------------------------------
  # SECTION 2: 8-PILLARS SCORECARD & ASSUMPTION ENGINE
  # ---------------------------------------------------------
  st.markdown("---")
  st.subheader(
      "🏛️ Section 2: The 8-Pillars Valuation Matrix & Assumption Simulator"
  )

  st.markdown(
      "**Scorecard Result:** Passed"
      f" **{fund['passed_pillars_count']}/8 Pillars**"
  )

  p_cols = st.columns(4)
  for i, p in enumerate(fund["pillars"]):
    with p_cols[i % 4]:
      badge = "✅ PASS" if p["Pass"] else "❌ FAIL"
      color = "#00bc8c" if p["Pass"] else "#e74c3c"
      st.markdown(
          f"""
                <div style="padding:10px; border-radius:8px; background:#1e2430; border-left:4px solid {color}; margin-bottom:8px;">
                    <div style="font-size:0.8rem; font-weight:bold; color:#fff;">{p['Pillar']}</div>
                    <div style="font-size:0.75rem; color:#888;">Target: {p['Criteria']}</div>
                    <div style="font-size:0.9rem; font-weight:800; color:{color}; margin-top:3px;">{p.get('Current Value', p.get('CurrentValue', ''))} | {badge}</div>
                </div>
            """,
          unsafe_allow_html=True,
      )

  # Interactive Simulator Inputs with Unit Indicators
  st.markdown(
      "#### 🎮 Interactive Future Assumptions (Play with Low / Mid / High)"
  )
  st.caption(
      "Adjust forward growth, margins, and multiples below to model 5-year"
      " target valuations."
  )

  col_labels, col_hist_vals, col_in_low, col_in_mid, col_in_high = st.columns(
      [2, 1.3, 1.2, 1.2, 1.2]
  )

  with col_labels:
    st.markdown("**Valuation Variable**")
    st.markdown("• Revenue Growth Rate (%/yr)")
    st.markdown("• Profit Margin %")
    st.markdown("• Target Exit P/E Multiple")
    st.markdown("• Desired Annual Return (Discount %)")

  with col_hist_vals:
    st.markdown("**Historical / Current**")
    st.markdown(f"`{fund['rev_growth_1y']*100:+.1f}%` (1Y)")
    st.markdown(f"`{fund['profit_margin']*100:.1f}%`")
    st.markdown(f"`{fund['trailing_pe']:.1f}x`")
    st.markdown("`12.5%` (Baseline)")

  with col_in_low:
    st.markdown("**Low Case**")
    st.markdown("<div class='unit-tag'>Growth (%)</div>", unsafe_allow_html=True)
    g_low = st.number_input(
        "Rev Low",
        value=5.0,
        step=0.5,
        format="%.1f",
        key="glow",
        label_visibility="collapsed",
    )
    st.markdown("<div class='unit-tag'>Margin (%)</div>", unsafe_allow_html=True)
    pm_low = st.number_input(
        "Margin Low",
        value=max(round(fund["profit_margin"] * 100 - 3, 1), 5.0),
        step=0.5,
        format="%.1f",
        key="pmlow",
        label_visibility="collapsed",
    )
    st.markdown(
        "<div class='unit-tag'>Multiple (x)</div>", unsafe_allow_html=True
    )
    pe_low = st.number_input(
        "PE Low",
        value=max(round(fund["trailing_pe"] * 0.7, 1), 12.0),
        step=0.5,
        format="%.1f",
        key="pelow",
        label_visibility="collapsed",
    )
    st.markdown("<div class='unit-tag'>Return (%)</div>", unsafe_allow_html=True)
    ret_low = st.number_input(
        "Ret Low",
        value=12.5,
        step=0.5,
        format="%.1f",
        key="retlow",
        label_visibility="collapsed",
    )

  with col_in_mid:
    st.markdown("**Mid Case**")
    st.markdown("<div class='unit-tag'>Growth (%)</div>", unsafe_allow_html=True)
    g_mid = st.number_input(
        "Rev Mid",
        value=12.0,
        step=0.5,
        format="%.1f",
        key="gmid",
        label_visibility="collapsed",
    )
    st.markdown("<div class='unit-tag'>Margin (%)</div>", unsafe_allow_html=True)
    pm_mid = st.number_input(
        "Margin Mid",
        value=max(round(fund["profit_margin"] * 100, 1), 8.0),
        step=0.5,
        format="%.1f",
        key="pmmid",
        label_visibility="collapsed",
    )
    st.markdown(
        "<div class='unit-tag'>Multiple (x)</div>", unsafe_allow_html=True
    )
    pe_mid = st.number_input(
        "PE Mid",
        value=max(round(fund["trailing_pe"] * 0.85, 1), 18.0),
        step=0.5,
        format="%.1f",
        key="pemid",
        label_visibility="collapsed",
    )
    st.markdown("<div class='unit-tag'>Return (%)</div>", unsafe_allow_html=True)
    ret_mid = st.number_input(
        "Ret Mid",
        value=12.5,
        step=0.5,
        format="%.1f",
        key="retmid",
        label_visibility="collapsed",
    )

  with col_in_high:
    st.markdown("**High Case**")
    st.markdown("<div class='unit-tag'>Growth (%)</div>", unsafe_allow_html=True)
    g_high = st.number_input(
        "Rev High",
        value=20.0,
        step=0.5,
        format="%.1f",
        key="ghigh",
        label_visibility="collapsed",
    )
    st.markdown("<div class='unit-tag'>Margin (%)</div>", unsafe_allow_html=True)
    pm_high = st.number_input(
        "Margin High",
        value=round(fund["profit_margin"] * 100 + 4, 1),
        step=0.5,
        format="%.1f",
        key="pmhigh",
        label_visibility="collapsed",
    )
    st.markdown(
        "<div class='unit-tag'>Multiple (x)</div>", unsafe_allow_html=True
    )
    pe_high = st.number_input(
        "PE High",
        value=max(round(fund["trailing_pe"] * 1.0, 1), 24.0),
        step=0.5,
        format="%.1f",
        key="pehigh",
        label_visibility="collapsed",
    )
    st.markdown("<div class='unit-tag'>Return (%)</div>", unsafe_allow_html=True)
    ret_high = st.number_input(
        "Ret High",
        value=12.5,
        step=0.5,
        format="%.1f",
        key="rethigh",
        label_visibility="collapsed",
    )

  assumptions = {
      "Low": {
          "rev_growth": g_low,
          "profit_margin": pm_low,
          "target_pe": pe_low,
          "desired_return": ret_low,
      },
      "Mid": {
          "rev_growth": g_mid,
          "profit_margin": pm_mid,
          "target_pe": pe_mid,
          "desired_return": ret_mid,
      },
      "High": {
          "rev_growth": g_high,
          "profit_margin": pm_high,
          "target_pe": pe_high,
          "desired_return": ret_high,
      },
  }

  val = fe.calculate_fair_values(fund, assumptions)

  st.markdown("#### 🎯 5-Year Target Prices & Fair Value Buy Targets")
  v1, v2, v3 = st.columns(3)

  with v1:
    st.metric(
        label="Low Case Fair Buy Value",
        value=f"${val['Low']['fair_value_today']:.2f}",
        delta=f"{val['Low']['upside_vs_fair']:+.1f}% vs Spot",
    )
    st.caption(f"Estimated 2031 Price: **${val['Low']['future_price']:.2f}**")

  with v2:
    st.metric(
        label="Mid Case Fair Buy Value",
        value=f"${val['Mid']['fair_value_today']:.2f}",
        delta=f"{val['Mid']['upside_vs_fair']:+.1f}% vs Spot",
    )
    st.caption(f"Estimated 2031 Price: **${val['Mid']['future_price']:.2f}**")

  with v3:
    st.metric(
        label="High Case Fair Buy Value",
        value=f"${val['High']['fair_value_today']:.2f}",
        delta=f"{val['High']['upside_vs_fair']:+.1f}% vs Spot",
    )
    st.caption(f"Estimated 2031 Price: **${val['High']['future_price']:.2f}**")

# =============================================================
# TAB 2: INTRADAY OPTIONS ENGINE & ORB READINESS
# =============================================================
with tab_engine:
  st.subheader("Macro Volatility & Execution Radar")

  regime = mb.get_market_regime()
  c1, c2, c3 = st.columns([1, 2, 2])
  with c1:
    st.metric(
        label="CBOE Volatility (^VIX)",
        value=f"{regime['vix']:.2f}",
        delta=f"{regime['vix_change']:+.2f}",
    )
  with c2:
    badge = regime["badge_color"]
    name = regime["regime"]
    st.markdown(
        f"**Market Regime:** <span style='color:{badge};"
        f" font-weight:bold;'>{name}</span>",
        unsafe_allow_html=True,
    )
    st.caption(regime["note"])
  with c3:
    st.markdown("**Strategy Focus:** `30m ORB + Midpoint Limit`")
    st.caption("Target: `0.60–0.75 Delta` | Auto-Flatten: `15:45 EDT`")

  st.markdown("---")
  st.subheader("🎯 15-Minute ORB Breakout Readiness Heatmap")

  with st.spinner("Scanning universe 15m price action..."):
    readiness_df = mb.get_orb_readiness_matrix()

  if not readiness_df.empty:
    st.dataframe(readiness_df, use_container_width=True, hide_index=True)
  else:
    st.info("Universe price data will refresh on candle close.")

# =============================================================
# TAB 3: CATALYSTS & MACRO SCHEDULE
# =============================================================
with tab_calendar:
  st.subheader("📅 Economic Releases & Corporate Earnings")
  sub1, sub2 = st.tabs(["High-Impact Macro Events", "Universe Earnings Dates"])

  with sub1:
    events_df = ec.get_economic_events(days_forward=30)
    if not events_df.empty:
      st.dataframe(events_df, use_container_width=True, hide_index=True)
    else:
      st.info("No major macro events scheduled in the next 30 days.")

  with sub2:
    with st.spinner("Fetching confirmed earnings dates..."):
      earnings_df = ec.get_universe_earnings(
          ["NVDA", "AAPL", "AMD", "AMZN", "MSFT", "TSLA"]
      )
    if not earnings_df.empty:
      st.dataframe(earnings_df, use_container_width=True, hide_index=True)
    else:
      st.info("No immediate earnings scheduled for active universe.")

# =============================================================
# INSTITUTIONAL LEGAL & REGULATORY DISCLAIMER (FOOTER)
# =============================================================
st.markdown(
    """
    <div class="legal-disclaimer">
        <strong>Regulatory & Risk Disclosure:</strong> Victor Terminal and Hero AI provide quantitative market analysis, backtesting frameworks, and valuation models strictly for informational and educational purposes. Nothing contained herein constitutes financial, investment, legal, or tax advice. Trading equities, options, and futures involves substantial risk of loss and is not suitable for every investor. Past performance and simulated backtest results do not guarantee future returns.
    </div>
""",
    unsafe_allow_html=True,
)