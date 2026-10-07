"""Read-only dashboard / write-only Mac transport. No broker API dependencies."""
from datetime import datetime, timezone
import json
import math
import re
import ssl
from urllib import request, error

MAX_BYTES = 1_000_000
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
    allowed={'qqq','mag7','volatility','treasury','semiconductors','news_event'}
    out={'mode':enum(raw.get('mode'),{'ACTIVE'}) or 'UNKNOWN',
         'at':stamp(raw.get('at')),'bar_end':stamp(raw.get('bar_end')),
         'bias':enum(raw.get('bias'),{'BULLISH','BEARISH','NEUTRAL'}) or 'UNKNOWN',
         'score':signed(raw.get('score')),'coverage':numeric(raw.get('coverage')),
         'missing':[x for x in raw.get('missing',[]) if x in allowed],'factors':{}}
    for k,f in (raw.get('factors') or {}).items():
        if k not in allowed or not isinstance(f,dict):continue
        out['factors'][k]={'value':signed(f.get('value')),'at':stamp(f.get('at')),
                           'source_code':enum(f.get('source_code'),{'QQQ','MAG7','VXN','VIX','TNX','IEF_PROXY','SMH','NEWS_EVENT'}),
                           'change_pct_15m':signed(f.get('change_pct_15m'))}
    breadth=raw.get('mag7') or {}
    out['mag7']={k:numeric(breadth.get(k)) for k in ('available','green','red','flat')}
    out['mag7']['confirmed']=breadth.get('confirmed') is True
    return out


def sanitize_vic(raw):
    if not isinstance(raw,dict):return None
    permission=raw.get('permission')
    permission=permission if isinstance(permission,dict) else {}
    return {'heartbeat':stamp(raw.get('heartbeat')),
            'health':enum(raw.get('health'),HEALTH) or 'UNKNOWN',
            'current_bias':enum(raw.get('current_bias'),{'BULLISH','BEARISH','NEUTRAL','UNKNOWN'}) or 'UNKNOWN',
            'market_direction':sanitize_direction(raw.get('market_direction')),
            'permission':{'light':enum(permission.get('light'),{'GREEN','RED','YELLOW'}) or 'UNKNOWN',
                          'valid_until':stamp(permission.get('valid_until'))}}


def sanitize_snapshot(raw):
    if not isinstance(raw,dict) or raw.get('schema')!=1 or raw.get('paper') is not True:
        raise ValueError('Invalid paper report format')
    reports=raw.get('reports')
    if not isinstance(reports,dict): raise ValueError('Missing reports')
    return {'schema':1,'paper':True,'observed_at':stamp(raw.get('observed_at')),
            'reports':{name:sanitize_report(reports.get(name)) for name in ('hero','bear')},
            'vic':sanitize_vic(raw.get('vic')), 'teams':sanitize_teams(raw.get('teams')),
            'supervisor':sanitize_supervisor(raw.get('supervisor'))}


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
        for key in ('realized_pnl','unrealized_pnl','net_pnl','equity','entry_budget','completed_trades','wins'):
            team[key]=signed(t.get(key))
        team['market_direction']=sanitize_direction(t.get('market_direction'))
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
            team['decisions'][owner]=clean
        for row in records(t.get('trades'))[-100:]:
            symbol=contract(row.get('symbol'))
            if not symbol:continue
            trade={'symbol':symbol,'owner':enum(row.get('owner'),{'HERO','BEAR'}),
                   'entry_at':stamp(row.get('entry_at')),'closed_at':stamp(row.get('closed_at')),
                   'quote_at':stamp(row.get('quote_at')),'exit_fills':[],
                   'setup':row.get('setup') if isinstance(row.get('setup'),str) and re.fullmatch(r'[A-Za-z0-9_ /.-]{1,100}',row['setup']) else None,
                   'exit_reason':row.get('exit_reason') if isinstance(row.get('exit_reason'),str) and re.fullmatch(r'[A-Z0-9_]{1,80}',row['exit_reason']) else None,
                   'market_policy_version':enum(row.get('market_policy_version'),{'active-context-v1'})}
            for key in ('quantity','remaining_qty','entry_price','exit_price'):trade[key]=numeric(row.get(key))
            for key in ('option_delta','realized_pnl','unrealized_pnl','total_pnl'):trade[key]=signed(row.get(key))
            for fill in records(row.get('exit_fills')):
                trade['exit_fills'].append({'at':stamp(fill.get('at')),'quantity':numeric(fill.get('quantity')),
                    'price':numeric(fill.get('price')),'purpose':enum(fill.get('purpose'),{'SCALE_OUT_50','CLOSE_ALL'})})
            entry=row.get('market_entry') or {}
            trade['market_entry']={k:signed(entry.get(k)) for k in ('score','coverage','quantity_without_context','quantity_with_context','fraction')}
            trade['market_entry']['bias']=enum(entry.get('bias'),{'BULLISH','BEARISH','NEUTRAL'})
            trade['market_entry']['at']=stamp(entry.get('at'))
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
    encoded=json.dumps(body,allow_nan=False).encode()
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

