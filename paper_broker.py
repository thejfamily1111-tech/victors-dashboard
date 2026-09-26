"""Alpaca PAPER REST adapter. The trading host is fixed; live orders unsupported."""
import json, os, ssl, math
from urllib.request import Request, build_opener, HTTPSHandler, HTTPRedirectHandler
from urllib.parse import urlencode, quote
from urllib.error import HTTPError
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_CEILING
from vic import ET, stamp

PAPER='https://paper-api.alpaca.markets'
DATA='https://data.alpaca.markets'

class BrokerError(RuntimeError):
    def __init__(self,status=0):
        self.status=status
        super().__init__(f'Alpaca request failed (HTTP {status})' if status else 'Alpaca network request failed')

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def num(x):
    v=float(x)
    if isinstance(x,bool) or not math.isfinite(v):raise ValueError('Invalid number')
    return v


def whole(x):
    v=num(x)
    if v<0 or v!=int(v):raise ValueError('Invalid contract quantity')
    return int(v)


def valid_quote(q,now,entry=False):
    if not isinstance(q,dict):raise ValueError('Missing option quote')
    bid,ask=num(q['bp']),num(q['ap'])
    if not 0<=(now-stamp(q['t'])).total_seconds()<=30:raise ValueError('Option quote older than 30 seconds')
    if bid<0 or ask<=0 or bid>ask:raise ValueError('Invalid or crossed option quote')
    if entry and (bid<=0 or num(q.get('bs',0))<1 or num(q.get('as',0))<1 or (ask-bid)/((ask+bid)/2)>.15):
        raise ValueError('Option quote too wide or lacks displayed size')
    return bid,ask


class PaperBroker:
    def __init__(self):
        import certifi
        self.key=os.getenv('APCA_API_KEY_ID') or os.getenv('ALPACA_API_KEY') or os.getenv('ALPACA_KEY')
        self.secret=os.getenv('APCA_API_SECRET_KEY') or os.getenv('ALPACA_SECRET_KEY') or os.getenv('ALPACA_SECRET')
        if not self.key or not self.secret:raise ValueError('Missing Alpaca paper credentials in .env')
        self.stock_feed=os.getenv('PAPER_STOCK_FEED','iex')
        self.option_feed=os.getenv('PAPER_OPTION_FEED','indicative')
        if self.stock_feed not in {'iex','sip'} or self.option_feed not in {'indicative','opra'}:raise ValueError('Invalid feed setting')
        context=ssl.create_default_context();context.load_verify_locations(certifi.where())
        self.http=build_opener(HTTPSHandler(context=context),NoRedirect())

    def request(self,method,path,params=None,body=None,data=False):
        if data and method!='GET':raise ValueError('Read-only data API')
        url=(DATA if data else PAPER)+path
        if params:url+='?'+urlencode({k:v for k,v in params.items() if v is not None})
        req=Request(url,data=json.dumps(body).encode() if body is not None else None,method=method,
                    headers={'APCA-API-KEY-ID':self.key,'APCA-API-SECRET-KEY':self.secret,'Content-Type':'application/json'})
        try:
            with self.http.open(req,timeout=8) as r:
                raw=r.read();return json.loads(raw) if raw else None
        except HTTPError as exc:raise BrokerError(exc.code) from None
        except (OSError,ValueError):raise BrokerError() from None

    def account(self):return self.request('GET','/v2/account')
    def clock(self):return self.request('GET','/v2/clock')
    def positions(self):return self.request('GET','/v2/positions')
    def open_orders(self):
        rows=self.request('GET','/v2/orders',{'status':'open','limit':500})
        if len(rows)>=500:raise ValueError('Open order response may be truncated')
        return rows
    def calendar(self,start,end):return self.request('GET','/v2/calendar',{'start':str(start),'end':str(end)})
    def get_order(self,cid):return self.request('GET','/v2/orders:by_client_order_id',{'client_order_id':cid})
    def cancel(self,oid):return self.request('DELETE','/v2/orders/'+quote(oid,safe=''))
    def submit(self,payload):
        if payload.get('position_intent') not in {'buy_to_open','sell_to_close'}:raise ValueError('Unsupported intent')
        if not str(payload.get('symbol','')).startswith('QQQ'):raise ValueError('QQQ only')
        return self.request('POST','/v2/orders',body=payload)
    def quotes(self,symbols):
        return self.request('GET','/v1beta1/options/quotes/latest',{'symbols':','.join(symbols),'feed':self.option_feed},data=True)['quotes']
    def bars(self,symbols,start,end):
        result={s:[] for s in symbols};token=None;seen=set()
        for _ in range(100):
            r=self.request('GET','/v2/stocks/bars',{'symbols':','.join(symbols),'timeframe':'5Min','start':start.isoformat(),
                 'end':end.isoformat(),'feed':self.stock_feed,'adjustment':'raw','sort':'asc','limit':10000,'page_token':token},data=True)
            for symbol,rows in r.get('bars',{}).items():result[symbol].extend(rows)
            token=r.get('next_page_token')
            if not token:return result
            if token in seen:raise ValueError('Repeated bar page token')
            seen.add(token)
        raise ValueError('Bar pagination incomplete')

    def choose_contract(self,kind,spot,now,max_cost,qty):
        params={'underlying_symbols':'QQQ','status':'active','type':kind,'expiration_date_gte':str(now.date()+timedelta(days=1)),
                'expiration_date_lte':str(now.date()+timedelta(days=2)),'strike_price_gte':spot*.99,'strike_price_lte':spot*1.01,'limit':1000}
        rows=[];token=None;seen=set()
        for _ in range(10):
            r=self.request('GET','/v2/options/contracts',{**params,'page_token':token});rows.extend(r.get('option_contracts',[]))
            token=r.get('next_page_token')
            if not token:break
            if token in seen:raise ValueError('Repeated contract page token')
            seen.add(token)
        else:raise ValueError('Contract pagination incomplete')
        eligible=[]
        for c in rows:
            if c.get('underlying_symbol')!='QQQ' or c.get('type')!=kind or c.get('tradable') is not True:continue
            if c.get('status')!='active' or num(c.get('size',0))!=100:continue
            # A standard OCC root excludes adjusted deliverables such as QQQ1.
            import re
            if not re.fullmatch(r'QQQ\d{6}[CP]\d{8}',c['symbol']):continue
            dte=(datetime.fromisoformat(c['expiration_date']).date()-now.date()).days
            if not 1<=dte<=2:continue
            eligible.append(c)
        # ATM selection, not a delta filter. No invented/missing Greeks.
        eligible.sort(key=lambda c:(abs(num(c['strike_price'])-spot),c['expiration_date']))
        if not eligible:raise ValueError('No eligible standard QQQ 1–2 DTE contracts')
        # Check nearest strikes; never choose a distant strike solely to fit budget.
        nearest=abs(num(eligible[0]['strike_price'])-spot)
        eligible=[c for c in eligible if abs(num(c['strike_price'])-spot)<=nearest+1e-8]
        quotes=self.quotes([c['symbol'] for c in eligible])
        for c in eligible:
            try:
                q=quotes[c['symbol']];_,ask=valid_quote(q,datetime.now(ET),entry=True)
                # QQQ is penny-eligible; require provider confirmation for this adapter.
                if c.get('ppind') is not True:continue
                limit=Decimal(str(ask)).quantize(Decimal('.01'),rounding=ROUND_CEILING)
                if float(limit)*100*qty>max_cost:continue
                return c['symbol'],str(limit),q
            except (KeyError,ValueError):continue
        raise ValueError('ATM contracts exceed premium cap, lack penny eligibility or valid liquid quotes')
