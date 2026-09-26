"""Append-only decision/outcome journals. Offline research cannot change config."""
from pathlib import Path
import json, math, os, fcntl
import pandas as pd
import numpy as np

BASE_DIR=Path(__file__).resolve().parent
LEARN_DIR=BASE_DIR/'research_data'
LEARN_LOG_FILE=LEARN_DIR/'hero_v3_events.jsonl'
OUTCOME_FILE=LEARN_DIR/'hero_v3_outcomes.jsonl'


def json_safe(x):
    if isinstance(x,dict): return {str(k):json_safe(v) for k,v in x.items()}
    if isinstance(x,(list,tuple)): return [json_safe(v) for v in x]
    if isinstance(x,(np.integer,)): return int(x)
    if isinstance(x,(float,np.floating)): return float(x) if math.isfinite(x) else None
    if isinstance(x,(pd.Timestamp,)): return x.isoformat()
    return x


def append_event(event,path=LEARN_LOG_FILE):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    line=json.dumps(json_safe(event),allow_nan=False,separators=(',',':'))+'\n'
    with path.open('a') as f:
        fcntl.flock(f,fcntl.LOCK_EX)
        f.write(line);f.flush();os.fsync(f.fileno())
        fcntl.flock(f,fcntl.LOCK_UN)


def read_events(path=LEARN_LOG_FILE):
    path=Path(path)
    if not path.exists(): return []
    with path.open() as f:
        # Malformed journals fail visibly; never silently skip data.
        return [json.loads(line) for line in f if line.strip()]


def candidate_record(candidate,features,*,final_state,reason_code,vic=None,option=None,alpha=None):
    return {'schema_version':'3.0','event':'CANDIDATE','event_id':candidate['setup_id'],
            'candidate':candidate,'market':features,'vic':vic,'option':option,'alpha':alpha,
            'final_state':final_state,'reason_code':reason_code}


def resolve_candidate_path(record,df_1m,*,as_of,session_close):
    """Full-session underlying path; not an executable options backtest.
    Require exact contiguous 1m coverage. No tail fallback, same-date only.
    Ambiguous target/stop ordering is null, not guessed as a win or loss.
    """
    c=record['candidate']; start=pd.Timestamp(c['decision_ts']); end=pd.Timestamp(session_close)
    now=pd.Timestamp(as_of)
    if any(t.tzinfo is None for t in (start,end,now)) or df_1m.index.tz is None:
        raise ValueError('TIMEZONE_REQUIRED')
    end=end.tz_convert(start.tz)
    now=now.tz_convert(start.tz)
    result={'event':'OUTCOME','setup_id':c['setup_id'],'resolved':False,'reason_code':'INCOMPLETE_SESSION'}
    if now<end or end<=start or end.tz_convert(start.tz).date()!=start.date(): return result
    bars=df_1m.copy();bars.index=bars.index.tz_convert(start.tz)
    first=start.ceil('min')
    bars=bars[(bars.index>=first)&(bars.index<end)]
    grid=pd.date_range(first,end-pd.Timedelta(minutes=1),freq='1min')
    if not bars.index.equals(grid) or bars.empty:
        result['reason_code']='MISSING_OR_DUPLICATE_1M_BARS';return result
    if not np.isfinite(bars[['Open','High','Low','Close']].to_numpy(dtype=float)).all():
        result['reason_code']='INVALID_PATH_DATA';return result
    sign=1 if c['direction']=='CALL' else -1
    entry,r,stop=c['entry_spot'],c['initial_r'],c['stop']
    if r<=0: raise ValueError('INVALID_FROZEN_R')
    favorable=(bars.High-entry)/r if sign==1 else (entry-bars.Low)/r
    adverse=(bars.Low-entry)/r if sign==1 else (entry-bars.High)/r
    stop_mask=bars.Low<=stop if sign==1 else bars.High>=stop
    stop_time=bars.index[stop_mask][0] if stop_mask.any() else None
    paths={};ambiguous=False
    for name,level in c['targets'].items():
        if level is None or not math.isfinite(level) or sign*(level-entry)<=0:
            paths[name]={'eligible':False,'reason_code':'TARGET_NOT_AHEAD'};continue
        mask=bars.High>=level if sign==1 else bars.Low<=level
        hit=bars.index[mask][0] if mask.any() else None
        tie=hit is not None and stop_time is not None and hit==stop_time
        ambiguous |= tie
        before=None if tie else bool(hit is not None and (stop_time is None or hit<stop_time))
        outcome=None if tie else sign*(level-entry)/r if before else -1. if stop_time is not None else sign*(float(bars.Close.iloc[-1])-entry)/r
        paths[name]={'eligible':True,'hit_before_stop':before,'path_ambiguous':tie,
                     'first_touch_bar':hit.isoformat() if hit is not None else None,
                     'time_to_touch_minutes':(hit+pd.Timedelta(minutes=1)-start).total_seconds()/60 if hit is not None else None,
                     'underlying_result_r':outcome}
    returns={}
    for minutes in (5,15,30,60):
        label=start+pd.Timedelta(minutes=minutes-1)
        returns[str(minutes)]=sign*(float(bars.loc[label,'Close'])-entry)/r if label in bars.index else None
    selected=paths.get(c['target_model'],{})
    result.update(resolved=True,reason_code='RESOLVED',path_ambiguous=ambiguous,
        mfe_r=max(0.,float(favorable.max())),mae_r=min(0.,float(adverse.min())),
        excursion_scope='FULL_SESSION_UNDERLYING',paths=paths,returns_r=returns,
        r_eod=sign*(float(bars.Close.iloc[-1])-entry)/r,
        stop_first_touch_bar=stop_time.isoformat() if stop_time is not None else None,
        underlying_result_r=selected.get('underlying_result_r'),
        actual_option_pnl=None,costs_included=False)
    return result


def comparison_report(events,outcomes):
    # Replay can repeat append after a crash; deterministic IDs deduplicate analytically.
    decisions={r['candidate']['setup_id']:r for r in events if r.get('event')=='CANDIDATE'}
    resolved={r['setup_id']:r for r in outcomes if r.get('resolved')}
    rows=[]
    for sid,rec in decisions.items():
        o=resolved.get(sid);c=rec['candidate']
        if not o: continue
        row={'strategy':c['strategy_version'],'mode':c['mode'],'ticker':c['ticker'],
             'time':c['decision_ts'],'state':rec['final_state'],'r':o.get('underlying_result_r'),
             'mfe':o['mfe_r'],'mae':o['mae_r'],'ambiguous':o['path_ambiguous'],
             'extension_bin':c.get('extension_bin'),'attempt':c.get('breach',{}).get('attempt_number'),
             'vic':(rec.get('vic') or {}).get('verdict'),
             'rvol_percentile':rec['market'].get('rvol',{}).get('percentile'),
             'width_percentile':rec['market'].get('orb_width_context',{}).get('percentile')}
        rows.append(row)
    groups={}
    if not rows: return {'status':'NO_RESOLVED_COMPARABLE_DATA','candidate_count':len(decisions)}
    df=pd.DataFrame(rows).sort_values('time')
    df['hour']=df.time.str[11:13];df['date']=df.time.str[:10]
    df['rvol_bucket']=pd.cut(df.rvol_percentile,[-1,25,50,75,100]).astype(str)
    df['width_bucket']=pd.cut(df.width_percentile,[-1,25,50,75,100]).astype(str)
    for dimension in ('all','ticker','hour','rvol_bucket','width_bucket','extension_bin','attempt','vic'):
        keys=['strategy','mode']+([] if dimension=='all' else [dimension])
        for key,g in df.groupby(keys,dropna=False):
            clean=g.dropna(subset=['r']);v=clean.r.astype(float);curve=np.r_[0,v.cumsum().to_numpy()]
            losers=-v[v<0].sum()
            groups[str((dimension,key))]={'N':len(v),'N_resolved':len(g),'N_ambiguous':int(g.ambiguous.sum()),
                'win_rate':float((v>0).mean()) if len(v) else None,'expectancy_r':float(v.mean()) if len(v) else None,
                'median_r':float(v.median()) if len(v) else None,'profit_factor':float(v[v>0].sum()/losers) if losers else None,
                'sequential_unit_r_drawdown':float((np.maximum.accumulate(curve)-curve).max()),
                'mfe_r':float(g.mfe.mean()),'mae_r':float(g.mae.mean()),
                'candidates_per_observed_day':len(g)/g.date.nunique(),
                'false_rejection_rate':float((clean[clean.state.isin(['REJECTED','BLOCKED','VETOED'])].r>0).mean()) if len(clean[clean.state.isin(['REJECTED','BLOCKED','VETOED'])]) else None}
    return {'scope':'GROSS_UNDERLYING_COUNTERFACTUAL_NOT_OPTIONS_OR_PORTFOLIO_BACKTEST','groups':groups,
            'limitations':['Overlapping signals are not independent trades','Costs and fill delay not simulated',
                          'Baseline preserves raw continuation condition, not full legacy execution gates']}
