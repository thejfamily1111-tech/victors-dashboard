"""Causal overnight research model and bounded shared entry context. No broker API."""
from datetime import datetime, timedelta
from pathlib import Path
import hashlib
import json
import math
from zoneinfo import ZoneInfo
import numpy as np

ET = ZoneInfo('America/New_York')
VERSION = 'overnight-v1.4.0'
GROUP_WEIGHTS = {'futures':.30, 'us':.25, 'asia':.12, 'europe':.12,
                 'rates_fx':.10, 'crypto':.06, 'commodities':.05}


def ts(value):
    value = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace('Z','+00:00'))
    if value.tzinfo is None: raise ValueError('Timestamp must include timezone')
    return value.astimezone(ET)


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def bias(value, threshold=.001):
    return 'BULLISH' if value > threshold else 'BEARISH' if value < -threshold else 'NEUTRAL'


def digest(obj):
    return hashlib.sha256(json.dumps(obj,sort_keys=True,allow_nan=False).encode()).hexdigest()[:20]


def session(day):
    import exchange_calendars as xc
    cal=xc.get_calendar('XNYS')
    label=cal.date_to_session(str(day), direction='none')
    opening=cal.session_open(label).to_pydatetime().astimezone(ET)
    closing=cal.session_close(label).to_pydatetime().astimezone(ET)
    return opening, closing


def target_day(current):
    """Today until the close; then the next exchange session (including holidays)."""
    import exchange_calendars as xc
    cal=xc.get_calendar('XNYS'); current=ts(current)
    label=cal.date_to_session(str(current.date()),direction='next')
    if cal.session_close(label).to_pydatetime() <= current:
        label=cal.next_session(label)
    return str(label.date())


def usable_evidence(row, current):
    try:
        return (row.get('eligible') is True and row.get('status') in ('FRESH','CLOSED')
                and ts(row['observed_at']) <= ts(row['received_at']) <= current
                and 0 <= (current-ts(row['observed_at'])).total_seconds() <= (900 if row['status']=='FRESH' else 86400)
                and number(row.get('change_pct')))
    except (KeyError, TypeError, ValueError): return False


def build(raw, current, slot='MONITOR'):
    """Historical analogs + bounded macro scenarios. Nothing is a calibrated probability."""
    current=ts(current); day=raw['session_date']; opening, closing=session(day)
    hold_until=closing-timedelta(minutes=15)
    rows=[r for r in raw.get('observations',[]) if usable_evidence(r,current)]
    groups={}
    for name, weight in GROUP_WEIGHTS.items():
        values=[max(-1.,min(1.,r['change_pct']/r.get('scale',1.))) * r.get('polarity',1)
                for r in rows if r.get('group')==name]
        if values: groups[name]={'score':round(float(np.mean(values)),4),'count':len(values),'weight':weight}
    score=sum(g['score']*g['weight'] for g in groups.values())
    coverage=sum(g['weight'] for g in groups.values())
    news=[r for r in raw.get('news',[]) if _known(r,current)]
    events=[r for r in raw.get('events',[]) if r.get('date')==day and r.get('impact')=='HIGH']
    payload={'version':VERSION,'session_date':day,'issued_at':current.isoformat(),
        'data_cutoff':raw.get('data_cutoff'), 'slot':slot, 'can_submit_orders':False,
        'valid_until':(opening+timedelta(minutes=90) if slot in ('0915','0925') else current+timedelta(minutes=10)).isoformat(),
        'groups':groups,'score':round(score,4),'coverage':round(coverage,3),
        'direction':bias(score,.15),'probability_green':None,'probability_status':'UNCALIBRATED',
        'range_status':'UNVALIDATED_EMPIRICAL_QUANTILES','forecast':{},
        'observations':raw.get('observations',[]),'news':news[:20],'events':events[:20],
        'economic_releases':[r for r in raw.get('economic_releases',[]) if _known(r,current)],
        'warnings':raw.get('warnings',[])[:20], 'ai':{'status':'NOT_REQUESTED'},
        'method':'QQQ gap/trend analogs; bounded global scenario tilt. No trained global-to-QQQ probability model.',
        'session_open':opening.isoformat(),'session_close':closing.isoformat(),'hold_until':hold_until.isoformat()}
    # The pre-open analog target is not a rolling intraday forecast. Keep fresh
    # global evidence visible after the open without reanchoring full-day paths
    # to an intraday price or resurrecting the expired morning contribution.
    if current >= opening:
        payload.update(slot='INTRADAY_MONITOR',status='CONTEXT_ONLY',direction='UNKNOWN',
            forecast={},method='Fresh global context only; morning forecasts remain frozen. Intraday plans require completed local chart evidence.')
        payload['forecast_id']=digest(payload)
        return payload
    q=next((r for r in rows if r.get('id')=='QQQ'),None)
    history=sorted([r for r in raw.get('history',[]) if str(r.get('date',''))<day
                    and all(number(r.get(k)) and r[k]>0 for k in ('open','high','low','close','previous_close'))],key=lambda r:r['date'])
    # Duplicate dates never count as independent analogs. Exclude a broken OHLC bar.
    history=list({r['date']:r for r in history if r['low']<=min(r['open'],r['close'])<=max(r['open'],r['close'])<=r['high']}.values())
    import exchange_calendars as xc
    expected_previous=str(xc.get_calendar('XNYS').previous_session(day).date())
    if q is None or len(history)<40 or ts(q['observed_at']).date()!=opening.date() or history[-1]['date']!=expected_previous:
        payload['status']='INSUFFICIENT_DATA'; payload['forecast_id']=digest(payload); return payload
    anchor=q['value']; previous=history[-1]['close']; gap=anchor/previous-1
    current_trend=previous/history[-6]['close']-1
    for i,r in enumerate(history):
        r=dict(r); r['trend']=history[i-1]['close']/history[i-6]['close']-1 if i>=6 else 0
        history[i]=r
    ordered=sorted(history,key=lambda r:abs((r['open']/r['previous_close']-1)-gap)+.25*abs(r['trend']-current_trend))
    analogs=ordered[:min(60,max(30,len(ordered)//4))]
    ranges=np.array([(r['high']-r['low'])/r['open'] for r in analogs])
    day_range=max(.002,float(np.median(ranges)))
    tilt=score*day_range*.15  # Heuristic maximum 15% of typical daily range, not fitted alpha.
    vol=[r for r in rows if r.get('group')=='volatility']
    stress=any(r['change_pct']>5 for r in vol)
    widening=1.25 if events or stress else 1.
    def estimate(field):
        candidates=[r for r in ordered if number(r.get(field)) and r[field]>0]
        matched=candidates[:min(60,max(30,len(candidates)//4))]
        samples=[r[field]/r['open']-1 for r in matched]
        if len(samples)<20:return None
        lo,mid,hi=np.quantile(samples,[.1,.5,.9]); mid+=tilt
        return {'estimate':round(anchor*(1+mid),2),
            'lower':round(anchor*(1+mid+(lo-(mid-tilt))*widening),2),
            'upper':round(anchor*(1+mid+(hi-(mid-tilt))*widening),2),'samples':len(samples),
            'sample_dates':[r['date'] for r in matched]}
    forecasts={k:estimate(k) for k in ('low','high','close','hold')}
    # High/low must straddle the estimated open, even after the scenario tilt.
    for bound in ('estimate','lower','upper'):
        forecasts['low'][bound]=min(anchor,forecasts['low'][bound])
        forecasts['high'][bound]=max(anchor,forecasts['high'][bound])
    for minutes in (5,10,15,30,60):forecasts[str(minutes)+'m']=estimate('m'+str(minutes))
    close_est=forecasts['close']['estimate']
    payload.update(status='READY' if coverage>=.5 else 'PARTIAL',direction=bias(close_est/previous-1,0.),
        forecast=dict(forecasts,anchor=anchor,anchor_at=q['observed_at'],anchor_kind='PREMARKET_ESTIMATED_OPEN',
            previous_close=previous,typical_range_pct=round(day_range*100,4),
            tilt_pct=round(tilt*100,4),analogs=len(analogs),
            analog_dates=[r['date'] for r in analogs],
            day_color=bias(close_est/previous-1,0.),
            from_anchor=bias(forecasts['hold']['estimate']/anchor-1) if forecasts['hold'] else 'UNKNOWN'))
    payload['forecast_id']=digest(payload)
    return payload


def _known(row,current):
    try: return ts(row['published_at'])<=ts(row['received_at'])<=current
    except (KeyError,ValueError,TypeError):return False


def usable(brief, current):
    try:
        current=ts(current)
        return (brief.get('version')==VERSION and brief.get('status')=='READY'
                and brief.get('slot') in ('0915','0925') and brief['session_date']==str(current.date())
                and ts(brief['issued_at'])<=current<ts(brief['valid_until'])
                and 0<=(ts(brief['issued_at'])-ts(brief['data_cutoff'])).total_seconds()<=600
                and ts(brief['issued_at'])<ts(brief['session_open'])
                and brief.get('coverage',0)>=.5 and number(brief['forecast']['previous_close']))
    except (KeyError,ValueError,TypeError):return False


def read_brief(root,current):
    try:
        path=Path(root)/'overnight_context.json'
        if path.stat().st_size>500000:return {}
        obj=json.loads(path.read_text())
        return obj if usable(obj,current) else {}
    except (OSError,ValueError,TypeError):return {}


def apply_context(policy,brief,current,spot=None,require_daily=False):
    """Add a small entry preference, keeping chart requirements and budgets intact."""
    import copy
    out=copy.deepcopy(policy); current=ts(current)
    valid=usable(brief,current)
    out['overnight']={'status':'ACTIVE' if valid else 'UNAVAILABLE','version':VERSION}
    if not valid:
        if require_daily:
            out.setdefault('daily_outlook',{}).update(all_aligned=False,bias='UNKNOWN',research_reason='NO_VALID_MORNING_BRIEF')
        return out
    forecast=brief['forecast']; target=forecast.get('hold') or {}
    move=target.get('estimate',0)/spot-1 if number(spot) and spot>0 and target.get('estimate') else None
    move_bias=bias(move) if move is not None else 'UNKNOWN'
    age=5*int(max(0.,(current-ts(brief['session_open'])).total_seconds()/60)//5)
    weight=.15*max(0.,1-age/90)
    ai=brief.get('ai') or {}
    ai_vote={'BULLISH':1,'BEARISH':-1}.get(ai.get('stance'),0) if ai.get('status')=='COMPLETE' else 0
    macro=max(-1.,min(1.,brief.get('score',0)+.05*ai_vote))
    before=out.get('score',0)
    out['score']=round((1-weight)*before+weight*macro,4)
    if out.get('bias')!='UNKNOWN':out['bias']=bias(out['score'],.20)
    compact={'version':VERSION,'status':'ACTIVE','forecast_id':brief['forecast_id'],
        'issued_at':brief['issued_at'],'valid_until':brief['valid_until'],
        'direction':brief['direction'],'move_from_entry':move_bias,'hold_estimate':target.get('estimate'),
        'score':macro,'weight':round(weight,4),'score_before':before,'probability_green':None}
    out['overnight']=compact
    if require_daily:
        day=out.setdefault('daily_outlook',{})
        aligned=day.get('all_aligned') and day.get('bias')==brief['direction']==move_bias and move_bias in ('BULLISH','BEARISH')
        day.update(all_aligned=bool(aligned),research=compact,
            research_reason='MORNING_AND_ENTRY_MOVE_AGREE' if aligned else 'MORNING_OR_ENTRY_MOVE_DISAGREES')
        if not aligned:day['bias']='MIXED'
    if out.get('snapshot_id'):out['snapshot_id']=digest({'base':out['snapshot_id'],'research':compact})
    return out
