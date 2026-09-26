"""Read-only dashboard / write-only Mac transport. No broker API dependencies."""
from datetime import datetime, timezone
import json
import math
import re
import ssl
from urllib import request, error

MAX_BYTES = 1_000_000
HEALTH = {'STARTING','MARKET_CLOSED','ORDER_PENDING','MANAGING_POSITION','ENTRY_PAUSED','SCANNING','ERROR','STOPPED','GREEN','RED','YELLOW','UNKNOWN'}
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


def sanitize_vic(raw):
    if not isinstance(raw,dict): return None
    permission=raw.get('permission')
    permission=permission if isinstance(permission,dict) else {}
    return {'heartbeat':stamp(raw.get('heartbeat')),
            'health':enum(raw.get('health'),HEALTH) or 'UNKNOWN',
            'current_bias':enum(raw.get('current_bias'),{'BULLISH','BEARISH','NEUTRAL','UNKNOWN'}) or 'UNKNOWN',
            'permission':{'light':enum(permission.get('light'),{'GREEN','RED','YELLOW'}) or 'UNKNOWN',
                          'valid_until':stamp(permission.get('valid_until'))}}


def sanitize_snapshot(raw):
    if not isinstance(raw,dict) or raw.get('schema')!=1 or raw.get('paper') is not True:
        raise ValueError('Invalid paper report format')
    reports=raw.get('reports')
    if not isinstance(reports,dict): raise ValueError('Missing reports')
    return {'schema':1,'paper':True,'observed_at':stamp(raw.get('observed_at')),
            'reports':{name:sanitize_report(reports.get(name)) for name in ('hero','bear')},
            'vic':sanitize_vic(raw.get('vic'))}


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
