"""Display calculations and optional public observations. No execution imports."""
import math
from datetime import timedelta
import pandas as pd

def num(v):
    if isinstance(v,bool):return None
    try:
        n=float(v)
        return n if math.isfinite(n) else None
    except (TypeError,ValueError):return None

def fresh(value,now,seconds=45):
    try:
        ts=pd.Timestamp(value)
        return ts.tzinfo is not None and 0 <= (pd.Timestamp(now)-ts).total_seconds() <= seconds
    except (ValueError,TypeError):return False

def change(value,prior):
    a,b=num(value),num(prior)
    return (a-b,(a/b-1)*100) if a is not None and b is not None and b>0 else (None,None)

def team_totals(teams,day):
    # Only one report per team; historical sessions never enter today's total.
    teams=list({t['team_id']:t for t in teams if t.get('day')==str(day)}.values())
    if not teams:return None
    def total(key):
        values=[num(t.get(key)) for t in teams]
        return sum(values) if all(v is not None for v in values) else None
    active=[p for t in teams for p in t.get('trades',[]) if (num(p.get('remaining_qty')) or 0)>0]
    pending=any(t.get('pending_entry') for t in teams)
    costs=[num(p.get('entry_price')) for p in active]
    premium=sum(p['remaining_qty']*c*100 for p,c in zip(active,costs)) if all(c is not None for c in costs) and not pending else None
    floating=total('unrealized_pnl')
    market=premium+floating if premium is not None and floating is not None else None
    complete=all(len([p for p in t.get('trades',[]) if p.get('remaining_qty')==0]) == num(t.get('completed_trades')) for t in teams)
    closed=[p for t in teams for p in t.get('trades',[]) if p.get('remaining_qty')==0]
    pnl=[num(p.get('realized_pnl')) for p in closed]
    closed_pnl=sum(pnl) if complete and all(v is not None for v in pnl) else None
    starting=total('starting_equity')
    return dict(teams=len(teams),positions=None if pending else len(active),contracts=None if pending else sum(p['remaining_qty'] for p in active),
                premium=premium,market_value=market,unrealized=floating,realized=total('realized_pnl'),closed_pnl=closed_pnl,
                closed_balance=starting+closed_pnl if starting is not None and closed_pnl is not None else None,
                starting=starting,closed_trades=total('completed_trades'),wins=sum(v>0 for v in pnl) if complete and all(v is not None for v in pnl) else None,
                losses=sum(v<0 for v in pnl) if complete and all(v is not None for v in pnl) else None,pending=pending)

def event_windows(events,now):
    today=now.date();monday=today-timedelta(days=today.weekday())
    high=[e for e in events if isinstance(e,dict) and e.get('impact')=='HIGH']
    high=sorted(high,key=lambda e:(str(e.get('date','')),str(e.get('scheduled_at') or '')))
    return { 'Today':[e for e in high if e.get('date')==str(today)],
             'This week':[e for e in high if str(monday)<=str(e.get('date',''))<=str(monday+timedelta(days=6))],
             'Next 30 days':[e for e in high if str(today)<=str(e.get('date',''))<str(today+timedelta(days=30))]}

def daily_observation(frame,now):
    if frame is None or frame.empty:return {}
    values=pd.to_numeric(frame.iloc[:,0],errors='coerce').dropna()
    values=values[values.index.date<=now.date()]
    if values.empty:return {}
    val=float(values.iloc[-1]);prior=float(values.iloc[-2]) if len(values)>1 else None
    absolute,relative=change(val,prior)
    return dict(value=val,prior=prior,change=absolute,change_pct=relative,date=str(values.index[-1].date()))
