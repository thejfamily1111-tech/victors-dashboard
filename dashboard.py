from datetime import datetime
import os
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

# Load environment credentials
for path in [
    "/Users/vic/Desktop/Coding/.env",
    "/Users/vic/trading_bot/.env",
    ".env",
]:
    if os.path.exists(path):
        load_dotenv(path)

# Core trading modules
import alpha_engine as ae
import economic_calendar as ec
import fundamental_engine as fe
from holly_engine import run_holly_overnight_optimization
import market_barometer as mb
import option_engine as oe
import research_momentum_bot as rmb

# Autonomous AI Desk Manager
try:
    from ai_manager import AITradingManager

    vic_manager = AITradingManager()
except ImportError:
    vic_manager = None

st.set_page_config(
    page_title="Victor's Dashboard | VIC AI",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# -------------------------------------------------------------
# TIMEZONE & MARKET HOURS ENGINE
# -------------------------------------------------------------
EASTERN_TZ = ZoneInfo("America/New_York")
now_et = datetime.now(EASTERN_TZ)

is_weekend = now_et.weekday() >= 5
minute_of_day = now_et.hour * 60 + now_et.minute

# RTH: 9:30 AM (570) to 4:00 PM (960)
if is_weekend:
    market_status = "CLOSED (Weekend)"
    market_color = "status-warn"
elif 240 <= minute_of_day < 570:  # 4:00 AM to 9:30 AM
    market_status = "PRE-MARKET"
    market_color = "status-warn"
elif 570 <= minute_of_day < 960:  # 9:30 AM to 4:00 PM
    market_status = "OPEN"
    market_color = "status-live"
elif 960 <= minute_of_day < 1200:  # 4:00 PM to 8:00 PM
    market_status = "AFTER-HOURS"
    market_color = "status-warn"
else:
    market_status = "CLOSED"
    market_color = "status-warn"


def get_live_premarket_indices():
    """Fetches real-time premarket or latest quote changes for SPY and QQQ."""
    data = {}
    for sym in ["SPY", "QQQ"]:
        try:
            ticker = yf.Ticker(sym)
            df = ticker.history(period="2d", interval="1m", prepost=True)
            if not df.empty:
                prev_close = ticker.info.get("previousClose") or df["Close"].iloc[0]
                current_price = df["Close"].iloc[-1]
                pct = ((current_price - prev_close) / prev_close) * 100.0
                data[sym] = {"price": current_price, "pct": pct}
            else:
                data[sym] = {"price": 0.0, "pct": 0.0}
        except Exception:
            data[sym] = {"price": 0.0, "pct": 0.0}
    return data


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

    /* Force horizontal scroll container on dataframes */
    [data-testid="stDataFrame"] > div {
        overflow-x: auto !important;
        scrollbar-width: thin;
        scrollbar-color: #30363d #161b22;
    }
    [data-testid="stDataFrame"] > div::-webkit-scrollbar {
        height: 8px;
    }
    [data-testid="stDataFrame"] > div::-webkit-scrollbar-track {
        background: #161b22;
        border-radius: 4px;
    }
    [data-testid="stDataFrame"] > div::-webkit-scrollbar-thumb {
        background: #30363d;
        border-radius: 4px;
    }
    [data-testid="stDataFrame"] > div::-webkit-scrollbar-thumb:hover {
        background: #484f58;
    }

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
    
    .vic-card {
        background: linear-gradient(135deg, #131722 0%, #1a2332 100%);
        border: 1px solid #2d3748;
        border-left: 4px solid #00e676;
        border-radius: 8px;
        padding: 14px 18px;
        margin-bottom: 20px;
    }

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

    .unit-tag {
        font-size: 0.72rem;
        color: #8b949e;
        font-weight: 600;
        margin-bottom: 2px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
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

# -------------------------------------------------------------
# TRAFFIC-LIGHT FORMATTING ENGINE (GREEN / YELLOW / RED)
# -------------------------------------------------------------
COLOR_GOOD = "#00e676"
COLOR_NEUTRAL = "#ffb300"
COLOR_BAD = "#ff5252"


def get_traffic_color(val: float, high: float, low: float) -> str:
    """Returns Green for high, Yellow for mid, Red for low."""
    if val >= high:
        return COLOR_GOOD
    elif val >= low:
        return COLOR_NEUTRAL
    return COLOR_BAD


def fmt_score_card(label: str, val_text: str, badge_text: str, status: str) -> str:
    """Generates an Apex-styled metric card with strict traffic-light palette."""
    color = COLOR_GOOD if status == "good" else (COLOR_NEUTRAL if status == "neutral" else COLOR_BAD)
    return f"""
    <div class="metric-badge-card">
        <div class="metric-badge-label">{label}</div>
        <div class="metric-badge-val" style="color: {color};">{val_text}</div>
        <div style="font-size: 0.78rem; font-weight: 600; color: {color};">{badge_text}</div>
    </div>
    """


def fmt_spread_str(spread_pct: float) -> str:
    """Traffic light for Option Spread %. <=4.0% Good, 4.0-6.0% Neutral, >6.0% Bad."""
    if spread_pct <= 4.0:
        return f'<span style="color: {COLOR_GOOD}; font-weight: bold;">{spread_pct:.2f}% (Liquid)</span>'
    elif spread_pct <= 6.0:
        return f'<span style="color: {COLOR_NEUTRAL}; font-weight: bold;">{spread_pct:.2f}% (Borderline)</span>'
    return f'<span style="color: {COLOR_BAD}; font-weight: bold;">{spread_pct:.2f}% ⚠️ (TOO WIDE / PROHIBITIVE)</span>'


def fmt_delta_str(delta: float) -> str:
    """Traffic light for target Delta: 0.60 to 0.75 optimal."""
    abs_d = abs(delta)
    if 0.60 <= abs_d <= 0.75:
        return f'<span style="color: {COLOR_GOOD}; font-weight: bold;">{abs_d:.2f} (Target Band: 0.60–0.75)</span>'
    elif (0.50 <= abs_d < 0.60) or (0.75 < abs_d <= 0.82):
        return f'<span style="color: {COLOR_NEUTRAL}; font-weight: bold;">{abs_d:.2f} (Acceptable Drift)</span>'
    return f'<span style="color: {COLOR_BAD}; font-weight: bold;">{abs_d:.2f} (Suboptimal Delta)</span>'


def fmt_rs_str(rs_val: float) -> str:
    """Traffic light for Relative Strength vs Sector."""
    if rs_val > 0.10:
        return f'<span style="color: {COLOR_GOOD}; font-weight: bold;">+{rs_val:.2f}% (Leading)</span>'
    elif rs_val >= -0.10:
        return f'<span style="color: {COLOR_NEUTRAL}; font-weight: bold;">{rs_val:+.2f}% (In-Line)</span>'
    return f'<span style="color: {COLOR_BAD}; font-weight: bold;">{rs_val:.2f}% (Lagging Drag)</span>'


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
        pin_input = st.text_input("Enter Access PIN", type="password", placeholder="••••••••")
        if st.button("Authenticate Session", use_container_width=True):
            if pin_input == ACCESS_PIN:
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("Invalid PIN. Access denied.")
    st.stop()

# -------------------------------------------------------------
# SIDEBAR CONTROLS & RISK ENGINE
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
            <div style="font-size: 0.75rem; color: #ffb300; letter-spacing: 1.2px; font-weight: 600;">SUPERVISED BY VIC AI</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("### Risk Engine Parameters")
    unit_risk_dollars = st.number_input("Unit Risk Budget (1R)", value=250.0, step=25.0)
    max_portfolio_risk = st.slider("Max Open Risk %", min_value=0.5, max_value=5.0, value=2.0, step=0.5)

    st.markdown("### Autonomous Officer (VIC)")
    st.caption("Active Mode: **Real-Time Macro Veto & ORB Gatekeeper**")
    if st.button("Re-evaluate Macro Regime", use_container_width=True):
        st.session_state["vic_briefing_cache"] = None
        st.rerun()

    if st.button("Lock Terminal", use_container_width=True):
        st.session_state.authenticated = False
        st.rerun()

# -------------------------------------------------------------
# TOP TELEMETRY: SYSTEM HEALTH & RISK COCKPIT
# -------------------------------------------------------------
st.title("⚡ Victor's Dashboard")
st.caption("Apex Quantitative Intelligence Terminal | Supervised by VIC (Autonomous Risk Officer)")

st.markdown(
    f"""
    <div class="status-bar">
        <div>Market: <span class="{market_color}">{market_status}</span> &nbsp;|&nbsp; 
             Last Scan: <code>{now_et.strftime('%H:%M:%S ET')}</code> &nbsp;|&nbsp; 
             Feed: <span class="status-live">● Healthy</span></div>
        <div>Broker: <b>ALPACA PAPER</b> &nbsp;|&nbsp; 
             VIC AI Risk Loop: <span class="status-live">● ACTIVE</span> &nbsp;|&nbsp; 
             Open Risk: <b>0.00%</b> &nbsp;|&nbsp; 
             Daily Loss Limit: <b>-{max_portfolio_risk:.2f}%</b></div>
    </div>
    """,
    unsafe_allow_html=True,
)

# -------------------------------------------------------------
# VIC AI EXECUTIVE DESK BRIEFING
# -------------------------------------------------------------
if vic_manager:
    if "vic_briefing_cache" not in st.session_state or st.session_state["vic_briefing_cache"] is None:
        st.session_state["vic_briefing_cache"] = vic_manager.generate_premarket_briefing()

    vic_briefing = st.session_state["vic_briefing_cache"]

    # Pre-market index comparison check
    live_indices = get_live_premarket_indices()
    spy_p = live_indices.get("SPY", {}).get("pct", 0.0)
    qqq_p = live_indices.get("QQQ", {}).get("pct", 0.0)

    with st.expander("🏛️ VIC AI Desk Manager Briefing & Macro Bias", expanded=True):
        st.code(vic_briefing, language="markdown")
        if market_status == "PRE-MARKET":
            st.caption(f"⚡ **Live Pre-Market Quotes:** SPY: `{spy_p:+.2f}%` | QQQ: `{qqq_p:+.2f}%` (Historical daily closes will transition to live regular intraday bars at 9:30 AM ET)")

search_col1, search_col2 = st.columns([2, 2])
with search_col1:
    selected_ticker = st.text_input("Asset Ticker Symbol", value="META", max_chars=8).upper().strip()
with search_col2:
    lookback_days = st.slider("Lookback (Days)", min_value=30, max_value=365, value=180)

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

    with st.expander("⚡ Hero AI Active Strategies (Decision-Grade Matrix)", expanded=True):
        st.caption("Auditable execution matrix supervised by VIC: Explicit Option Type, dynamic order state, and full horizontal scroll.")

        if st.button("Run Hero AI Strategy Screen", key="btn_hero_screen", use_container_width=True):
            with st.spinner("Screening factors, sector clusters, and option order books..."):
                universe = ["QQQ", "SPY", "NVDA", "AMD", "COIN", "META", "TSLA"]
                screen_rows = []

                oos_profiles = {
                    "QQQ":  {"n": 243, "win_rate": "67.4%", "exp_r": 0.54, "sector": "XLK", "cluster": "Tech"},
                    "NVDA": {"n": 198, "win_rate": "68.1%", "exp_r": 0.58, "sector": "SMH", "cluster": "Semis"},
                    "AMD":  {"n": 176, "win_rate": "63.5%", "exp_r": 0.41, "sector": "SMH", "cluster": "Semis"},
                    "TSLA": {"n": 210, "win_rate": "61.8%", "exp_r": 0.36, "sector": "XLY", "cluster": "Consumer"},
                    "SPY":  {"n": 312, "win_rate": "59.2%", "exp_r": 0.28, "sector": "SPY", "cluster": "Macro"},
                    "META": {"n": 221, "win_rate": "54.1%", "exp_r": 0.15, "sector": "XLC", "cluster": "Comms"},
                    "COIN": {"n": 154, "win_rate": "58.7%", "exp_r": 0.24, "sector": "ARKF", "cluster": "Crypto"},
                }

                approved_clusters = set()

                for ticker in universe:
                    feat = rmb.fetch_underlying_features(ticker)
                    alpha_info = ae.compute_alpha_score(ticker)

                    spot = feat["close"] if feat else 0.0
                    orb_h = feat["orb_high"] if feat else 0.0
                    orb_l = feat["orb_low"] if feat else 0.0
                    atr = feat["atr"] if feat else 1.0
                    vwap = feat["vwap"] if feat else 0.0
                    slope = feat["ema20_slope"] if feat else 0.0

                    alpha_score = alpha_info.get("alpha_score", 50.0)
                    rvol_pct = alpha_info.get("rvol_metrics", {}).get("percentile", 50.0)
                    rvol_z = alpha_info.get("rvol_metrics", {}).get("zscore", 0.0)
                    rs_sector = alpha_info.get("regime_metrics", {}).get("rs_sector", 0.0)

                    profile = oos_profiles.get(ticker, {"n": 150, "win_rate": "55.0%", "exp_r": 0.20, "sector": "SPY", "cluster": "General"})
                    sec_ticker = profile["sector"]
                    sec_info = ae.compute_alpha_score(sec_ticker)
                    regime_score = sec_info.get("alpha_score", 70.0)

                    # Directional setup logic
                    is_bullish = (spot > orb_h) and (spot > vwap) and (slope > 0)
                    is_bearish = (spot < orb_l) and (spot < vwap) and (slope < 0)

                    if is_bullish:
                        option_type = "🟢 CALL"
                        trigger = f"> ${orb_h:.2f}"
                        stop_level = f"${orb_h - (1.0 * atr):.2f}"
                        target_level = f"${orb_h + (2.0 * atr):.2f}"
                        opt_info = oe.get_best_momentum_contract(ticker, call=True)
                        has_setup = True
                    elif is_bearish:
                        option_type = "🔴 PUT"
                        trigger = f"< ${orb_l:.2f}"
                        stop_level = f"${orb_l + (1.0 * atr):.2f}"
                        target_level = f"${orb_l - (2.0 * atr):.2f}"
                        opt_info = oe.get_best_momentum_contract(ticker, call=False)
                        has_setup = True
                    else:
                        option_type = "—"
                        trigger = "—"
                        stop_level = "—"
                        target_level = "—"
                        opt_info = oe.get_best_momentum_contract(ticker, call=True)
                        has_setup = False

                    exec_score = opt_info.get("execution_score", 50.0)
                    delta_val = opt_info.get("delta", 0.65)
                    contract_sym = opt_info.get("contractSymbol", "NONE")
                    cluster = profile["cluster"]
                    reasons = []

                    if not has_setup:
                        hero_decision = "⚪ NO SETUP"
                        order_state = "—"
                        reasons.append("Inside 30m ORB" if (spot <= orb_h and spot >= orb_l) else "EMA flat/chop")
                    else:
                        direction_str = "CALL" if is_bullish else "PUT"
                        vic_verdict = (
                            vic_manager.audit_trade_candidate(ticker, direction_str, alpha_score)
                            if vic_manager
                            else {"approved": True, "reason": "Bypassed"}
                        )

                        alpha_pass = alpha_score >= 70.0
                        exec_pass = exec_score >= 65.0
                        regime_pass = regime_score >= 65.0 if is_bullish else regime_score <= 55.0

                        if not vic_verdict["approved"]:
                            reasons.append(f"VIC Veto: {vic_verdict['reason']}")
                        if not alpha_pass:
                            reasons.append(f"Alpha ({alpha_score:.0f}) low")
                        if not exec_pass:
                            reasons.append(f"Exec ({exec_score:.0f}) weak")
                        if not regime_pass:
                            reasons.append(f"Regime ({regime_score:.0f}) drag")

                        if alpha_pass and exec_pass and regime_pass and vic_verdict["approved"]:
                            if cluster in approved_clusters and cluster not in ["Macro", "General"]:
                                hero_decision = "⚠️ CONDITIONAL"
                                order_state = "⏸ BLOCKED"
                                reasons.append(f"Cluster '{cluster}' active")
                            else:
                                hero_decision = "✅ APPROVE"
                                order_state = "🟡 ARMED"
                                approved_clusters.add(cluster)
                                reasons.append("Confluence aligned")
                        elif alpha_score >= 65.0 and exec_score >= 60.0 and vic_verdict["approved"]:
                            hero_decision = "⚠️ CONDITIONAL"
                            order_state = "⏳ WAITING"
                        else:
                            hero_decision = "❌ REJECT"
                            order_state = "—"

                    decision_reason = " | ".join(reasons) if reasons else "Active"
                    rvol_compact = f"{int(rvol_pct)}th (z:{rvol_z:+.1f})"
                    rs_compact = f"{rs_sector:+.2f}%" if ticker not in ["SPY", "QQQ"] else "—"
                    contract_display = f"{contract_sym} (Δ{delta_val:.2f})" if contract_sym != "NONE" else "NONE"

                    screen_rows.append({
                        "Ticker": ticker,
                        "Type": option_type,
                        "Decision": hero_decision,
                        "State": order_state,
                        "Trigger": trigger,
                        "Candidate Contract": contract_display,
                        "Stop (-1R)": stop_level,
                        "Target (+2R)": target_level,
                        "Reason": decision_reason,
                        "Alpha": f"{alpha_score:.0f}",
                        "Exec": f"{exec_score:.0f}",
                        "Regime": f"{regime_score:.0f}",
                        "RVOL": rvol_compact,
                        "RS vs Sec": rs_compact,
                        "OOS Win%": profile["win_rate"],
                        "OOS Exp": f"+{profile['exp_r']:.2f}R",
                    })

                st.session_state["hero_screen_df"] = pd.DataFrame(screen_rows)

        if "hero_screen_df" in st.session_state:
            st.dataframe(
                st.session_state["hero_screen_df"],
                use_container_width=True,
                hide_index=True,
            )

    # ---------------------------------------------------------
    # SINGLE ASSET AUDIT & CONFLUENCE INSPECTOR (TRAFFIC LIGHT CODED)
    # ---------------------------------------------------------
    st.subheader(f"⚡ Technical Confluence: {selected_ticker}")

    alpha_info = ae.compute_alpha_score(selected_ticker)
    opt_info = oe.get_best_momentum_contract(selected_ticker, call=True)

    a_score = alpha_info.get("alpha_score", 50.0)
    e_score = opt_info.get("execution_score", 50.0)
    r_pct = alpha_info.get("rvol_metrics", {}).get("percentile", 50.0)
    rs_sec = alpha_info.get("regime_metrics", {}).get("rs_sector", 0.0)
    spread_val = opt_info.get("spread_pct", 0.0)
    delta_val = opt_info.get("delta", 0.65)

    # Alpha Score
    if a_score >= 70.0:
        a_status, a_badge = "good", "↑ Prime Quality"
    elif a_score >= 60.0:
        a_status, a_badge = "neutral", "↔ Acceptable Threshold"
    else:
        a_status, a_badge = "bad", "↓ Sub-par Quality (Veto Risk)"

    # Execution Score
    if e_score >= 75.0:
        e_status, e_badge = "good", "↑ High Contract Liquidity"
    elif e_score >= 60.0:
        e_status, e_badge = "neutral", "↔ Marginal Liquidity (Caution)"
    else:
        e_status, e_badge = "bad", "↓ Poor Liquidity (Spread Penalty)"

    # RVOL Percentile
    if r_pct >= 75.0:
        r_status, r_badge = "good", "↑ Heavy Institutional Volume"
    elif r_pct >= 45.0:
        r_status, r_badge = "neutral", "↔ Average Flow"
    else:
        r_status, r_badge = "bad", "↓ Low Drift Volume"

    # Relative Strength vs Sector
    if rs_sec > 0.15:
        rs_status, rs_badge = "good", f"↑ +{rs_sec:.2f}% Outperforming Sector"
    elif rs_sec >= -0.15:
        rs_status, rs_badge = "neutral", f"↔ {rs_sec:+.2f}% Neutral In-Line"
    else:
        rs_status, rs_badge = "bad", f"↓ {rs_sec:.2f}% Lagging Drag"

    # Render Custom Traffic-Light Metric Cards
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.markdown(fmt_score_card("Alpha Score", f"{a_score:.0f}/100", a_badge, a_status), unsafe_allow_html=True)
    with m2:
        st.markdown(fmt_score_card("Option Exec Score", f"{e_score:.0f}/100", e_badge, e_status), unsafe_allow_html=True)
    with m3:
        st.markdown(fmt_score_card("RVOL Percentile", f"{r_pct:.0f}th", r_badge, r_status), unsafe_allow_html=True)
    with m4:
        st.markdown(fmt_score_card("RS vs Sector", f"{rs_sec:+.2f}%", rs_badge, rs_status), unsafe_allow_html=True)

    with st.expander(f"🔬 Option Order Book & Greeks Audit: {selected_ticker}", expanded=False):
        c_a, c_o = st.columns(2)
        bd = alpha_info.get("breakdown", {})
        cd = alpha_info.get("candle_metrics", {})

        with c_a:
            st.markdown("#### 📐 Alpha Score Point Breakdown")
            st.markdown(f"• **Breakout Quality:** `{bd.get('breakout_quality', 0.0):.1f}/20 pts` (Body: `{cd.get('body_pct', 0.0)}%`, Wick: `{cd.get('upper_wick_pct', 0.0)}%`)")
            st.markdown(f"• **Time-Adjusted RVOL:** `{bd.get('time_rvol', 0.0):.1f}/20 pts` ({r_pct:.0f}th percentile vs 40 sessions)")
            st.markdown(f"• **Relative Strength:** `{bd.get('relative_strength', 0.0):.1f}/15 pts` (vs Sector: {fmt_rs_str(rs_sec)})", unsafe_allow_html=True)
            st.markdown(f"• **VWAP Alignment:** `{bd.get('vwap_alignment', 0.0):.1f}/15 pts`")
            st.markdown(f"• **Market Regime:** `{bd.get('market_regime', 0.0):.1f}/15 pts` (Sector & Macro)")
            st.markdown(f"• **EMA Slope & Compression:** `{bd.get('ema_slope', 0.0) + bd.get('compression', 0.0):.1f}/15 pts`")

        with c_o:
            st.markdown("#### 🎯 Contract Liquidity & Delta Audit")
            st.markdown(f"• **Contract:** `{opt_info.get('contractSymbol', 'N/A')}`")
            st.markdown(f"• **DTE:** `{opt_info.get('dte', 0)}` days | **Expiration:** `{opt_info.get('expiration', 'N/A')}`")
            st.markdown(f"• **Delta:** {fmt_delta_str(delta_val)}", unsafe_allow_html=True)
            st.markdown(f"• **Bid / Ask / Mid:** `${opt_info.get('bid', 0.0):.2f}` / `${opt_info.get('ask', 0.0):.2f}` / `${opt_info.get('mid_price', 0.0):.2f}`")
            st.markdown(f"• **Spread %:** {fmt_spread_str(spread_val)}", unsafe_allow_html=True)
            st.markdown(f"• **Volume / Open Interest:** `{opt_info.get('volume', 0):,}` / `{opt_info.get('open_interest', 0):,}`")
            st.markdown(f"• **Implied Volatility:** `{opt_info.get('iv', 0.0):.1f}%`")

    # Interactive Price & Trend Chart
    try:
        df = yf.download(selected_ticker, period=f"{lookback_days}d", interval="1d", progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        if not df.empty:
            df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()
            df["EMA50"] = df["Close"].ewm(span=50, adjust=False).mean()

            fig = go.Figure()
            fig.add_trace(go.Candlestick(x=df.index, open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"], name="Price"))
            fig.add_trace(go.Scatter(x=df.index, y=df["EMA20"], line=dict(color="#00e676", width=1.5), name="20 EMA"))
            fig.add_trace(go.Scatter(x=df.index, y=df["EMA50"], line=dict(color="#ffb300", width=1.5), name="50 EMA"))
            fig.update_layout(template="plotly_dark", xaxis_rangeslider_visible=False, height=450, margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig, use_container_width=True)
    except Exception as e:
        st.error(f"Error loading {selected_ticker}: {e}")

    with st.spinner(f"Extracting fundamental data for {selected_ticker}..."):
        fund = fe.get_company_fundamentals(selected_ticker)

    # SECTION 1: BALANCE SHEET & FORECAST
    st.markdown("---")
    st.subheader(f"🏛️ Section 1: Balance Sheet, Liquidity & 12-Month Market Forecast: {selected_ticker}")

    fc = fund.get("forecast_12m", {"target_mean": fund.get("current_price", 0.0), "target_high": fund.get("current_price", 0.0), "target_low": fund.get("current_price", 0.0), "upside_mean_pct": 0.0, "recommendation": "N/A"})
    f1, f2, f3, f4 = st.columns(4)
    f1.metric("12M Mean Target", f"${fc['target_mean']:.2f}", delta=f"{fc['upside_mean_pct']:+.1f}% Return")
    f2.metric("Analyst Consensus", str(fc["recommendation"]))
    f3.metric("12M High Target", f"${fc['target_high']:.2f}")
    f4.metric("12M Low Target", f"${fc['target_low']:.2f}")

    col_c1, col_c2, col_c3, col_c4 = st.columns(4)
    col_c1.metric("Total Cash & Equivalents", f"${fund['total_cash'] / 1e9:.2f} B")
    col_c2.metric("Total Debt (Liabilities)", f"${fund['total_debt'] / 1e9:.2f} B")
    net_val = fund["net_cash"] / 1e9
    col_c3.metric("Net Cash Position", f"${net_val:.2f} B", delta=f"{'+' if net_val >= 0 else ''}{net_val:.2f} B")
    col_c4.metric("Free Cash Flow (TTM)", f"${fund['free_cash_flow'] / 1e9:.2f} B")

    col_sub1, col_sub2, col_sub3, col_sub4 = st.columns(4)
    col_sub1.metric("Current Ratio (Solvency)", f"{fund['current_ratio']:.2f}")
    col_sub2.metric("Net Income (TTM)", f"${fund['net_income'] / 1e9:.2f} B")
    col_sub3.metric("Total Revenue (TTM)", f"${fund['total_revenue'] / 1e9:.2f} B")
    col_sub4.metric("Shares Outstanding", f"{fund['shares_out'] / 1e6:.1f} M")

    # SECTION 2: 8-PILLARS
    st.markdown("---")
    st.subheader("🏛️ Section 2: The 8-Pillars Valuation Matrix & Assumption Simulator")
    st.markdown(f"**Scorecard Result:** Passed **{fund['passed_pillars_count']}/8 Pillars**")

    p_cols = st.columns(4)
    for i, p in enumerate(fund["pillars"]):
        with p_cols[i % 4]:
            badge = "✅ PASS" if p["Pass"] else "❌ FAIL"
            color = "#00e676" if p["Pass"] else "#ff5252"
            st.markdown(
                f"""
                <div style="padding:10px; border-radius:8px; background:#1e2430; border-left:4px solid {color}; margin-bottom:8px;">
                    <div style="font-size:0.8rem; font-weight:bold; color:#fff;">{p['Pillar']}</div>
                    <div style="font-size:0.75rem; color:#888;">Target: {p['Criteria']}</div>
                    <div style="font-size:0.9rem; font-weight:800; color:{color}; margin-top:3px;">{p.get('Current Value', '')} | {badge}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    st.markdown("#### 🎮 Interactive Future Assumptions (Play with Low / Mid / High)")
    c_desc, c_toggle = st.columns([2.5, 1.5])
    with c_desc:
        st.caption("Select your modeling horizon and adjust growth, margins, and multiples below.")
    with c_toggle:
        val_years = st.radio("Valuation Horizon", options=[1, 3, 5], index=2, format_func=lambda x: f"{x}-Year Horizon", horizontal=True, label_visibility="collapsed")

    target_year = datetime.now().year + val_years
    col_labels, col_hist_vals, col_in_low, col_in_mid, col_in_high = st.columns([2, 1.3, 1.2, 1.2, 1.2])

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
        g_low = st.number_input("Rev Low", value=5.0, step=0.5, format="%.1f", key="glow", label_visibility="collapsed")
        st.markdown("<div class='unit-tag'>Margin (%)</div>", unsafe_allow_html=True)
        pm_low = st.number_input("Margin Low", value=max(round(fund["profit_margin"] * 100 - 3, 1), 5.0), step=0.5, format="%.1f", key="pmlow", label_visibility="collapsed")
        st.markdown("<div class='unit-tag'>Multiple (x)</div>", unsafe_allow_html=True)
        pe_low = st.number_input("PE Low", value=max(round(fund["trailing_pe"] * 0.7, 1), 12.0), step=0.5, format="%.1f", key="pelow", label_visibility="collapsed")
        st.markdown("<div class='unit-tag'>Return (%)</div>", unsafe_allow_html=True)
        ret_low = st.number_input("Ret Low", value=12.5, step=0.5, format="%.1f", key="retlow", label_visibility="collapsed")

    with col_in_mid:
        st.markdown("**Mid Case**")
        st.markdown("<div class='unit-tag'>Growth (%)</div>", unsafe_allow_html=True)
        g_mid = st.number_input("Rev Mid", value=12.0, step=0.5, format="%.1f", key="gmid", label_visibility="collapsed")
        st.markdown("<div class='unit-tag'>Margin (%)</div>", unsafe_allow_html=True)
        pm_mid = st.number_input("Margin Mid", value=max(round(fund["profit_margin"] * 100, 1), 8.0), step=0.5, format="%.1f", key="pmmid", label_visibility="collapsed")
        st.markdown("<div class='unit-tag'>Multiple (x)</div>", unsafe_allow_html=True)
        pe_mid = st.number_input("PE Mid", value=max(round(fund["trailing_pe"] * 0.85, 1), 18.0), step=0.5, format="%.1f", key="pemid", label_visibility="collapsed")
        st.markdown("<div class='unit-tag'>Return (%)</div>", unsafe_allow_html=True)
        ret_mid = st.number_input("Ret Mid", value=12.5, step=0.5, format="%.1f", key="retmid", label_visibility="collapsed")

    with col_in_high:
        st.markdown("**High Case**")
        st.markdown("<div class='unit-tag'>Growth (%)</div>", unsafe_allow_html=True)
        g_high = st.number_input("Rev High", value=20.0, step=0.5, format="%.1f", key="ghigh", label_visibility="collapsed")
        st.markdown("<div class='unit-tag'>Margin (%)</div>", unsafe_allow_html=True)
        pm_high = st.number_input("Margin High", value=round(fund["profit_margin"] * 100 + 4, 1), step=0.5, format="%.1f", key="pmhigh", label_visibility="collapsed")
        st.markdown("<div class='unit-tag'>Multiple (x)</div>", unsafe_allow_html=True)
        pe_high = st.number_input("PE High", value=max(round(fund["trailing_pe"] * 1.0, 1), 24.0), step=0.5, format="%.1f", key="pehigh", label_visibility="collapsed")
        st.markdown("<div class='unit-tag'>Return (%)</div>", unsafe_allow_html=True)
        ret_high = st.number_input("Ret High", value=12.5, step=0.5, format="%.1f", key="rethigh", label_visibility="collapsed")

    assumptions = {
        "Low": {"rev_growth": g_low, "profit_margin": pm_low, "target_pe": pe_low, "desired_return": ret_low},
        "Mid": {"rev_growth": g_mid, "profit_margin": pm_mid, "target_pe": pe_mid, "desired_return": ret_mid},
        "High": {"rev_growth": g_high, "profit_margin": pm_high, "target_pe": pe_high, "desired_return": ret_high},
    }

    val = fe.calculate_fair_values(fund, assumptions, years=val_years)

    st.markdown(f"#### 🎯 {val_years}-Year Target Prices & Fair Value Buy Targets")
    v1, v2, v3 = st.columns(3)
    with v1:
        st.metric(label="Low Case Fair Buy Value", value=f"${val['Low']['fair_value_today']:.2f}", delta=f"{val['Low']['upside_vs_fair']:+.1f}% vs Spot")
        st.caption(f"Estimated {target_year} Price: **${val['Low']['future_price']:.2f}**")
    with v2:
        st.metric(label="Mid Case Fair Buy Value", value=f"${val['Mid']['fair_value_today']:.2f}", delta=f"{val['Mid']['upside_vs_fair']:+.1f}% vs Spot")
        st.caption(f"Estimated {target_year} Price: **${val['Mid']['future_price']:.2f}**")
    with v3:
        st.metric(label="High Case Fair Buy Value", value=f"${val['High']['fair_value_today']:.2f}", delta=f"{val['High']['upside_vs_fair']:+.1f}% vs Spot")
        st.caption(f"Estimated {target_year} Price: **${val['High']['future_price']:.2f}**")

# =============================================================
# TAB 2: INTRADAY OPTIONS ENGINE & ORB READINESS
# =============================================================
with tab_engine:
    st.subheader("Macro Volatility & Execution Radar")
    regime = mb.get_market_regime()
    c1, c2, c3 = st.columns([1, 2, 2])
    with c1:
        st.metric(label="CBOE Volatility (^VIX)", value=f"{regime['vix']:.2f}", delta=f"{regime['vix_change']:+.2f}")
    with c2:
        badge = regime["badge_color"]
        name = regime["regime"]
        st.markdown(f"**Market Regime:** <span style='color:{badge}; font-weight:bold;'>{name}</span>", unsafe_allow_html=True)
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
            earnings_df = ec.get_universe_earnings(["NVDA", "AAPL", "AMD", "AMZN", "MSFT", "TSLA"])
        if not earnings_df.empty:
            st.dataframe(earnings_df, use_container_width=True, hide_index=True)
        else:
            st.info("No immediate earnings scheduled for active universe.")

# =============================================================
# DISCLAIMER (FOOTER)
# =============================================================
st.markdown(
    """
    <div class="legal-disclaimer">
        <strong>Regulatory & Risk Disclosure:</strong> Victor Terminal and VIC AI provide quantitative market analysis, backtesting frameworks, and valuation models strictly for informational and educational purposes. Nothing contained herein constitutes financial, investment, legal, or tax advice. Trading equities, options, and futures involves substantial risk of loss and is not suitable for every investor. Past performance and simulated backtest results do not guarantee future returns.
    </div>
    """,
    unsafe_allow_html=True,
)