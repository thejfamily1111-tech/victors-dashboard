"""Dashboard transport allowlist for public research; no raw state or environment."""
import re
from urllib.parse import urlsplit


def clean_text(value,limit=700):
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]','',str(value or ''))[:limit]


def compact(raw):
    from telemetry_link import enum, signed, numeric, stamp
    raw=raw if isinstance(raw,dict) else {}
    out={k:enum(raw.get(k),v) for k,v in {
        'status':{'ACTIVE','UNAVAILABLE'},'version':{'overnight-v1.4.0'},
        'direction':{'BULLISH','BEARISH','NEUTRAL','UNKNOWN'},
        'move_from_entry':{'BULLISH','BEARISH','NEUTRAL','UNKNOWN'}}.items()}
    out['forecast_id']=raw.get('forecast_id') if re.fullmatch('[a-f0-9]{20}',str(raw.get('forecast_id',''))) else None
    for k in ('issued_at','valid_until'):out[k]=stamp(raw.get(k))
    for k in ('score','weight','score_before','hold_estimate'):out[k]=signed(raw.get(k))
    out['probability_green']=None
    return out


def brief(raw):
    from telemetry_link import enum, signed, numeric, stamp, records
    if not isinstance(raw,dict) or raw.get('version')!='overnight-v1.4.0':return {}
    out={k:clean_text(raw.get(k),80) for k in ('version','session_date','slot','status','forecast_id')}
    for k in ('issued_at','data_cutoff','valid_until','session_open','session_close','hold_until','scheduled_at'):out[k]=stamp(raw.get(k))
    out['direction']=enum(raw.get('direction'),{'BULLISH','BEARISH','NEUTRAL','UNKNOWN'})
    for k in ('score','coverage','publication_delay_seconds'):out[k]=signed(raw.get(k))
    out.update(probability_green=None,probability_status='UNCALIBRATED',forecast={},observations=[],news=[],events=[],economic_releases=[])
    f=raw.get('forecast') or {}
    for k in ('anchor','previous_close','typical_range_pct','tilt_pct','analogs'):out['forecast'][k]=numeric(f.get(k)) if k!='tilt_pct' else signed(f.get(k))
    out['forecast']['from_anchor']=enum(f.get('from_anchor'),{'BULLISH','BEARISH','NEUTRAL','UNKNOWN'})
    for k in ('low','high','close','hold','5m','10m','15m','30m','60m'):
        value=f.get(k) or {};out['forecast'][k]={n:numeric(value.get(n)) for n in ('estimate','lower','upper','samples')}
    for r in records(raw.get('observations'))[:40]:
        row={k:clean_text(r.get(k),200) for k in ('id','group','status','source','observation_date')}
        for k in ('value','change_pct','change_bps'):row[k]=signed(r.get(k))
        for k in ('observed_at','received_at','baseline_at'):row[k]=stamp(r.get(k))
        row['eligible']=r.get('eligible') is True;out['observations'].append(row)
    for r in records(raw.get('news'))[:20]:
        url=urlsplit(str(r.get('url','')))
        safe_url=url._replace(query='',fragment='').geturl() if url.scheme=='https' and url.hostname and not url.username else ''
        out['news'].append({**{k:clean_text(r.get(k),260) for k in ('id','title','source')},'url':safe_url[:400],
            'published_at':stamp(r.get('published_at')),'received_at':stamp(r.get('received_at')),
            'first_observed_at':stamp(r.get('first_observed_at')),
            'receipt_basis':clean_text(r.get('receipt_basis'),60)})
    for r in records(raw.get('events'))[:20]:
        out['events'].append({'title':clean_text(r.get('title'),200),'scheduled_at':stamp(r.get('scheduled_at')),
            'date':clean_text(r.get('date'),10),'impact':enum(r.get('impact'),{'HIGH'}),'source':clean_text(r.get('source'),100)})
    for r in records(raw.get('economic_releases'))[:10]:
        out['economic_releases'].append({**{k:clean_text(r.get(k),160) for k in ('id','title','source','unit')},
            'actual':signed(r.get('actual')),'consensus':signed(r.get('consensus')),'published_at':stamp(r.get('published_at')),'received_at':stamp(r.get('received_at'))})
    out['warnings']=[clean_text(s,220) for s in raw.get('warnings',[])[:20] if isinstance(s,str)]
    ai=raw.get('ai') or {}
    out['ai']={k:clean_text(ai.get(k),1200 if k!='status' else 50) for k in ('status','summary','bull_case','bear_case','invalidation','stance')}
    from overnight_ai import sanitize_diagnostic
    if ai.get('diagnostic'):out['ai']['diagnostic']=sanitize_diagnostic(ai['diagnostic'])
    out['ai']['evidence_ids']=[clean_text(s,80) for s in ai.get('evidence_ids',[])[:30] if isinstance(s,str)]
    out['ai']['usage']={k:numeric((ai.get('usage') or {}).get(k)) for k in ('input_tokens','output_tokens','total_tokens')}
    return out


def telemetry(raw):
    from telemetry_link import stamp, sanitize_control_receipt
    from local_research_plan import compact as review_compact
    if not isinstance(raw,dict):return None
    from overnight_credentials import compact_configuration
    worker=raw.get('worker') if isinstance(raw.get('worker'),dict) else {}
    identity=worker.get('instance_id')
    return {'version':'overnight-v1.4.0','heartbeat':stamp(raw.get('heartbeat')),
        'control_receipt':sanitize_control_receipt(raw.get('control_receipt')),
        'worker':{'instance_id':identity if isinstance(identity,str) and re.fullmatch(r'[a-f0-9]{32}',identity) else None,
            'started_at':stamp(worker.get('started_at')),
            'release':worker.get('release') if worker.get('release') in {'Victor_Paper_v1.7.1','Victor_Paper_v1.7.2'} else None},
        'ai_configuration':compact_configuration(raw.get('ai_configuration')),
        'ai_last_success_at':stamp(raw.get('ai_last_success_at')),
        'session_date':clean_text(raw.get('session_date'),10),'worker_status':clean_text(raw.get('worker_status'),50),
        'brief':brief(raw.get('brief')),'monitor':brief(raw.get('monitor')),
        'scheduled_briefs':[brief(r) for r in raw.get('scheduled_briefs',[])[:2] if isinstance(r,dict)],
        'local_review':review_compact(raw.get('local_review')),
        'scheduled_reviews':[review_compact(r) for r in raw.get('scheduled_reviews',[])[:4] if isinstance(r,dict)]}
