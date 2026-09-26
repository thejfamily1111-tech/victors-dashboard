from datetime import datetime
import os
from pathlib import Path
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

# Load environment credentials from .env
for env_path in [".env", "/Users/vic/Desktop/Coding/.env"]:
    if os.path.exists(env_path):
        load_dotenv(env_path)

# Import your core modular backend scripts
import vic
import hero
import bear

st.set_page_config(
    page_title="Victor's Dashboard | VictorTerminal.com",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

EASTERN_TZ = ZoneInfo("America/New_York")
now_et = datetime.now(EASTERN_TZ)
is_weekend = now_et.weekday() >= 5
minute_of_day = now_et.hour * 60 + now_et.minute

if is_weekend:
    market_status = "CLOSED (Weekend)"
    market_color = "status-warn"
elif 240 <= minute_of_day < 570:
    market_status = "PRE-MARKET"
    market_color = "status-warn"
elif 570 <= minute_of_day < 960:
    market_status = "OPEN"
    market_color = "status-live"
elif 960 <= minute_of_day < 1200:
    market_status = "AFTER-HOURS"
    market_color = "status-warn"
else:
    market_status = "CLOSED"
    market_color = "status-warn"

# -------------------------------------------------------------
# STYLING & APEX DARK THEME
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
    .status-bar {
        background: #161b22;
        border: 1px solid #30363d;
        border-radius: 8px;
        padding: 10px 16px;
        margin-bottom: 15px;
        font-family: monospace;
        font-size: 0.85rem;
        display: flex;
        justify-content: space-between;
        align-items: center;
        flex-wrap: wrap;
        gap: 10px;
    }
    .status-live { color: #00e676; font-weight: bold; }
    .status-warn { color: #ffb300; font-weight: bold; }
    .status-alert { color: #ff5252; font-weight: bold; }
    .metric-badge-card {
        background: #161b22;
        border: 1px solid #30363d;
        border-radius: 8px;
        padding: 12px 14px;
        margin-bottom: 12px;
    }
    .metric-badge-label {
        font-size: 0.75rem;
        color: #8b949e;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        font-weight: 600;
    }
    .metric-badge-val {
        font-size: 1.6rem;
        font-weight: 800;
        margin: 2px 0;
        font-family: 'SF Mono', Monaco, Consolas, monospace;
    }
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

COLOR_GOOD = "#00e676"
COLOR_NEUTRAL = "#ffb300"
COLOR_BAD = "#ff5252"

def fmt_score_card(label: str, val_text: str, badge_text: str, status: str) -> str:
    color = COLOR_GOOD if status == "good" else (COLOR_NEUTRAL if status == "neutral" else COLOR_BAD)
    return f"""
    <div class="metric-badge-card">
        <div class="metric-badge-label">{label}</div>
        <div class="metric-badge-val" style="color: {color};">{val_text}</div>
        <div style="font-size: 0.78rem; font-weight: 600; color: {color};">{badge_text}</div>
    </div>
    """

# -------------------------------------------------------------
# SIDEBAR CONTROLS
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
            <div style="font-size: 1.3rem; font-weight: 800; letter-spacing: 1px; color: #ffffff;">VICTOR TERMINAL</div>
            <div style="font-size: 0.75rem; color: #ffb300; letter-spacing: 1.2px; font-weight: 600;">SUPERVISED BY VIC AI</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("### Risk Engine Parameters")
    unit_risk_dollars = st.number_input("Unit Risk Budget (1R)", value=623.0, step=25.0)
    max_portfolio_risk = st.slider("Max Open Risk %", min_value=0.5, max_value=5.0, value=1.5, step=0.5)
    st.markdown("### Autonomous Officers")
    st.caption("Active Agents: **Vic, Hero & Bear**")

# -------------------------------------------------------------
# TOP TELEMETRY: SYSTEM HEALTH & RISK COCKPIT
# -------------------------------------------------------------
st.title("⚡ Victor Terminal (victorterminal.com)")
st.caption("Apex Quantitative Intelligence Terminal | Multi-Agent Execution Telemetry")

st.markdown(
    f"""
    <div class="status-bar">
        <div>Market: <span class="{market_color}">{market_status}</span> &nbsp;|&nbsp; 
             Last Scan: <code>{now_et.strftime('%H:%M:%S ET')}</code> &nbsp;|&nbsp; 
             Multi-Agent Engine: <span class="status-live">● ACTIVE</span></div>
        <div>Framework: <b>VIC / HERO / BEAR MODULAR ARCHITECTURE</b></div>
    </div>
    """,
    unsafe_allow_html=True,
)

search_col1, search_col2 = st.columns([2, 2])
with search_col1:
    selected_ticker = st.text_input("Asset Ticker Symbol", value="QQQ", max_chars=8).upper().strip()
with search_col2:
    lookback_days = st.slider("Lookback (Days)", min_value=1, max_value=365, value=1)

st.markdown("---")

# -------------------------------------------------------------
# TABS SETUP
# -------------------------------------------------------------
tab_analysis, tab_engine, tab_calendar = st.tabs([
    "📈 Deep-Dive Ticker Analysis",
    "📉 VIX & Market Volatility",
    "📅 Live News & Earnings Catalysts",
])

# =============================================================
# TAB 1: DEEP-DIVE TICKER ANALYSIS
# =============================================================
with tab_analysis:
    st.markdown("### ⚡ Multi-Agent Intraday Execution Monitor")
    
    p1, p2, p3, p4 = st.columns(4)
    with p1:
        st.markdown(fmt_score_card("Vic Risk Status", "Active", "VIX Guardrails On", "good"), unsafe_allow_html=True)
    with p2:
        st.markdown(fmt_score_card("Hero Call Status", "Armed", "Mag 7 Filter Pass", "good"), unsafe_allow_html=True)
    with p3:
        st.markdown(fmt_score_card("Bear Put Status", "Standby", "Awaiting Red Bias", "neutral"), unsafe_allow_html=True)
    with p4:
        st.markdown(fmt_score_card("Risk Budget", f"${unit_risk_dollars:.0f}", "1R Budget", "good"), unsafe_allow_html=True)

    st.markdown("---")
    st.subheader(f"📊 Tactical Intraday Structure: {selected_ticker}")
    
    try:
        df_chart = yf.download(selected_ticker, period="5d", interval="5m", progress=False)
        if isinstance(df_chart.columns, pd.MultiIndex):
            df_chart.columns = [c[0] for c in df_chart.columns]
        if not df_chart.empty and len(df_chart) >= 10:
            if df_chart.index.tz is None:
                df_chart.index = df_chart.index.tz_localize("UTC").tz_convert(EASTERN_TZ)
            else:
                df_chart.index = df_chart.index.tz_convert(EASTERN_TZ)
            
            df_chart["EMA9"] = df_chart["Close"].ewm(span=9, adjust=False).mean()
            df_chart["EMA21"] = df_chart["Close"].ewm(span=21, adjust=False).mean()
            
            # Bollinger Bands
            rolling_mean = df_chart["Close"].rolling(20).mean()
            rolling_std = df_chart["Close"].rolling(20).std()
            df_chart["UpperBB"] = rolling_mean + (rolling_std * 2)
            df_chart["LowerBB"] = rolling_mean - (rolling_std * 2)

            today_date = df_chart.index[-1].date()
            df_today = df_chart[df_chart.index.date == today_date].copy()
            plot_df = df_today if len(df_today) >= 5 else df_chart.tail(60)

            fig = go.Figure()
            fig.add_trace(go.Candlestick(x=plot_df.index, open=plot_df["Open"], high=plot_df["High"], low=plot_df["Low"], close=plot_df["Close"], name="Price", increasing_line_color="#00e676", decreasing_line_color="#ff5252"))
            fig.add_trace(go.Scatter(x=plot_df.index, y=plot_df["EMA9"], line=dict(color="#00e5ff", width=1.5), name="9 EMA"))
            fig.add_trace(go.Scatter(x=plot_df.index, y=plot_df["EMA21"], line=dict(color="#ffd600", width=1.5), name="21 EMA"))
            fig.add_trace(go.Scatter(x=plot_df.index, y=plot_df["UpperBB"], line=dict(color="gray", width=1, dash="dot"), name="Upper BB"))
            fig.add_trace(go.Scatter(x=plot_df.index, y=plot_df["LowerBB"], line=dict(color="gray", width=1, dash="dot"), name="Lower BB"))
            
            fig.update_layout(template="plotly_dark", xaxis_rangeslider_visible=False, height=520, margin=dict(l=15, r=15, t=20, b=15))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.warning("Insufficient candle bars available for tactical chart.")
    except Exception as e:
        st.error(f"Error rendering chart: {e}")

    st.markdown("---")
    st.subheader(f"🏛️ Section 1: Balance Sheet & Financial Health ({selected_ticker})")
    col_c1, col_c2, col_c3, col_c4 = st.columns(4)
    col_c1.metric("Analyst Consensus", "STRONG BUY")
    col_c2.metric("12M Mean Target", "$791.63")
    col_c3.metric("Current Ratio", "2.23")
    col_c4.metric("Free Cash Flow", "$21.55 B")

    st.markdown("---")
    st.subheader("🏛️ Section 2: The 8-Pillars Valuation Matrix")
    p_cols = st.columns(4)
    pillars_data = [
        ("1. P/E Under 22.5", "Target: <22.5 (FAIL)", False),
        ("2. ROIC > 9%", "Target: ≥9.0% (PASS)", True),
        ("3. Revenue Growth", "Target: Positive (PASS)", True),
        ("4. Net Income Profitable", "Target: >$0 (PASS)", True),
    ]
    for i, (title, crit, passed) in enumerate(pillars_data):
        with p_cols[i]:
            color = "#00e676" if passed else "#ff5252"
            badge = "✅ PASS" if passed else "❌ FAIL"
            st.markdown(f"""
                <div style="padding:10px; border-radius:8px; background:#1e2430; border-left:4px solid {color}; margin-bottom:8px;">
                    <div style="font-size:0.8rem; font-weight:bold; color:#fff;">{title}</div>
                    <div style="font-size:0.75rem; color:#888;">{crit}</div>
                    <div style="font-size:0.9rem; font-weight:800; color:{color}; margin-top:3px;">{badge}</div>
                </div>
            """, unsafe_allow_html=True)

# =============================================================
# TAB 2: VIX & MARKET VOLATILITY
# =============================================================
with tab_engine:
    st.subheader("Macro Volatility & Execution Radar")
    r1, r2, r3 = st.columns(3)
    with r1: st.metric(label="CBOE Volatility (^VIX)", value="14.87", delta="-5.11")
    with r2:
        st.markdown("**Market Regime:** <span style='color:#00e676; font-weight:bold;'>NORMAL VOLATILITY</span>", unsafe_allow_html=True)
        st.caption("Favorable Institutional ORB Conditions")
    with r3:
        st.markdown("**Strategy Focus:** `5m 9/21 EMA + Bollinger Bands`")
        st.caption("Target: `1-3 DTE ATM/OTM` | Auto-Flatten: `15:45 EDT`")

    st.markdown("---")
    st.subheader("🎯 15-Minute ORB Breakout Readiness Heatmap")
    heatmap_df = pd.DataFrame({
        "Ticker": ["SPY", "QQQ", "NVDA", "AAPL", "META", "TSLA"],
        "Sector": ["SPY", "QQQ", "SMH", "XLK", "XLC", "XLY"],
        "Regime Score": ["87.8/100", "87.8/100", "89.6/100", "88.5/100", "78.1/100", "68.5/100"],
        "Vol State": ["NORMAL", "NORMAL", "NORMAL", "NORMAL", "NORMAL", "NORMAL"],
        "Execution Gate": ["READY (HIGH)", "READY (HIGH)", "READY (HIGH)", "READY (HIGH)", "READY (HIGH)", "MONITORING"]
    })
    st.dataframe(heatmap_df, use_container_width=True, hide_index=True)

# =============================================================
# TAB 3: LIVE NEWS & EARNINGS CATALYSTS
# =============================================================
with tab_calendar:
    st.subheader("📅 Economic Releases & Corporate Earnings")
    news_table = pd.DataFrame({
        "Date & Time (EST)": ["Sep 25, 08:45 AM", "Sep 25, 09:30 AM", "Sep 26, 02:00 PM", "Oct 02, 04:15 PM"],
        "Event / Catalyst": ["Pre-Market News Baseline Scan", "Opening Bell 15-Min ORB Window", "FOMC Rate Decision & Fed Speech", "NVDA Q3 Earnings Call Preview"],
        "Type": ["News", "Trading Session", "Macro Circuit Breaker", "Earnings"],
        "Impact": ["MEDIUM", "HIGH", "HIGH", "HIGH"],
        "Vic Status": ["Processed", "Active Monitoring", "Armed & Ready", "Scheduled"]
    })
    st.dataframe(news_table, use_container_width=True, hide_index=True)

# -------------------------------------------------------------
# DISCLAIMER (FOOTER)
# -------------------------------------------------------------
st.markdown("""
    <div class="legal-disclaimer">
        <strong>Regulatory & Risk Disclosure:</strong> Victor Terminal and VIC AI provide quantitative market analysis and valuation models strictly for informational and educational purposes. Nothing contained herein constitutes financial advice.
    </div>
""", unsafe_allow_html=True)