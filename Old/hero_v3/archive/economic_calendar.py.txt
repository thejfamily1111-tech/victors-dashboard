import datetime
import yfinance as yf
import pandas as pd

MACRO_SCHEDULE = [
    # Format: Date (YYYY-MM-DD), Event, Impact, Category
    {"Date": "2026-09-22", "Event": "Existing Home Sales", "Impact": "Medium", "Category": "Housing"},
    {"Date": "2026-09-23", "Event": "FOMC Rate Decision & Press Conference", "Impact": "HIGH", "Category": "Fed / Rates"},
    {"Date": "2026-09-24", "Event": "Q2 GDP Final Revision / Jobless Claims", "Impact": "HIGH", "Category": "Growth & Jobs"},
    {"Date": "2026-09-25", "Event": "Core PCE Price Index (Fed Preferred Inflation)", "Impact": "HIGH", "Category": "Inflation"},
    {"Date": "2026-10-02", "Event": "Nonfarm Payrolls (NFP) & Unemployment Rate", "Impact": "HIGH", "Category": "Employment"},
    {"Date": "2026-10-13", "Event": "CPI Inflation Report (Consumer Price Index)", "Impact": "HIGH", "Category": "Inflation"},
    {"Date": "2026-10-14", "Event": "PPI Inflation Report (Producer Price Index)", "Impact": "HIGH", "Category": "Inflation"},
    {"Date": "2026-11-04", "Event": "FOMC Rate Decision", "Impact": "HIGH", "Category": "Fed / Rates"},
]

def get_economic_events(days_forward: int = 30) -> pd.DataFrame:
    """Returns scheduled high/medium impact macro events within forward window."""
    today = datetime.date.today()
    cutoff = today + datetime.timedelta(days=days_forward)
    
    events = []
    for item in MACRO_SCHEDULE:
        ev_date = datetime.datetime.strptime(item["Date"], "%Y-%m-%d").date()
        if today <= ev_date <= cutoff:
            days_until = (ev_date - today).days
            timing = "Today" if days_until == 0 else ("Tomorrow" if days_until == 1 else f"In {days_until} days")
            events.append({
                "Date": item["Date"],
                "Timing": timing,
                "Event": item["Event"],
                "Impact": item["Impact"],
                "Category": item["Category"]
            })
            
    df = pd.DataFrame(events)
    return df if not df.empty else pd.DataFrame(columns=["Date", "Timing", "Event", "Impact", "Category"])

def get_universe_earnings(symbols: list) -> pd.DataFrame:
    """Pulls earnings release dates via yfinance for the equity watchlist."""
    records = []
    today = datetime.date.today()
    
    for sym in symbols:
        if sym in ["SPY", "QQQ"]:
            continue
        try:
            ticker = yf.Ticker(sym)
            cal = ticker.calendar
            if cal is not None and not cal.empty:
                if "Earnings Date" in cal.index:
                    dates = cal.loc["Earnings Date"].tolist()
                    if dates:
                        earning_dt = pd.to_datetime(dates[0]).date()
                        if earning_dt >= today:
                            days_until = (earning_dt - today).days
                            records.append({
                                "Symbol": sym,
                                "Next Earnings Date": str(earning_dt),
                                "Timing": f"In {days_until} days" if days_until > 0 else "Today",
                                "Status": "Scheduled"
                            })
        except Exception:
            continue
            
    df = pd.DataFrame(records)
    return df if not df.empty else pd.DataFrame(columns=["Symbol", "Next Earnings Date", "Timing", "Status"])
