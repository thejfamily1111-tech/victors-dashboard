"""Read-only dashboard / write-only Mac transport. No broker API dependencies."""
from datetime import datetime, timezone
import json
import math
import re
import ssl
from urllib import request, error

MAX_BYTES = 1_000_000
# Existing deployed vt_write SQL limits jsonb text to 900,000 bytes. Leave room
# for PostgreSQL's canonical JSON representation and the RPC envelope.
SNAPSHOT_BUDGET = 850_000
BETA_ERRORS = {'BETA_UNAVAILABLE', 'BETA_INVALID', 'BETA_TOO_LARGE'}
CONTROL_KEYS = ('qqq_trading_enabled', 'qqq_research_enabled',
                'overnight_research_enabled', 'vic_enabled', 'beta_engine_enabled')
COMPONENT_KEYS = {'qqq_trading', 'qqq_research', 'overnight_research', 'vic', 'beta_engine'}
COMPONENT_STATES = {'RUNNING', 'OFF', 'DRAINING', 'WAITING_SCHEDULE', 'STARTING',
                    'STOPPING', 'STOPPED', 'ERROR', 'UNKNOWN', 'STALE', 'OFFLINE',
                    'PROTECTING_POSITIONS', 'WAITING', 'WAITING_FOR_WORKER'}
HEALTH = {'STARTING','MARKET_CLOSED','ORDER_PENDING','MANAGING_POSITION','ENTRY_PAUSED','SCANNING','ERROR','ATTENTION','STOPPED','GREEN','RED','YELLOW','UNKNOWN'}
STATUS = {'new','accepted','pending_new','partially_filled','filled','done_for_day','canceled','expired','replaced','pending_cancel','pending_replace','accepted_for_bidding','stopped','rejected','suspended','calculated','held','intent','submitted','partial','unknown','close_pending'}
SIDE = {'buy','sell','long','short','buy_to_open','sell_to_close'}

def stamp(value):
    if not isinstance(value,str): return None
    try:
        dt = datetime.fromisoformat(value.replace('Z','+00:00'))
        if dt.tzinfo is None: return None
        return dt.astimezone(timezone.utc).isoformat()
    except (ValueError, OverflowError): return None


def utcnow(): return datetime.now(timezone.utc).isoformat()


def numeric(value):
    if isinstance(value,bool): return None
    try:
        n=float(value)
        return n if math.isfinite(n) and 0 <= n <= 1_000_000_000 else None
    except (ValueError,TypeError,OverflowError): return None


def enum(value, options):
    return value if isinstance(value,str) and value in options else None


def contract(value):
    return value if isinstance(value,str) and re.fullmatch(r'QQQ\d{6}[CP]\d{8}',value) else None


def records(value):
    if isinstance(value,dict): value=list(value.values())
    return [r for r in value[-100:] if isinstance(r,dict)] if isinstance(value,list) else []


def sanitize_report(raw):
    """Positive field/value allowlist. Never serialize whole executor dictionaries."""
    if not isinstance(raw,dict) or raw.get('paper') is not True: return None
    result={'paper':True,'heartbeat':stamp(raw.get('heartbeat')),
            'health':enum(raw.get('health'),HEALTH) or 'UNKNOWN',
            'orders':[],'positions':[],'activities':[]}
    for key,values in [('stock_feed',{'iex','sip','delayed_sip'}),('option_feed',{'indicative','opra'})]:
        val=enum(raw.get(key),values)
        if val: result[key]=val
    for row in records(raw.get('orders')):
        symbol=contract(row.get('symbol') or row.get('contract_symbol'))
        if not symbol or row.get('ticker')!='QQQ': continue
        result['orders'].append({'ticker':'QQQ','symbol':symbol,
            'side':enum(row.get('side'),SIDE),
            'status':enum(str(row.get('status',row.get('state',''))).lower(),STATUS) or 'unknown',
            'qty':numeric(row.get('qty',row.get('quantity'))),
            'filled_qty':numeric(row.get('filled_qty')),'owned_qty':numeric(row.get('owned_qty')),
            'avg_fill_price':numeric(row.get('avg_fill_price')),
            'submitted_at':stamp(row.get('submitted_at')),'updated_at':stamp(row.get('updated_at'))})
    for row in records(raw.get('positions')):
        symbol=contract(row.get('symbol'))
        if symbol: result['positions'].append({'symbol':symbol,'qty':numeric(row.get('qty')),
            'side':enum(row.get('side'),SIDE),'avg_entry_price':numeric(row.get('avg_entry_price')),
            'current_price':numeric(row.get('current_price'))})
    for row in records(raw.get('activities')):
        symbol=contract(row.get('symbol'))
        kind=enum(row.get('type'),{'ENTRY_FILLED','EXIT_FILLED'})
        if symbol and kind: result['activities'].append({'symbol':symbol,'type':kind,
            'timestamp':stamp(row.get('timestamp')),'qty':numeric(row.get('qty')),
            'price':numeric(row.get('price')),'side':enum(row.get('side'),SIDE),
            'status':enum(str(row.get('status','')).lower(),STATUS) or 'unknown'})
    return result


def sanitize_direction(raw):
    if not isinstance(raw,dict) or not raw:return {}
    allowed={'qqq','mag7','volatility','treasury','semiconductors','news_event','breadth'}
    out={'mode':enum(raw.get('mode'),{'ACTIVE'}) or 'UNKNOWN',
         'at':stamp(raw.get('at')),'bar_end':stamp(raw.get('bar_end')),
         'bias':enum(raw.get('bias'),{'BULLISH','BEARISH','NEUTRAL'}) or 'UNKNOWN',
         'score':signed(raw.get('score')),'coverage':numeric(raw.get('coverage')),
         'missing':[x for x in raw.get('missing',[]) if isinstance(x,str) and x in allowed] if isinstance(raw.get('missing'),list) else [],'factors':{}}
    for k,f in mapping(raw.get('factors')).items():
        if k not in allowed or not isinstance(f,dict):continue
        out['factors'][k]={'value':signed(f.get('value')),'at':stamp(f.get('at')),
                           'source_code':enum(f.get('source_code'),{'QQQ','QQQ_DERIVED','MAG7','MAG7_WEIGHTED','QQQE','^VXN','^VIX','^TNX','VXN','VIX','TNX','IEF_PROXY','SMH','NEWS_EVENT'}),
                           'change_pct_15m':signed(f.get('change_pct_15m')),
                           'change_pct':signed(f.get('change_pct'))}
    breadth=mapping(raw.get('mag7'))
    out['mag7']={k:numeric(breadth.get(k)) for k in ('available','green','red','flat')}
    out['mag7']['confirmed']=breadth.get('confirmed') is True
    from overnight_schema import compact
    out['overnight']=compact(raw.get('overnight'))
    return out


POLICY_VERSIONS={'vic-policy-v2','vic-policy-v3'}
QQQ_QUALITY={'FRESH','NO_COMPLETED_QQQ_BARS','NO_QQQ_BAR_KNOWN_BY_DECISION','QQQ_FIVE_MINUTE_BAR_STALE',
    'QQQ_RECENT_BAR_GAP','QQQ_FEATURE_WARMUP_OR_INVALID','PREVIOUS_SESSION_CALENDAR_UNAVAILABLE',
    'PREVIOUS_SESSION_COMPLETE_CLOSE_UNAVAILABLE','QQQ_NOT_YET_ENGINE_VISIBLE','UNKNOWN'}
MACRO_STATUS={'ACTIVE_UNVALIDATED_HEURISTIC','UNAVAILABLE_NEUTRAL','UNKNOWN_UNMAPPED_OR_INCOMPLETE',
    'NOT_YET_AVAILABLE_OR_TIME_ORDER_ERROR','STALE','MISSING_VALUE_OR_SOURCE','UNKNOWN_UNMAPPED_SERIES',
    'UNKNOWN_UNITS_OR_PERIOD','UNKNOWN_INITIAL_RELEASE_NOT_CONFIRMED','MISSING_RELEASE_OR_CONSENSUS_PROVENANCE',
    'CONSENSUS_NOT_KNOWN_BEFORE_RELEASE','MISSING_OR_INVALID_AVAILABILITY_OR_CONSENSUS'}
FEED_KEYS={'minutes','stocks','indices','news','holdings','releases'}
STOCK_FEEDS={'iex','sip','delayed_sip','UNKNOWN'}
OPTION_FEEDS={'indicative','opra','UNKNOWN'}


def mapping(value):return value if isinstance(value,dict) else {}


def bounded(value,low,high):
    # New public quality fields accept JSON numbers only, never numeric strings.
    return value if isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and low<=value<=high else None


def sanitize_macro(raw):
    raw=mapping(raw)
    if raw.get('version')!='macro-surprise-v1':return {}
    out={'version':'macro-surprise-v1','status':enum(raw.get('status'),MACRO_STATUS) or 'UNAVAILABLE_NEUTRAL',
         'horizon':enum(raw.get('horizon'),{'15M_ONLY'}),'weight':bounded(raw.get('weight'),0,.05),
         'score_delta':bounded(raw.get('score_delta'),-.05,.05),
         'applied_score_delta':bounded(raw.get('applied_score_delta'),-.05,.05),
         'accepted_count':bounded(raw.get('accepted_count'),0,100),'probability_green':None,'evidence':[]}
    for row in records(raw.get('evidence'))[-20:]:
        clean={'status':enum(row.get('status'),MACRO_STATUS) or 'UNKNOWN_UNMAPPED_OR_INCOMPLETE',
            'series_id':enum(row.get('series_id'),{'US_CPI_ALL_ITEMS_MOM','US_CPI_CORE_MOM','US_PCE_PRICE_MOM','US_PCE_CORE_MOM'}),
            'unit':enum(row.get('unit'),{'percent'}),'period_type':enum(row.get('period_type'),{'MOM'}),
            'initial_release':row.get('initial_release') is True}
        for key in ('published_at','received_at','engine_received_at','consensus_asof','consensus_received_at'):
            clean[key]=stamp(row.get(key))
        for key in ('actual','consensus','surprise_pp'):clean[key]=bounded(row.get(key),-100,100)
        out['evidence'].append(clean)
    return out


def sanitize_data_contract(raw):
    raw=mapping(raw)
    if raw.get('version')!='shared-context-v1':return {}
    out={'version':'shared-context-v1','effective_stock_feed':enum(raw.get('effective_stock_feed'),STOCK_FEEDS) or 'UNKNOWN',
        'effective_option_feed':enum(raw.get('effective_option_feed'),OPTION_FEEDS) or 'UNKNOWN','source_receipts':{}}
    for name,row in mapping(raw.get('source_receipts')).items():
        if name not in FEED_KEYS or not isinstance(row,dict):continue
        clean={'availability_status':enum(row.get('availability_status'),{'CAPTURED','UNKNOWN_NO_CAPTURED_RECEIPT'}) or 'UNKNOWN_NO_CAPTURED_RECEIPT',
            'provider':enum(row.get('provider'),{'Alpaca','Yahoo via yfinance','Alpaca news','User-supplied structured feed','QQQ holdings input'}),
            'feed':enum(row.get('feed'),STOCK_FEEDS|{'5-minute index history; delay unverified','news','vic_inputs/economic_releases.json','holdings'})}
        for key in ('request_started_at','network_completed_at','received_at','engine_received_at'):clean[key]=stamp(row.get(key))
        for key in ('request_seconds','consumption_delay_seconds'):clean[key]=bounded(row.get(key),0,86400)
        out['source_receipts'][name]=clean
    return out


def sanitize_feed_health(raw):
    raw=mapping(raw)
    if not raw:return {}
    out={key:stamp(raw.get(key)) for key in ('last_completed_minute','last_complete_five_minute_bar')}
    for key in ('latest_minute_age_seconds','five_minute_bar_age_seconds'):out[key]=bounded(raw.get(key),-3600,604800)
    out['jobs']={}
    for name,row in mapping(raw.get('jobs')).items():
        if name not in FEED_KEYS or not isinstance(row,dict):continue
        out['jobs'][name]={'pending':row.get('pending') is True,'pending_seconds':bounded(row.get('pending_seconds'),0,86400),
            'last_receipt':stamp(row.get('last_receipt')),'error':'DATA_SOURCE_ERROR' if row.get('error') else None}
    return out


def sanitize_plan(raw):
    raw=mapping(raw)
    if raw.get('version')!='team13-confirm-risk-v1':return {}
    out={'version':'team13-confirm-risk-v1','side':enum(raw.get('side'),{'CALL','PUT'}),
        'status':enum(raw.get('status'),{'ARMED','CONFIRMED'}),
        'plan_id':raw.get('plan_id') if isinstance(raw.get('plan_id'),str) and re.fullmatch(r'[a-f0-9]{20}',raw['plan_id']) else None}
    for key in ('armed_at','confirmed_at','confirm_bar_end','structure_asof'):out[key]=stamp(raw.get(key))
    for key in ('trigger_close','confirmation_close','stop_price','target_level','fill_zone_low','fill_zone_high','underlying_risk','room_r',
                'ordered_quantity','ordered_premium','risk_ceiling','max_trade_loss','premium_stop_fraction','max_hold_minutes',
                'floor_arm_r','floor_peak_fraction','scale_r','full_target_r'):
        out[key]=bounded(raw.get(key),0,1000000)
    return out


def sanitize_provenance(raw):
    raw=mapping(raw)
    from team_settings import NAMES
    if raw.get('team_id') not in NAMES or raw.get('strategy_version') not in ('paper-v1.7.0','paper-v1.7.1'):return {}
    out={key:raw.get(key) for key in ('strategy_version','team_id')}
    for key in ('roster_version','label','entry_label','exit_label','source_rule'):
        value=raw.get(key)
        out[key]=value[:1600] if isinstance(value,str) and not any(ord(c)<32 for c in value) else None
    out['display_team_number']=bounded(raw.get('display_team_number'),1,10)
    out['captured_at']=stamp(raw.get('captured_at'))
    out['config_hash']=raw.get('config_hash') if isinstance(raw.get('config_hash'),str) and re.fullmatch(r'[a-f0-9]{64}',raw['config_hash']) else None
    out['code_sha256']={k:v for k,v in mapping(raw.get('code_sha256')).items()
        if isinstance(k,str) and re.fullmatch(r'(?:report_rules/)?[a-z0-9_]+\.py',k)
        and isinstance(v,str) and re.fullmatch(r'[a-f0-9]{64}',v)}
    return out


def sanitize_cluster(value):
    if not isinstance(value,str):return None
    parts=value.split(':',2)
    return value if len(parts)==3 and parts[0]=='QQQ' and parts[1] in {'CALL','PUT'} and stamp(parts[2]) else None


def sanitize_engine_status(raw):
    raw=mapping(raw)
    if raw.get('release') not in {'Victor_Paper_v1.5.0','Victor_Paper_v1.7.0','Victor_Paper_v1.7.1'}:return {}
    reconciliation=mapping(raw.get('reconciliation'))
    # Never transfer raw broker error strings or account/funding dictionaries.
    issues=reconciliation.get('issues')
    count=len(issues) if isinstance(issues,list) else bounded(reconciliation.get('issue_count'),0,1000)
    from team_settings import NAMES
    return {'release':raw['release'],'active_team_ids':[t for t in raw.get('active_team_ids',[]) if t in NAMES],
        'release_manifest_sha256':raw.get('release_manifest_sha256') if isinstance(raw.get('release_manifest_sha256'),str) and re.fullmatch(r'[a-f0-9]{64}',raw['release_manifest_sha256']) else None,
        'roster_version':enum(raw.get('roster_version'),{'paper10-2026-10-12-v1'}),
        'reconciliation':{'ok':reconciliation.get('ok') if type(reconciliation.get('ok')) is bool else None,
        'checked_at':stamp(reconciliation.get('checked_at')),'issue_count':count,
        'status':'VERIFIED' if reconciliation.get('ok') is True else 'ATTENTION_ENTRIES_PAUSED' if reconciliation.get('ok') is False else 'UNKNOWN'},
        'owned_quote_batch_ms':bounded(raw.get('owned_quote_batch_ms'),0,3600000),
        'entry_pause_active':raw.get('entry_pause_active') is True,
        'entry_pause_observed_at':stamp(raw.get('entry_pause_observed_at')),
        'control_receipt':sanitize_control_receipt(raw.get('control_receipt'))}


def sanitize_control_receipt(raw):
    """A worker acknowledgement, never process arguments, logs or credentials."""
    raw=mapping(raw)
    if raw.get('version')!='victor-control-v1':return {}
    revision=raw.get('revision')
    device=raw.get('device_id')
    controls=mapping(raw.get('controls'))
    out={'version':'victor-control-v1',
         'revision':revision if type(revision) is int and 0<=revision<=2**53 else None,
         'device_id':device if isinstance(device,str) and re.fullmatch('[a-f0-9]{32}',device) else None,
         'controls':{key:controls[key] for key in CONTROL_KEYS if type(controls.get(key)) is bool},
         'observed_at':stamp(raw.get('observed_at')), 'valid':raw.get('valid') is True,
         'error':enum(raw.get('error'),{'CONTROLS_UNAVAILABLE','CONTROLS_INVALID'}),
         'components':{key:enum(value,COMPONENT_STATES) or 'UNKNOWN' for key,value in mapping(raw.get('components')).items() if key in COMPONENT_KEYS},
         'in_flight':[key for key in raw.get('in_flight',[]) if isinstance(key,str) and key in COMPONENT_KEYS] if isinstance(raw.get('in_flight'),list) else []}
    if 'effective_new_entries_enabled' in raw:
        out['effective_new_entries_enabled']=raw.get('effective_new_entries_enabled') is True
    if 'pause_reason' in raw:
        out['pause_reason']=enum(raw.get('pause_reason'),{'CONTROLS_UNAVAILABLE','CONTROLS_INVALID','QQQ_TRADING_OFF','VIC_OFF_NEW_ENTRIES_PAUSED'})
    return out


def sanitize_controller(raw):
    try:
        from control_transport import sanitize_status, ControlError
    except ImportError:
        return None
    try:
        return sanitize_status(raw)
    except (ControlError,ValueError,TypeError):
        return None


def sanitize_policy(raw):
    if not isinstance(raw,dict) or raw.get('version') not in POLICY_VERSIONS:return {}
    out=sanitize_direction(raw)
    out.update(version=raw['version'],valid_until=stamp(raw.get('valid_until')),
        confidence=enum(raw.get('confidence'),{'LOW','MODERATE','HIGH_CONSENSUS'}),
        regime=enum(raw.get('regime'),{'BULLISH_TREND','BEARISH_TREND','MIXED_OR_RANGE','UNKNOWN'}),
        holdings_status=enum(raw.get('holdings_status'),{'AVAILABLE','UNAVAILABLE'}),
        snapshot_id=raw.get('snapshot_id') if isinstance(raw.get('snapshot_id'),str) and re.fullmatch(r'[a-f0-9]{20}',raw['snapshot_id']) else None)
    out.update(macro_context=sanitize_macro(raw.get('macro_context')),data_contract=sanitize_data_contract(raw.get('data_contract')),
        feed_health=sanitize_feed_health(raw.get('feed_health')),qqq_data_status=enum(raw.get('qqq_data_status'),QQQ_QUALITY) or 'UNKNOWN')
    day=mapping(raw.get('daily_outlook'))
    out['daily_outlook']={'bias':enum(day.get('bias'),{'BULLISH','BEARISH','MIXED','UNKNOWN'}),
        'all_aligned':day.get('all_aligned') is True,'news_opposes':day.get('news_opposes') is True,
        'missing':[k for k in day.get('missing',[]) if isinstance(k,str) and k in {'qqq','mag7','breadth','semiconductors','volatility','treasury'}] if isinstance(day.get('missing'),list) else []}
    from local_research_plan import compact as compact_review
    out['local_research_plan']=compact_review(raw.get('local_research_plan'))
    return out


def sanitize_vic(raw):
    if not isinstance(raw,dict):return None
    permission=raw.get('permission')
    permission=permission if isinstance(permission,dict) else {}
    from local_research_plan import compact_receipt
    return {'heartbeat':stamp(raw.get('heartbeat')),
            'local_review_receipt':compact_receipt(raw.get('local_review_receipt')),
            'health':enum(raw.get('health'),HEALTH) or 'UNKNOWN',
            'current_bias':enum(raw.get('current_bias'),{'BULLISH','BEARISH','NEUTRAL','UNKNOWN'}) or 'UNKNOWN',
            'market_direction':sanitize_direction(raw.get('market_direction')),
            'vic_policy':sanitize_policy(raw.get('vic_policy')),
            'engine_status':sanitize_engine_status(raw.get('engine_status')),
            'permission':{'light':enum(permission.get('light'),{'GREEN','RED','YELLOW'}) or 'UNKNOWN',
                          'valid_until':stamp(permission.get('valid_until'))}}


def sanitize_snapshot(raw):
    if not isinstance(raw,dict) or raw.get('schema')!=1 or raw.get('paper') is not True:
        raise ValueError('Invalid paper report format')
    reports=raw.get('reports')
    if not isinstance(reports,dict): raise ValueError('Missing reports')
    from overnight_schema import telemetry
    vic=sanitize_vic(raw.get('vic'))
    engine=sanitize_engine_status(raw.get('engine_status') or raw.get('teams'))
    if vic and engine:vic['engine_status']=engine
    out={'schema':1,'paper':True,'observed_at':stamp(raw.get('observed_at')),
            'reports':{name:sanitize_report(reports.get(name)) for name in ('hero','bear')},
            'vic':vic, 'teams':sanitize_teams(raw.get('teams')),'engine_status':engine,
            'supervisor':sanitize_supervisor(raw.get('supervisor')),'overnight':telemetry(raw.get('overnight'))}
    out['beta']=None
    out['beta_error']=enum(raw.get('beta_error'),BETA_ERRORS)
    if raw.get('beta') is not None:
        try:
            from beta_panel.snapshot import validate
            out['beta']=validate(raw['beta'],enforce_limit=False)
            out['beta_error']=None
        except (ValueError,TypeError,OverflowError,RecursionError,ImportError):
            out['beta_error']='BETA_INVALID'
    out['control_status']=sanitize_controller(raw.get('control_status'))
    # Never drop only some positions/orders and imply a complete portfolio.
    # If Beta does not fit, preserve the entire QQQ report and say why Beta is
    # unavailable. This also makes sanitize_snapshot idempotent across RPCs.
    if len(json.dumps(out,ensure_ascii=False,allow_nan=False).encode('utf-8'))>SNAPSHOT_BUDGET and out['beta'] is not None:
        out['beta']=None
        out['beta_error']='BETA_TOO_LARGE'
    if len(json.dumps(out,ensure_ascii=False,allow_nan=False).encode('utf-8'))>SNAPSHOT_BUDGET:
        raise ValueError('QQQ and controller report exceeds telemetry size limit')
    return out


def signed(value):
    if isinstance(value,bool): return None
    try:
        n=float(value)
        return n if math.isfinite(n) and abs(n)<=1_000_000_000 else None
    except (ValueError,TypeError,OverflowError): return None


def sanitize_teams(raw):
    """Competition-only virtual capital and performance, never broker account values."""
    if isinstance(raw,dict): raw=raw.get('teams')
    if not isinstance(raw,list): return []
    output=[]
    from team_settings import NAMES as names, BUDGET, EXIT_LABELS
    for t in raw[:len(names)]:
        if not isinstance(t,dict) or t.get('team_id') not in names or t.get('paper') is not True:continue
        team={'team_id':t['team_id'],'label':names[t['team_id']],'paper':True,
              'heartbeat':stamp(t.get('heartbeat')),'health':enum(t.get('health'),HEALTH) or 'UNKNOWN',
              'day':t.get('day') if isinstance(t.get('day'),str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}',t['day']) else None,
              'starting_equity':numeric(t.get('starting_equity')) or BUDGET,
              'exit_policy':EXIT_LABELS[t['team_id']],'pending_entry':t.get('pending_entry') is True,'trades':[],'activities':[]}
        team['entry_enabled']=t.get('entry_enabled') if isinstance(t.get('entry_enabled'),bool) else None
        team['roster_version']=enum(t.get('roster_version'),{'paper10-2026-10-12-v1'})
        team['pending_orders']=bounded(t.get('pending_orders'),0,1000)
        for key in ('realized_pnl','unrealized_pnl','net_pnl','equity','entry_budget','completed_trades','wins'):
            team[key]=signed(t.get(key))
        team['market_direction']=sanitize_direction(t.get('market_direction'))
        team['vic_policy']=sanitize_policy(t.get('vic_policy'))
        team['entry_used']=t.get('entry_used') is True
        team['risk_latched']=t.get('risk_latched') is True
        team['daily_loss_allowance']=bounded(t.get('daily_loss_allowance'),0,5000)
        team['report_team']=numeric(t.get('report_team'))
        metrics=t.get('metrics') if isinstance(t.get('metrics'),dict) else {}
        team['metrics']={'bar_end':stamp(metrics.get('bar_end'))}
        for key in ('candle_minutes','price_close','ema_5_5m','ema_9_5m','momentum_relative_volume','rsi_14_5m','previous_rsi_14_5m','relative_volume','session_vwap','vwap_slope_atr','lower_bband','middle_bband','upper_bband','orb_high','orb_low','directional_efficiency','mean_range_atr','chop_detected'):
            team['metrics'][key]=signed(metrics.get(key))
        team['decisions']={}
        decisions=t.get('decisions') if isinstance(t.get('decisions'),dict) else {}
        def reason(value):
            return value if isinstance(value,str) and re.fullmatch(r'[A-Z][A-Z0-9_]{0,79}',value) else 'DATA_CHECK_FAILED'
        for owner in ('hero','bear'):
            d=decisions.get(owner)
            if not isinstance(d,dict):continue
            clean={'action':enum(d.get('action'),{'WAIT','BUY_CALL_SIGNAL','BUY_PUT_SIGNAL','HOLD','CLOSE_ALL','SCALE_OUT_50','DATA_UNAVAILABLE'}),
                   'reasons':[reason(r) for r in d.get('reasons',[])[:20]] if isinstance(d.get('reasons'),list) else []}
            if d.get('reason'):clean['reason']=reason(d['reason'])
            for key in ('stop_price','target_level','room_r'):clean[key]=signed(d.get(key))
            clean['team13_plan']=sanitize_plan(d.get('team13_plan'))
            clean['team13_plan_observation']=sanitize_plan(d.get('team13_plan_observation'))
            team['decisions'][owner]=clean
        for row in records(t.get('trades'))[-100:]:
            symbol=contract(row.get('symbol'))
            if not symbol:continue
            trade={'symbol':symbol,'owner':enum(row.get('owner'),{'HERO','BEAR'}),
                   'entry_at':stamp(row.get('entry_at')),'closed_at':stamp(row.get('closed_at')),
                   'quote_at':stamp(row.get('quote_at')),'exit_fills':[],
                   'setup':row.get('setup') if isinstance(row.get('setup'),str) and re.fullmatch(r'[A-Za-z0-9_ /.-]{1,100}',row['setup']) else None,
                   'exit_reason':row.get('exit_reason') if isinstance(row.get('exit_reason'),str) and re.fullmatch(r'[A-Z0-9_]{1,80}',row['exit_reason']) else None,
                   'market_policy_version':enum(row.get('market_policy_version'),{'active-context-v1','vic-day-hold-v1'})}
            trade['team13_plan']=sanitize_plan(row.get('team13_plan'))
            trade['strategy_provenance']=sanitize_provenance(row.get('strategy_provenance'))
            trade['signal_cluster']=sanitize_cluster(row.get('signal_cluster'))
            for key in ('quantity','remaining_qty','entry_price','exit_price'):trade[key]=numeric(row.get(key))
            for key in ('option_delta','realized_pnl','unrealized_pnl','total_pnl'):trade[key]=signed(row.get(key))
            for fill in records(row.get('exit_fills')):
                trade['exit_fills'].append({'at':stamp(fill.get('at')),'quantity':numeric(fill.get('quantity')),
                    'price':numeric(fill.get('price')),'purpose':enum(fill.get('purpose'),{'SCALE_OUT_50','CLOSE_ALL'})})
            entry=row.get('market_entry') or {}
            trade['market_entry']={k:signed(entry.get(k)) for k in ('score','coverage','quantity_without_context','quantity_with_context','fraction')}
            trade['market_entry']['bias']=enum(entry.get('bias'),{'BULLISH','BEARISH','NEUTRAL'})
            trade['market_entry']['at']=stamp(entry.get('at'))
            trade['market_entry']['ranked_at']=stamp(entry.get('ranked_at'))
            trade['market_entry']['reason']=enum(entry.get('reason'),{'VIC_ALIGNED','VIC_CONFLICT_REDUCED','VIC_NEUTRAL_REDUCED','VIC_INCOMPLETE_CHART_ONLY_REDUCED','TEAM7_FIXED_SINGLE_ALLOCATION','LEGACY_CONTEXT_POLICY'})
            trade['market_entry']['entry_policy_version']=enum(entry.get('entry_policy_version'),POLICY_VERSIONS|{'active-context-v1'})
            for key in ('entry_chart_bar_end','vic_qqq_bar_end'):trade['market_entry'][key]=stamp(entry.get(key))
            trade['market_entry']['stock_feed']=enum(entry.get('stock_feed'),STOCK_FEEDS)
            trade['market_entry']['option_feed']=enum(entry.get('option_feed'),OPTION_FEEDS)
            trade['market_entry']['macro_context']=sanitize_macro(entry.get('macro_context'))
            trade['market_entry']['data_contract']=sanitize_data_contract(entry.get('data_contract'))
            trade['market_entry']['feed_health']=sanitize_feed_health(entry.get('feed_health'))
            from local_research_plan import compact as compact_review
            trade['market_entry']['local_research_plan']=compact_review(entry.get('local_research_plan'))
            trade['market_entry']['local_strategy_priority']=bounded(entry.get('local_strategy_priority'),0,10)
            from overnight_schema import compact
            trade['market_entry']['overnight']=compact(entry.get('overnight'))
            team['trades'].append(trade)
        for a in records(t.get('activities'))[-30:]:
            symbol=contract(a.get('symbol'))
            if symbol and a.get('type') in {'ENTRY_FILLED','EXIT_FILLED'}:
                team['activities'].append({'symbol':symbol,'owner':enum(a.get('owner'),{'hero','bear'}),
                    'type':a['type'],'timestamp':stamp(a.get('timestamp')),'qty':numeric(a.get('qty')),
                    'price':numeric(a.get('price')),'realized_pnl':signed(a.get('realized_pnl'))})
        output.append(team)
    return output


class LinkError(Exception):
    def __init__(self,message,status=None):
        super().__init__(message)
        self.status=status


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): return None


def rpc(url, publishable_key, operation, token, payload=None):
    # Restrict destination; no query strings, userinfo, redirects or HTTP downgrades.
    if not re.fullmatch(r'https://[a-z0-9-]+\.supabase\.co',url or ''):
        raise LinkError('Set TELEMETRY_URL to the HTTPS Supabase project URL, without a trailing slash.')
    if not isinstance(publishable_key,str) or not publishable_key.startswith('sb_publishable_'):
        raise LinkError('Use the Supabase publishable key, never a secret/service-role key.')
    if not isinstance(token,str) or not re.fullmatch(r'[A-Za-z0-9_-]{43,128}',token):
        raise LinkError('Telemetry access token is missing or invalid.')
    if operation not in ('vt_read','vt_write'): raise LinkError('Invalid operation')
    body={'p_token':token}
    if operation=='vt_write': body['p_snapshot']=sanitize_snapshot(payload)
    encoded=json.dumps(body,ensure_ascii=False,allow_nan=False).encode('utf-8')
    if len(encoded)>MAX_BYTES: raise LinkError('Report exceeds size limit')
    req=request.Request(url+'/rest/v1/rpc/'+operation,data=encoded,method='POST',
        headers={'apikey':publishable_key,'Content-Type':'application/json','User-Agent':'VictorTelemetry/1'})
    try:
        import certifi
        ctx=ssl.create_default_context(cafile=certifi.where())
        opener=request.build_opener(NoRedirect(),request.HTTPSHandler(context=ctx))
        with opener.open(req,timeout=8) as response:
            data=response.read(MAX_BYTES+1)
        if len(data)>MAX_BYTES: raise LinkError('Response exceeds size limit')
        return json.loads(data)
    except error.HTTPError as exc:
        # Never expose response bodies, headers, credentials or request arguments.
        raise LinkError(f'Telemetry service returned HTTP {exc.code}. Check setup and access token.',status=exc.code) from None
    except (error.URLError,TimeoutError,OSError,ValueError):
        raise LinkError('Telemetry service unavailable or returned an invalid response.') from None


def fetch_remote(url,key,reader_token):
    envelope=rpc(url,key,'vt_read',reader_token)
    if envelope is None: return None
    if not isinstance(envelope,dict): raise LinkError('Invalid report envelope')
    try:
        return {'received_at':stamp(envelope.get('received_at')),
                'snapshot':sanitize_snapshot(envelope.get('snapshot'))}
    except ValueError: raise LinkError('Invalid paper telemetry report') from None


def sanitize_supervisor(raw):
    if not isinstance(raw,dict):return None
    # Only research text and date, never balances, secrets or raw state.
    out={'date':str(raw.get('date',''))[:10],'generated_at':stamp(raw.get('generated_at')),
         'summary':str(raw.get('summary',''))[:1000],'mode':str(raw.get('mode',''))[:40],
         'ai_status':str(raw.get('ai',{}).get('status','NOT_REQUESTED'))[:40],
         'ai_text':str(raw.get('ai',{}).get('text',''))[:8000]}
    out['recommendations']=[{k:str(r.get(k,''))[:1200] for k in ('team','trade_id','observation','recommendation')}
        for r in raw.get('recommendations',[])[:100] if isinstance(r,dict)]
    return out

