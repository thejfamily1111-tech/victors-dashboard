"""Deterministic local research reviews. No network, AI, orders, or risk changes.

Four scheduled receipts complement the immutable 09:15/09:25 forecasts. A review
ranks chart families; every entry must revalidate its native chart and quote.
Coverage is evidence availability, never a probability of a profitable trade.
"""
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
from daily_outlook import ts, session, target_day, number, digest, usable_evidence

VERSION='local-research-v1.7.0'
SLOTS=('0920','1020','1220','1420')
MAX_BYTES=300000
FAMILIES={
    'team1':'accepted_breakout','team2':'failed_breakout_fade',
    'team3':'accepted_breakout','team4':'range_reversion','team5':'range_reversion',
    'team6':'trend_pullback','report8':'failed_breakout_fade',
    'report21':'trend_pullback','report25':'compression_expansion'}


def load(path):
    try:
        path=Path(path)
        if path.stat().st_size>MAX_BYTES:return {}
        value=json.loads(path.read_text())
        return value if isinstance(value,dict) else {}
    except (OSError,ValueError,TypeError):return {}


def source(row,current,max_age=330):
    """Unknown receipts and future/stale observations cannot authorize ranking."""
    try:
        observed=ts(row.get('observed_at') or row['at'])
        received=ts(row.get('engine_received_at') or row['received_at'])
        if not observed<=received<=current or not 0<=(current-observed).total_seconds()<=max_age:return {}
        if not row.get('source'):return {}
        return {k:deepcopy(row[k]) for k in ('source','source_code','input_digest','observation_digest') if k in row} | {
            'observed_at':observed.isoformat(),'received_at':received.isoformat(),'status':'FRESH'}
    except (KeyError,ValueError,TypeError):return {}


def build(raw,report,current,slot,active_ids=None):
    current=ts(current);day=target_day(current);opening,closing=session(day)
    phase='PREMARKET' if current<opening else 'INTRADAY'
    policy=(report or {}).get('vic_policy') or {}
    rows=(raw or {}).get('observations',[])
    known=[r for r in rows if usable_evidence(r,current)] if (raw or {}).get('session_date')==day else []
    sources=[];levels=[];missing=[];q={};qsource={};regime='UNKNOWN';bias='UNKNOWN'
    if phase=='PREMARKET':
        q=next((r for r in known if r.get('id')=='QQQ'),{})
        qsource=source(q,current,900)
        if not number(q.get('value')) or q['value']<=0:qsource={}
        if qsource and ts(qsource['observed_at']).date()!=opening.date():qsource={}
        if qsource:
            qsource['id']='qqq_premarket';sources.append(qsource)
            # An opening hypothesis is derived from the known gap; no future high/low.
            change=q.get('change_pct')
            bias='BULLISH' if number(change) and change>.1 else 'BEARISH' if number(change) and change<-.1 else 'NEUTRAL'
        missing.append('Completed regular-session chart confirmation not yet available')
    else:
        q=(policy.get('factors') or {}).get('qqq') or {}
        qsource=source(q,current)
        if not number(q.get('close')) or q['close']<=0:qsource={}
        try:
            if not (ts(policy['at'])<=current<ts(policy['valid_until']) and
                    ts(policy['at']).date()==current.date()):qsource={}
        except (KeyError,ValueError,TypeError):qsource={}
        if qsource:
            qsource['id']='qqq_chart';sources.append(qsource)
            regime=policy.get('regime','UNKNOWN')
            bias=policy.get('bias','UNKNOWN')
            if bias not in ('BULLISH','BEARISH','NEUTRAL'):bias='UNKNOWN'
            for name in ('vwap','close'):
                if number(q.get(name)) and q[name]>0:
                    levels.append(dict(kind='SESSION_VWAP' if name=='vwap' else 'REFERENCE_PRICE',
                        price=q[name],source_id='qqq_chart',asof=qsource['observed_at'],received_at=qsource['received_at']))
        else:missing.append('Fresh completed QQQ chart with captured receipt unavailable')
    # Record actual provenance; source freshness is checked independently of worker heartbeat.
    for row in known:
        if row.get('id')=='QQQ' and phase=='PREMARKET':continue
        src=source(row,current,900 if row.get('status')=='FRESH' else 86400)
        if src:sources.append(dict(src,id='global:'+str(row.get('id')),status=row['status']))
    for key,row in (policy.get('factors') or {}).items():
        if key=='qqq':continue
        src=source(row,current)
        if src:sources.append(dict(src,id='vic:'+key))
    group_names=('futures','us','asia','europe','rates_fx','crypto','commodities')
    available_groups=sorted({r.get('group') for r in known if r.get('group') in group_names})
    for name in group_names:
        if name not in available_groups:missing.append('Global group missing/stale: '+name)
    events=[]
    for row in (raw or {}).get('events',[]):
        if isinstance(row,dict) and row.get('date')==day and row.get('impact')=='HIGH':
            events.append({k:deepcopy(row.get(k)) for k in ('id','title','source','scheduled_at','date','impact')})
    releases=[]
    for row in (raw or {}).get('economic_releases',[]):
        try:
            if ts(row['published_at'])<=ts(row['received_at'])<=current:
                releases.append(deepcopy(row))
        except (KeyError,ValueError,TypeError):continue
    if not releases:missing.append('Verified actual-versus-consensus release evidence unavailable')
    from shared_context import macro_context
    macro=macro_context(releases,current)
    family_order=(['trend_pullback','accepted_breakout','compression_expansion','failed_breakout_fade','range_reversion']
        if regime in ('BULLISH_TREND','BEARISH_TREND') else
        ['range_reversion','failed_breakout_fade','compression_expansion','accepted_breakout','trend_pullback'])
    # Premarket ranking only forms a conditional hypothesis; live alignment at
    # entry must still agree. Team7 is intentionally outside this router.
    if phase=='PREMARKET':family_order=['compression_expansion','accepted_breakout','trend_pullback','failed_breakout_fade','range_reversion']
    if active_ids is None:
        from team_settings import NAMES
        active_ids=set(NAMES)
    rankable=bool(qsource) and (phase=='PREMARKET' or regime in ('BULLISH_TREND','BEARISH_TREND','MIXED_OR_RANGE'))
    ranked=[]
    if rankable:
        for family in family_order:
            for team,kind in FAMILIES.items():
                if kind==family and team in active_ids:
                    ranked.append(dict(team_id=team,family=family,side='EITHER',
                        rationale='Conditional '+family+' preference; native setup, fresh price/volume, quote and existing risk rules must revalidate.'))
    expires=min(current+timedelta(minutes=90),closing-timedelta(minutes=15))
    if phase=='PREMARKET':expires=min(expires,opening+timedelta(minutes=50))
    status='READY' if rankable else 'INSUFFICIENT_DATA'
    summary=('Premarket conditional hypothesis' if phase=='PREMARKET' else 'Completed-chart conditional review')+': '+bias+'; '+regime+'. '
    summary+='Native charts may overturn this context. Missing evidence remains unknown; evidence coverage is not win confidence.'
    payload=dict(version=VERSION,status=status,paper=True,session_date=day,slot=slot,phase=phase,
        issued_at=current.isoformat(),valid_until=expires.isoformat(),bias=bias,regime=regime,
        source_cutoff=max((s['observed_at'] for s in sources),default=None),sources=sources,
        coverage=dict(qqq_chart_or_premarket=bool(qsource),global_groups=available_groups,
            global_groups_available=len(available_groups),global_groups_expected=len(group_names),
            vic_score_coverage=policy.get('coverage') if number(policy.get('coverage')) else None),
        uncertainty='UNVALIDATED_RULE_ROUTER',probability_green=None,summary=summary,
        levels=levels,strategies=ranked,events=events[:20],economic_releases=releases[-10:],macro_context=macro,
        scenarios={
            'bull':'Require a native CALL setup: accepted resistance break/retest or support pullback with fresh volume and completed-bar confirmation. Current VIC and executable quote must revalidate; price must remain inside the native entry zone with required target room.',
            'bear':'Require a native PUT setup: rejected resistance or failed support/retest with fresh volume and completed-bar confirmation. Bearish news alone does not create a PUT; the native entry zone, stop and target-room checks govern.',
            'invalidation':'Expire on stated clock, wrong session, unavailable/future/stale QQQ evidence, or an opposing native chart. Existing frozen position ownership, stop, exit and funding limits always govern. VIX alone never vetoes a trade.'},
        missing=missing,warnings=['Conditional research only; no calibrated return probability or new numeric trading targets.',
            'Morning forecasts remain immutable and expire independently; this review does not extend their weight.'],
        can_submit_orders=False,method='deterministic-family-router-v1')
    payload['plan_id']=digest(payload)
    return payload


def usable(plan,current):
    try:
        current=ts(current);opening,closing=session(plan['session_date'])
        issued,end=ts(plan['issued_at']),ts(plan['valid_until'])
        return (plan.get('version')==VERSION and plan.get('status')=='READY' and plan.get('paper') is True
            and plan['session_date']==str(current.date()) and issued<=current<end
            and end<=min(issued+timedelta(minutes=90),closing-timedelta(minutes=15))
            and plan.get('probability_green') is None and plan.get('can_submit_orders') is False
            and plan.get('plan_id')==digest({k:v for k,v in plan.items() if k!='plan_id'}))
    except (KeyError,ValueError,TypeError):return False


def read_plan(root,current):
    plan=load(Path(root)/'local_research_plan.json')
    return plan if usable(plan,current) else {}


def priority(plan,team_id,owner,alignment,current):
    if not usable(plan,current) or not number(alignment) or alignment<0 or team_id=='team7':return 0
    side='CALL' if owner=='hero' else 'PUT'
    for index,row in enumerate(plan.get('strategies',[])):
        if row.get('team_id')==team_id and row.get('side') in ('EITHER',side):return len(plan['strategies'])-index
    return 0


def compact(plan):
    if not isinstance(plan,dict) or plan.get('version')!=VERSION:return {'status':'UNAVAILABLE'}
    def text(value,limit=1200):return str(value)[:limit] if isinstance(value,str) else None
    def records(value):return value if isinstance(value,list) else []
    keys=('version','status','plan_id','session_date','slot','phase','issued_at','valid_until','bias','regime',
        'source_cutoff','uncertainty','summary')
    out={k:text(plan.get(k)) for k in keys}
    out.update(paper=plan.get('paper') is True,probability_green=None,sources=[],levels=[],strategies=[],scenarios={})
    coverage=plan.get('coverage') if isinstance(plan.get('coverage'),dict) else {}
    out['coverage']={k:v for k,v in coverage.items() if k in ('qqq_chart_or_premarket','global_groups_available',
        'global_groups_expected','vic_score_coverage') and (number(v) or isinstance(v,bool))}
    out['coverage']['global_groups']=[text(v,60) for v in records(coverage.get('global_groups'))[:7] if isinstance(v,str)]
    for row in records(plan.get('sources'))[:40]:
        if isinstance(row,dict):out['sources'].append({k:text(row.get(k),300) for k in (
            'id','source','source_code','input_digest','observation_digest','observed_at','received_at','status')})
    for row in records(plan.get('levels'))[:20]:
        if isinstance(row,dict) and number(row.get('price')):
            out['levels'].append({k:text(row.get(k),100) for k in ('kind','source_id','asof','received_at')} | {'price':row['price']})
    for row in records(plan.get('strategies'))[:10]:
        if isinstance(row,dict) and row.get('team_id') in FAMILIES:
            out['strategies'].append({k:text(row.get(k),600) for k in ('team_id','family','side','rationale')})
    scenarios=plan.get('scenarios') if isinstance(plan.get('scenarios'),dict) else {}
    for key in ('bull','bear','invalidation'):out['scenarios'][key]=text(scenarios.get(key))
    for key in ('missing','warnings'):out[key]=[text(v,300) for v in records(plan.get(key))[:30] if isinstance(v,str)]
    return out


def compact_receipt(raw):
    """Only a bounded engine acknowledgement, never arbitrary worker content."""
    import re
    from telemetry_link import stamp
    raw=raw if isinstance(raw,dict) else {}
    out={'version':'local-research-receipt-v1','can_submit_orders':False}
    for key,allowed in {
        'status':{'RECEIVED','UNAVAILABLE'},
        'mode':{'PREMARKET_ONLY','REGULAR_SESSION'},
        'publication_status':{'READY','PENDING','INSUFFICIENT_DATA','MISSED_DEADLINE','INVALID_ARCHIVE','UNAVAILABLE'},
        'slot':set(SLOTS)}.items():
        out[key]=raw.get(key) if isinstance(raw.get(key),str) and raw[key] in allowed else None
    for key,pattern in (('plan_id',r'[a-f0-9]{20}'),('session_date',r'\d{4}-\d{2}-\d{2}')):
        value=raw.get(key)
        out[key]=value if isinstance(value,str) and re.fullmatch(pattern,value) else None
    for key in ('received_at','checked_at','issued_at','valid_until'):out[key]=stamp(raw.get(key))
    return out


def receipt(root,plan,current,previous=None,premarket=False):
    raw=plan or load(Path(root)/'local_research_plan.json')
    previous=previous or {}
    valid=usable(plan,current)
    return compact_receipt(dict(status='RECEIVED' if valid else 'UNAVAILABLE',
        mode='PREMARKET_ONLY' if premarket else 'REGULAR_SESSION',
        publication_status=raw.get('status','UNAVAILABLE'),plan_id=plan.get('plan_id'),
        session_date=plan.get('session_date',str(ts(current).date())),slot=raw.get('slot'),
        issued_at=plan.get('issued_at'),valid_until=plan.get('valid_until'),
        received_at=(previous.get('received_at') if valid and previous.get('plan_id')==plan.get('plan_id')
                     else current.isoformat() if valid else None),checked_at=current.isoformat()))


def recover_latest(root,current):
    """Repair an interrupted pointer write; a newer bad archive is a barrier.

    Archive bytes are immutable. Never fall back through a failed/tampered refresh
    to an older READY result. A pending newer slot also invalidates old context.
    """
    from vic import atomic_json
    root=Path(root);current=ts(current);day=target_day(current);opening,closing=session(day)
    latest=None
    for slot in SLOTS:
        due=opening.replace(hour=int(slot[:2]),minute=int(slot[2:]),second=0,microsecond=0)
        path=root/'overnight_data'/'reviews'/day/(slot+'.json')
        if due<=current and due<closing-timedelta(minutes=15) and path.exists():latest=(slot,due,path)
    if latest is None:return
    slot,due,path=latest;plan=load(path)
    valid=False
    try:
        valid=(plan.get('version')==VERSION and plan.get('paper') is True
            and plan.get('session_date')==day and plan.get('slot')==slot
            and plan.get('status') in ('READY','INSUFFICIENT_DATA','MISSED_DEADLINE')
            and ts(plan['issued_at'])<=current and ts(plan['scheduled_at'])==due
            and plan.get('plan_id')==digest({k:v for k,v in plan.items() if k!='plan_id'}))
    except (KeyError,TypeError,ValueError):pass
    if not valid:
        plan=dict(version=VERSION,status='INVALID_ARCHIVE',paper=True,session_date=day,
                  slot=slot,scheduled_at=due.isoformat(),can_submit_orders=False)
    pointer=root/'local_research_plan.json';old=load(pointer)
    if old.get('session_date')==day and old.get('status')=='PENDING' and old.get('slot','')>slot:
        return
    if old!=plan:atomic_json(pointer,plan)


def publish_due(root,raw,current):
    from vic import atomic_json
    root=Path(root);current=ts(current);day=target_day(current);opening,closing=session(day)
    directory=root/'overnight_data'/'reviews'/day;published=[]
    recover_latest(root,current)
    for slot in SLOTS:
        due=opening.replace(hour=int(slot[:2]),minute=int(slot[2:]),second=0,microsecond=0)
        path=directory/(slot+'.json')
        if current<due or due>=closing-timedelta(minutes=15) or path.exists():continue
        delay=(current-due).total_seconds()
        if delay>90:
            plan=dict(version=VERSION,status='MISSED_DEADLINE',paper=True,session_date=day,slot=slot,
                issued_at=current.isoformat(),scheduled_at=due.isoformat(),can_submit_orders=False)
        else:
            plan=build(raw,load(root/'vic_telemetry.json'),current,slot)
            plan['scheduled_at']=due.isoformat()
            plan['publication_delay_seconds']=round(delay,2)
            if plan['status']!='READY' and delay<90:
                # A transient pointer is not an immutable final publication. It
                # makes an older review unavailable while fresh inputs arrive.
                plan.update(status='PENDING',strategies=[])
                plan['plan_id']=digest({k:v for k,v in plan.items() if k!='plan_id'})
                atomic_json(root/'local_research_plan.json',plan)
                continue
        plan['plan_id']=digest({k:v for k,v in plan.items() if k!='plan_id'})
        directory.mkdir(parents=True,exist_ok=True);atomic_json(path,plan);published.append(plan)
        # A failed scheduled refresh invalidates a prior local plan instead of
        # disguising the absence of current evidence. The remote plan is separate.
        atomic_json(root/'local_research_plan.json',plan)
    return published
