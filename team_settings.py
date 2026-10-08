"""Shared experiment labels and virtual premium allocation; no credentials."""
BUDGET = 5000.0
NAMES = {
    'team1': 'Level / ORB momentum',
    'team2': 'Wick / RSI reversal',
    'team3': 'Aggressive price action',
    'team4': 'Wick / outer Bollinger reversal',
    'team5': 'Balanced BB / RSI reversal',
    'team6': '5-minute EMA5/9 + volume momentum',
}
EXIT_LABELS = {
    **dict.fromkeys(('team1', 'team2', 'team3'), '$500 half / $1,000 all / $300 floor'),
    'team2': '$200 peak protection / $500 half / momentum runner / rising floor',
    'team4': '$200 peak protection / $500 or 1R half / rising floor / 2R or 45-minute maximum',
    'team5': '$200 peak protection / $500 half / frozen middle target / 20-minute maximum',
    'team6': '$200 peak protection / $500 or 1R half / opposite wick or 2R all / 30-minute maximum',
}

ENTRY_LABELS = {
 'team1':'Level rejection or opening-range continuation, directional body and one momentum clue.',
 'team2':'Three prior bars net opposite move; rejection wick >=50% range and >=2x body; close in opposite 30%; RSI <=35 call / >=65 put. No next-candle wait.',
 'team3':'Chart-only sweep/reclaim or recent-range breakout.',
 'team4':'Same rejection wick as Team 2; extreme within 10% of full BB20/2 width from outer band, or outside. No RSI gate.',
 'team5':'BB20/2 excursion and RSI35/65 reversal, price confirmation and frozen middle target; VWAP never vetoes.',
 'team6':'EMA5 above/below EMA9 and both rising/falling; close beyond prior bar high/low; volume >=1.2x preceding 20 bars. No five-candle wait.',
}

# Shared revision applies quality gates without replacing the six pattern identities.
for _team in ENTRY_LABELS:
    ENTRY_LABELS[_team] += " Quality: reject overlapping low-volume chop, tiny rejection candles and extended momentum; minimum 0.5R target room."
for _team in EXIT_LABELS:
    EXIT_LABELS[_team] = "$500 half / $1,000 all; after observed $200 peak retain half (minimum $50), after $500 peak retain max($300, 60% of peak). 20% premium stop / structural stop / session flatten. Older positions retain their recorded policy."
EXIT_LABELS['team4'] += " Also 1R half, frozen 2R target or 45-minute maximum."
EXIT_LABELS['team5'] += " Also frozen middle-band target or 20-minute maximum."
EXIT_LABELS['team6'] += " Also 1R half, opposite rejection wick, 2R target or 30-minute maximum."

ENTRY_LABELS["team2"] += " RSI must turn at least 0.5 points toward 50 on the signal candle."
ENTRY_LABELS["team4"] += " Rejection must close back inside the outer band."
ENTRY_LABELS["team5"] += " Do not fade an opposing EMA9 slope beyond 0.75 ATR when BB width expands over 10%."
ENTRY_LABELS["team6"] += " Prefer same-clock-slot RVOL; use previous-20-bar RVOL only when unavailable."

# Active-context experiment: retain the original six plus eleven report winners.
# Aggregate premium remains the original six-team maximum, rather than growing with roster size.
AGGREGATE_PREMIUM_CAP = 30000.0
WINNER_DAILY_LOSS = 1000.0
REPORT_WINNERS = {
 5: ('Balanced BB / RSI reversal',5,49,2050.8),
 8: ('Rejection wick',15,36,171.6),
 11: ('Large opening-gap failure fade',5,3,1662.5),
 21: ('EMA5/9 + RVOL + ADX',5,105,2121.4),
 25: ('BB compression / range expansion',5,18,667.4),
 36: ('Two-leg complex pullback',5,6,315.2),
 50: ('Wick + outer BB',60,2,409.8),
 52: ('ORB / volume retest',2,2,2098.8),
 54: ('ORB / volume retest',10,1,1179.2),
 55: ('ORB / volume retest',30,4,8263.6),
 61: ('Known-level sweep',30,5,17.6),
}
for _number, (_label,_minutes,_trades,_net) in REPORT_WINNERS.items():
    _id='report'+str(_number)
    NAMES[_id]=f'Report {_number}: {_label} ({_minutes}m)'
    ENTRY_LABELS[_id]=f'Adapted from 2025 report Team {_number}; native {_minutes}m entry timing; {_trades} historical trades, ${_net:+,.2f} simulated net. Active market context changes order priority, side selection and size.'
    EXIT_LABELS[_id]='Original report structural/time exits and premium safeguards; $1,000 daily loss trigger; session flatten; two-candle adverse market thesis exit. Paper execution differs from the report.'

# Appended to preserve persisted report-team identities and the original roster order.
NAMES['team7']='VIC daily direction / one morning entry'
ENTRY_LABELS['team7']='09:30 <= entry < 10:00 ET; one submission per session; all six available daily VIC factors agree; confirmed local pullback from completed one-minute candles. Up to $5,000 premium, standard QQQ 1–3 DTE / 0.40–0.60 absolute delta. No future low, forced deadline entry, top-up or re-entry.'
EXIT_LABELS['team7']='Hold all filled contracts until 15:45 ET (15 minutes before an early close). No routine premium stop, profit target, trailing floor or VIC reversal exit. Manual flatten remains available. Entire paid premium is at risk; paper experiment.'
ENTRY_LABELS['team1']+=' VIC v2 pilot requires EMA momentum AND directional RSI; volume or VIC alone cannot supply confirmation.'
ENTRY_LABELS['team3']+=' VIC v2 ranks valid sides and changes premium allocation; its chart-only setup remains independent.'
