"""VIC QQQ macro monitor. Publishes entry permission; NEVER submits orders.
Run: python3 vic.py (continuous) or python3 vic.py --once.
The dashboard also evaluates VIC while open. All times are America/New_York.
Calendar scope: Fed events, BLS releases, BEA releases; not every global event.
Mag-7 breadth is advisory only; no count can grant or veto permission.
News: reported material events may pause for 30m; WATCH never pauses.
Routine headlines are hidden. Heuristics do not verify truth or actual impact.
Policy defaults (unvalidated): VIX <35, 15m post-release pause, 2 completed
5m bars confirming EMA trend after release. Override VIC_MAX_VIX and
VIC_POST_NEWS_MINUTES in the existing .env. Missing required inputs => RED.
Permission expires after 45s. RED applies to new entries, never position exits.
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
import ssl, socket
from email.utils import parsedate_to_datetime
from concurrent.futures import ThreadPoolExecutor
import json, os, re, html, time, tempfile, hashlib
import xml.etree.ElementTree as XML

VIC_BUILD='2026-09-26-material-news-mag7'
import re
MAG7=('MSFT','AAPL','NVDA','AMZN','GOOGL','META','TSLA')
TRUSTED={'Yahoo Finance','CNBC','BBC Business'}


def classify_news(title):
    t=re.sub(r'\s+',' ',str(title).casefold()).strip()
    def result(level,category,reason):
        return {'level':level,'category':category,'reason':reason,'pause_candidate':level=='HIGH'}
    uncertainty_text=re.sub(r'\b(than expected|above expectations|below expectations|versus expectations)\b','',t)
    uncertain=bool(re.search(r'\b(could|might|may|rumou?r|reportedly|unconfirmed|denies|denied|not|no|if|would|expects?|expected|forecasts?|predicts?|prediction|preview|outlook|bets?|odds|what to watch|opinion|should|why|how to)\b|\?',uncertainty_text))
    # Require BOTH a material subject and a concrete event, not sentiment words.
    patterns=[
      ('MONETARY_POLICY',r'\b(federal reserve|fed|fomc|ecb|bank of japan)\b',r'\b(cuts?|raises?|hikes?|holds?|announces?|announced|approves?|launches?)\b.{0,55}\b(rates?|stimulus|bond.buying|emergency|liquidity)\b|\bemergency rate (cut|hike)\b'),
      ('US_ECONOMIC_RELEASE',r'\b(us|u\.s\.|american)\b|\b(bls|bea)\b',r'\b(cpi|pce|inflation|payrolls?|jobs report|unemployment|gdp)\b.{0,65}\b(rose|rises|fell|falls|jumped|jumps|surged|surges|slowed|slows|accelerated|accelerates|added|adds|reported|reports|released|release|beats|misses)\b|\b(adds|added|loses|lost)\b.{0,30}\bjobs\b'),
      ('SYSTEMIC_DISRUPTION',r'\b(market.wide|nyse|nasdaq|us banking|u\.s\. banking|fdic|treasury|us government|u\.s\. government)\b',r'\b(halt|halts|halted|outage|default|defaults|fails|failure|seizes|seized|emergency|shutdown)\b'),
      ('TRADE_POLICY',r'\b(us|u\.s\.|china|white house|president|treasury|eu)\b',r'\b(imposes?|imposed|raises?|raised|removes?|removed|suspends?|suspended|cuts?|cut)\b.{0,35}\btariffs?\b|\btariffs?\b.{0,35}\b(imposed|raised|removed|suspended|cut)\b|\btrade (deal|agreement)\b.{0,25}\b(signed|reached)\b'),
      ('GEOPOLITICAL_SHOCK',r'\b(us|u\.s\.|china|taiwan|iran|israel|russia|nato|hormuz)\b',r'\b(launches?|launched)\b.{0,30}\b(strikes?|attack|invasion)\b|\b(invades|invasion|war breaks out|ceasefire signed|ceasefire reached|strait of hormuz closed)\b')]
    for category,subject,event in patterns:
        if re.search(subject,t) and re.search(event,t):
            if uncertain:return result('WATCH',category,'Speculative, denied or conditional wording; no automatic pause')
            return result('HIGH',category,'Concrete material-event wording; reported headline, not independently verified')
    company=r'\b(apple|microsoft|nvidia|amazon|alphabet|google|meta|tesla|aapl|msft|nvda|amzn|googl|tsla)\b'
    if re.search(company,t) and re.search(r'\b(earnings|guidance|revenue|export ban|antitrust|outage|recall)\b',t):
        return result('WATCH','MEGACAP_EVENT','Potential QQQ context; single-company headline does not veto entries')
    if re.search(r'\b(fed|fomc|cpi|pce|payrolls|tariffs?|recession|war|ceasefire|bank failure)\b',t):
        return result('WATCH','MACRO_CONTEXT','Context or unclear event; no automatic pause')
    return result('IGNORE','ROUTINE','Routine recap, recommendation or no configured material event')


def active_alerts(items,now,stamp):
    """Original publication time controls expiry; polling never resets the timer.
    Exact normalized duplicates use earliest publication across publishers.
    """
    grouped={}
    for item in items:
        if item.get('source') not in TRUSTED:continue
        info=classify_news(item.get('title',''))
        if not info['pause_candidate']:continue
        try:published=stamp(item['published_at'])
        except (KeyError,ValueError,TypeError):continue
        key=re.sub(r'[^a-z0-9]+',' ',str(item.get('title','')).casefold()).strip()
        if key not in grouped or published<grouped[key][0]:grouped[key]=(published,item,info)
    alerts=[]
    for published,item,info in grouped.values():
        if 0<=(now-published).total_seconds()<1800:
            alerts.append({'title':item['title'],'source':item['source'],'category':info['category'],
                           'published_at':published.isoformat(),'pause_until':(published+timedelta(minutes=30)).isoformat(),'reason':info['reason']})
    return alerts


def breadth(statuses,bar_end,now,stamp):
    result={'bias':'UNKNOWN','preferred_engine':None,'green':0,'red':0,'flat':0,'available':0,'bar_end':bar_end,'mode':'CONTEXT_ONLY','statuses':{},'reason':'Missing or stale aligned Mag-7 data'}
    try:
        end=stamp(bar_end)
        if end.date()!=now.date() or not 0<=(now-end).total_seconds()<=180:return result
        clean={s:statuses[s] for s in MAG7 if statuses.get(s) in {'GREEN','RED','FLAT'}}
        result.update(statuses=clean,available=len(clean))
        for label in ('green','red','flat'):result[label]=sum(x==label.upper() for x in clean.values())
        # Partial coverage is shown but never interpreted as a complete seven-stock vote.
        if len(clean)!=7:return result
        bias='BULLISH' if result['green']>=4 else 'BEARISH' if result['red']>=4 else 'NEUTRAL'
        result.update(bias=bias,preferred_engine='HERO' if bias=='BULLISH' else 'BEAR' if bias=='BEARISH' else None,reason='Completed 5m close vs previous regular-session close; informational, never an entry veto')
    except (ValueError,TypeError,KeyError):pass
    return result

BASE=Path(__file__).resolve().parent
ET=ZoneInfo('America/New_York')
CALENDARS={
 'BLS':'https://www.bls.gov/schedule/news_release/bls.ics',
 'BEA':'https://www.bea.gov/news/schedule/ics/online-calendar-subscription.ics',
 'Fed':'https://www.federalreserve.gov/json/calendar.json'}
CACHE={}


def stamp(value):
    d=value if isinstance(value,datetime) else datetime.fromisoformat(str(value).replace('Z','+00:00'))
    if d.tzinfo is None:raise ValueError('Timezone required')
    return d.astimezone(ET)


def finite(value):
    import math
    if isinstance(value,bool):raise ValueError('Boolean is not numeric')
    v=float(value)
    if not math.isfinite(v):raise ValueError('Non-finite number')
    return v


def clean(value):
    return re.sub(r'\s+',' ',re.sub('<[^>]*>',' ',html.unescape(str(value or '')))).strip()


def request_text(url,headers=None):
    # URLs are fixed provider endpoints, never supplied by headlines or calendars.
    req=Request(url,headers={'User-Agent':'Mozilla/5.0',**(headers or {})})
    # Retain system/custom trust roots and add certifi for python.org macOS installs.
    import certifi
    context=ssl.create_default_context()
    context.load_verify_locations(cafile=certifi.where())
    with urlopen(req,timeout=12,context=context) as response:
        return response.read(5_000_001).decode('utf-8-sig')


def connection_error(exc):
    """Useful diagnostics without exposing request headers, credentials or local paths."""
    if isinstance(exc,HTTPError):
        return f'HTTP {exc.code}: provider rejected the request or is temporarily unavailable'
    reason=exc.reason if isinstance(exc,URLError) else exc
    if isinstance(reason,ssl.SSLCertVerificationError):
        return 'HTTPS certificate verification failed; update certifi in the Python environment running the dashboard and check any network proxy certificate'
    if isinstance(reason,socket.gaierror):
        return 'DNS lookup failed; check the internet connection, DNS settings or VPN'
    if isinstance(reason,(TimeoutError,socket.timeout)):
        return 'Connection timed out; check the connection and try Refresh market data'
    if isinstance(reason,ConnectionRefusedError):
        return 'Connection refused; check the firewall, VPN or proxy'
    if isinstance(reason,ssl.SSLError):
        return 'HTTPS handshake failed; check network TLS/proxy settings'
    if isinstance(exc,ModuleNotFoundError) and exc.name=='certifi':
        return 'Certificate bundle missing; run python3 -m pip install --upgrade certifi'
    if isinstance(exc,URLError):
        return f'Network connection failed ({type(reason).__name__}); check the connection, firewall or proxy'
    return f'Feed could not be read ({type(exc).__name__})'


def cached(key,seconds,fn):
    old=CACHE.get(key)
    if old and 0<=time.monotonic()-old[0]<seconds:return old[1]
    result=fn()  # A failed refresh never silently reuses stale success.
    CACHE[key]=(time.monotonic(),result)
    return result


def topic(title):
    t=title.lower()
    for key,pattern in [('conference',r'fomc press conference'),('fomc',r'fomc meeting|fomc statement'),
                        ('cpi',r'consumer price index'),('ppi',r'producer price index'),
                        ('jobs',r'employment situation'),('jolts',r'job openings'),
                        ('eci',r'employment cost index'),('pce',r'personal income and outlays'),
                        ('gdp',r'gross domestic product|\bgdp\b')]:
        if re.search(pattern,t):return key
    return None


def event(title,day,when,source,uid,url):
    return {'id':source+':'+str(uid),'title':clean(title),'date':str(day),
            'scheduled_at':when.isoformat() if when else None,'source':source,'url':url,
            'topic':topic(title),'impact':'HIGH' if topic(title) else 'OTHER',
            'release_confirmed_at':None,'release_evidence':None}


def parse_ics(text,source,url):
    if 'BEGIN:VCALENDAR' not in text:raise ValueError('Invalid calendar response')
    text=re.sub(r'\r?\n[ \t]','',text)
    output=[]
    for block in text.split('BEGIN:VEVENT')[1:]:
        props={}
        for line in block.split('END:VEVENT')[0].splitlines():
            if ':' in line:
                key,val=line.split(':',1);props[key.split(';')[0]]=(key,val)
        if props.get('STATUS',('', ''))[1]=='CANCELLED':continue
        key,raw=props.get('DTSTART',('',''))
        title=props.get('SUMMARY',('', ''))[1].replace('\\,',',').replace('\\n',' ').replace('\\;', ';')
        if not title or not raw:raise ValueError('Calendar event missing title/time')
        if 'RRULE' in props:raise ValueError('Recurring calendar unsupported; cannot assume clear')
        if len(raw)==8:
            day=datetime.strptime(raw,'%Y%m%d').date();when=None
        else:
            dt=datetime.strptime(raw.rstrip('Z'),'%Y%m%dT%H%M%S')
            tz=timezone.utc if raw.endswith('Z') else ET
            match=re.search(r'TZID=([^;:]+)',key)
            if match and match[1] not in {'US-Eastern','America/New_York'}:tz=ZoneInfo(match[1])
            when=dt.replace(tzinfo=tz).astimezone(ET);day=when.date()
        uid=props.get('UID',('',title+raw))[1]
        output.append(event(title,day,when,source,uid,url))
    if not output:raise ValueError('Empty calendar')
    return output


def parse_fed(text):
    output=[]
    for row in json.loads(text)['events']:
        if not row.get('month'):continue  # Feed includes a trailing empty object.
        title=clean(row.get('title'))
        for day in str(row.get('days','')).split(','):
            day=day.strip()
            if not day.isdigit():raise ValueError('Unsupported Fed date')
            date=datetime.strptime(row['month']+'-'+day,'%Y-%m-%d').date()
            raw=clean(row.get('time')).lower().replace('.','')
            match=re.fullmatch(r'(\d{1,2}):(\d{2})\s*([ap]m)',raw)
            when=None
            if match:
                hour=int(match[1])%12+(12 if match[3]=='pm' else 0)
                when=datetime.combine(date,datetime.min.time(),ET).replace(hour=hour,minute=int(match[2]))
            output.append(event(title,date,when,'Fed',f'{date}:{title}:{raw}',
                                'https://www.federalreserve.gov/newsevents/calendar.htm'))
    if not output:raise ValueError('Empty Fed calendar')
    return output


def load_bls_snapshot(now=None):
    """A dated, hash-bound user import; reading/copying never renews its age."""
    now=stamp(now or datetime.now(ET))
    raw=(BASE/'bls.ics').read_bytes()
    meta=json.loads((BASE/'bls_snapshot.json').read_text())
    if len(raw)>5_000_000 or hashlib.sha256(raw).hexdigest()!=meta['sha256']:
        raise ValueError('BLS snapshot changed; import a freshly downloaded calendar')
    imported=stamp(meta['imported_at']);expires=imported+timedelta(days=7)
    rows=parse_ics(raw.decode('utf-8-sig'),'BLS',CALENDARS['BLS'])
    error=None
    if not imported<=now<expires:error='BLS saved calendar expired or import date is invalid; download and import a fresh bls.ics'
    elif not min(e['date'] for e in rows)<=str(now.date())<=max(e['date'] for e in rows):
        error='BLS saved calendar does not cover today; download and import a fresh bls.ics'
    return {'events':rows,'checked_at':now.isoformat(),'error':error,
            'mode':'LOCAL SNAPSHOT','imported_at':imported.isoformat(),
            'expires_at':expires.isoformat(),
            'warning':'Using a saved BLS calendar; schedule changes after import are not reflected.'}


def fetch_calendar(source):
    url=CALENDARS[source]
    def work():
        try:
            raw=request_text(url)
            rows=parse_fed(raw) if source=='Fed' else parse_ics(raw,source,url)
            return {'events':rows,'checked_at':datetime.now(ET).isoformat(),'error':None,'mode':'ONLINE'}
        except Exception as exc:
            # Cache failed online attempts briefly; still re-read local data on every call.
            return {'events':[],'checked_at':None,'error':f'{source} calendar unavailable: {connection_error(exc)}'}
    old=CACHE.get('calendar:'+source)
    ttl=60 if old and old[1].get('error') else 900
    bundle=cached('calendar:'+source,ttl,work)
    if source!='BLS' or not bundle.get('error'):return bundle
    try:
        snapshot=load_bls_snapshot()
        snapshot['online_error']=bundle['error']
        return snapshot
    except Exception as exc:
        return {**bundle,'error':bundle['error']+'; saved calendar missing or invalid. Import a fresh bls.ics with import_bls_calendar.py.'}


def headline_signal(title):
    """Compatibility label: event relevance, never a price-direction forecast."""
    return classify_news(title)['level']


def fetch_news(symbol=None):
    """Market-wide RSS feeds; symbol retained only for compatibility and ignored."""
    feeds={'Yahoo Finance':'https://finance.yahoo.com/news/rssindex',
           'CNBC':'https://www.cnbc.com/id/100003114/device/rss/rss.html',
           'BBC Business':'https://feeds.bbci.co.uk/news/business/rss.xml'}
    def one(pair):
        source,url=pair
        try:
            rows=rss_items(url)
            if not rows:raise ValueError('Empty RSS feed')
            for row in rows:row.update(source=source,signal=headline_signal(row['title']),triage=classify_news(row['title']))
            return source,rows,None
        except Exception as exc:return source,[],source+': '+connection_error(exc)
    def work():
        now=datetime.now(ET);items=[];sources={};seen=set()
        with ThreadPoolExecutor(max_workers=2) as pool:
            for source,rows,error in pool.map(one,feeds.items()):
                rows=[r for r in rows if 0<=(now-stamp(r['published_at'])).total_seconds()<=7*24*3600]
                recent=any((now-stamp(r['published_at'])).total_seconds()<=72*3600 for r in rows)
                if not recent and not error:error=source+': no headlines within 72 hours; older articles shown for reference'
                for r in rows:r['stale']=(now-stamp(r['published_at'])).total_seconds()>72*3600
                sources[source]={'error':error,'count':len(rows),'checked_at':now.isoformat()}
                for row in rows:
                    key=(row['title'].casefold(),row['url'])
                    if key not in seen:items.append(row);seen.add(key)
        items.sort(key=lambda n:stamp(n['published_at']),reverse=True)
        return {'items':[n for n in items if n['triage']['level']!='IGNORE'][:100],'ignored_count':sum(n['triage']['level']=='IGNORE' for n in items),'checked_at':now.isoformat(),
                'error':None if any(not n['stale'] for n in items) else 'No recent market headlines available; any articles below are historical.',
                'warnings':[v['error'] for v in sources.values() if v['error']],
                'sources':sources,'scope':'Market-wide Yahoo Finance, CNBC and BBC Business RSS; limited coverage, not exhaustive.'}
    return cached('market_news',60,work)


def rss_items(url):
    root=XML.fromstring(request_text(url));rows=[]
    for item in root.findall('.//item'):
        try:
            date_text=item.findtext('pubDate')
            try:published=parsedate_to_datetime(date_text)
            except (ValueError,TypeError):published=stamp(date_text)
            if published.tzinfo is None:continue
            published=published.astimezone(ET)
            rows.append({'title':clean(item.findtext('title')),'published_at':published.isoformat(),'url':item.findtext('link')})
        except (TypeError,ValueError):continue
    return rows


def release_evidence(e,now):
    """Match official publication topic AND the scheduled ET date; a timer is not evidence."""
    if not e['scheduled_at'] or stamp(e['scheduled_at'])>now:return None
    key=e['topic']; scheduled=stamp(e['scheduled_at'])
    if key=='conference':return None  # Requires explicit user verification of completion.
    if e['source']=='BLS':
        code={'cpi':'cpi','ppi':'ppi','jobs':'empsit','jolts':'jolts','eci':'eci'}.get(key)
        if not code:return None
        url=f'https://www.bls.gov/news.release/{code}.nr0.htm'
        raw=cached('release:'+code,60,lambda:request_text(url))
        # Only the release header; later dates in the page may describe next month's schedule.
        header=clean(raw).split('embargoed until',1)
        if len(header)!=2:return None
        match=re.search(r'(\w+ \d{1,2}, \d{4})',header[1][:180])
        if match and datetime.strptime(match[1],'%B %d, %Y').date()==scheduled.date():
            first=CACHE.setdefault('first_release:'+e['id'],now.isoformat())
            return {'at':first,'url':url}
    else:
        url='https://www.federalreserve.gov/feeds/press_monetary.xml' if e['source']=='Fed' else 'https://apps.bea.gov/rss/rss.xml'
        rows=cached('release:'+e['source'],60,lambda:rss_items(url))
        for row in rows:
            when=stamp(row['published_at'])
            if scheduled<=when<=now and when.date()==scheduled.date() and topic(row['title'])==key:
                return {'at':when.isoformat(),'url':row['url']}
    return None


def collect_context(now=None):
    now=stamp(now or datetime.now(ET))
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures={s:pool.submit(fetch_calendar,s) for s in CALENDARS}
        nf=pool.submit(fetch_news)
        sources={s:f.result() for s,f in futures.items()};news=nf.result()
    events=[];errors=[]
    for source,bundle in sources.items():
        rows=bundle['events']
        if bundle['error']:errors.append(bundle['error'])
        elif not min(e['date'] for e in rows)<=str(now.date())<=max(e['date'] for e in rows):
            errors.append(source+' calendar does not cover today')
        events.extend(e.copy() for e in rows if now.date()<=datetime.fromisoformat(e['date']).date()<=now.date()+timedelta(days=45))
    try:confirmations=json.loads((BASE/'vic_release_confirmations.json').read_text())
    except (OSError,ValueError):confirmations={}
    for e in events:
        if e['date']!=str(now.date()) or e['impact']!='HIGH':continue
        try:
            proof=release_evidence(e,now)
            manual=confirmations.get(e['id']) if isinstance(confirmations,dict) else None
            if not proof and isinstance(manual,dict) and e['scheduled_at']:
                if stamp(e['scheduled_at'])<=stamp(manual['at'])<=now:proof=manual
            if proof:e.update(release_confirmed_at=proof['at'],release_evidence=proof['url'])
        except Exception as exc:e['verification_error']=type(exc).__name__
    return {'events':sorted(events,key=lambda e:(e['date'],e['scheduled_at'] or '',e['title'])),
            'sources':sources,'calendar_errors':errors,'news':news,'checked_at':now.isoformat()}


def atomic_json(path,data):
    path=Path(path);tmp=None
    try:
        with tempfile.NamedTemporaryFile('w',dir=path.parent,prefix=path.name+'.',suffix='.tmp',delete=False) as f:
            tmp=f.name;json.dump(data,f,indent=2,allow_nan=False);f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if tmp and os.path.exists(tmp):os.unlink(tmp)


def confirm_release(e,now=None):
    """Called only by an explicit dashboard user confirmation, not by a clock."""
    now=stamp(now or datetime.now(ET))
    if not e.get('scheduled_at') or not stamp(e['scheduled_at'])<=now or e['date']!=str(now.date()):
        raise ValueError('Cannot confirm an undated, future or different-day event')
    path=BASE/'vic_release_confirmations.json'
    try:data=json.loads(path.read_text())
    except FileNotFoundError:data={}
    data={k:v for k,v in data.items() if stamp(v['at']).date()==now.date()}
    data[e['id']]={'at':now.isoformat(),'url':e['url'],'method':'USER_VERIFIED'}
    atomic_json(path,data)


class VicRiskManager:
    def __init__(self,total_account_balance=0.0,max_vix=None,post_news_minutes=None):
        import os
        self.total_balance=float(total_account_balance)
        self.max_vix=float(max_vix if max_vix is not None else os.getenv('VIC_MAX_VIX','35'))
        self.post_news_minutes=float(post_news_minutes if post_news_minutes is not None else os.getenv('VIC_POST_NEWS_MINUTES','15'))
        if not 0<self.max_vix<200 or not 0<=self.post_news_minutes<=240:raise ValueError('Invalid VIC policy')

    def get_allocated_budget(self,vix_score):
        v=float(vix_score)
        if not 0<v<200:raise ValueError('Invalid VIX')
        return self.total_balance*(.25 if v<20 else .50 if v<=30 else .80)

    def evaluate(self,context,market,now=None):
        now=stamp(now or datetime.now(ET));reasons=[];bias='UNKNOWN';vix=None
        try:
            if not 0<=(now-stamp(context['checked_at'])).total_seconds()<=90:raise ValueError()
            if set(context['sources'])!=set(CALENDARS):raise ValueError()
            for source in context['sources'].values():
                rows=source.get('events',[])
                if source.get('error'):raise ValueError()
                if source.get('mode')=='LOCAL SNAPSHOT':
                    if not stamp(source['imported_at'])<=now<stamp(source['expires_at']):raise ValueError()
                if not rows or not min(e['date'] for e in rows)<=str(now.date())<=max(e['date'] for e in rows):raise ValueError()
                if not 0<=(now-stamp(source['checked_at'])).total_seconds()<=1800:raise ValueError()
        except (ValueError,TypeError,KeyError):reasons.append('Calendar status missing or stale')
        reasons.extend(context.get('calendar_errors',[]))
        news=context.get('news',{})
        try:
            if news.get('error') or not 0<=(now-stamp(news['checked_at'])).total_seconds()<=120:raise ValueError()
        except (ValueError,TypeError,KeyError):reasons.append(news.get('error') or 'News status missing or stale')
        alerts=active_alerts(news.get('items',[]),now,stamp)
        for alert in alerts:
            reasons.append('Material-news pause ('+alert['category']+') until '+stamp(alert['pause_until']).strftime('%H:%M ET')+': '+alert['title'])
        breadth_market=market
        qqq=market.get('qqq_bars',[])
        # Existing callers need no new fields or imports. Optional fetch failures are context-only.
        if 'mag7_status' not in market and qqq:
            try:breadth_market={**market,**mag7_snapshot(qqq[-1]['bar_end'])}
            except Exception:pass
        mag7=breadth(breadth_market.get('mag7_status',{}),breadth_market.get('mag7_bar_end'),now,stamp)
        if qqq and (not mag7.get('bar_end') or stamp(mag7['bar_end'])!=stamp(qqq[-1]['bar_end'])):
            mag7=breadth({},None,now,stamp)
        breadth_note=f"Mag-7 context: {mag7['bias']} ({mag7['green']}/7 green, {mag7['red']}/7 red, {mag7['available']}/7 available); preference {mag7['preferred_engine'] or 'none'}. Context only, not a veto."

        try:
            vix=finite(market['vix'])
            if not vix>0 or not 0<=(now-stamp(market['vix_at'])).total_seconds()<=600:raise ValueError()
            if vix>=self.max_vix:reasons.append(f'VIX {vix:.2f} at/above limit {self.max_vix:g}')
        except (ValueError,TypeError,KeyError):reasons.append('VIX missing, invalid or over 10 minutes old')
        bars=market.get('qqq_bars',[])
        try:
            if len(bars)<2:raise ValueError()
            prev,last=bars[-2:];end=stamp(last['bar_end'])
            if not 0<=(now-end).total_seconds()<=180 or (end-stamp(prev['bar_end'])).total_seconds()!=300:raise ValueError()
            if any(stamp(b['bar_end']).date()!=now.date() for b in (prev,last)):raise ValueError()
            for b in (prev,last):
                ts=stamp(b['bar_end'])
                if ts.minute%5 or ts.second or ts.microsecond or any(finite(b[k])<=0 for k in ('close','ema9','ema21')):raise ValueError()
            if all(finite(b['close'])>finite(b['ema9'])>finite(b['ema21']) for b in (prev,last)):bias='BULLISH'
            elif all(finite(b['close'])<finite(b['ema9'])<finite(b['ema21']) for b in (prev,last)):bias='BEARISH'
            else:bias='NEUTRAL'
        except (ValueError,TypeError,KeyError):reasons.append('QQQ completed candles missing or stale')
        today=[e for e in context.get('events',[]) if e['date']==str(now.date()) and e['impact']=='HIGH']
        for e in today:
            if not e.get('scheduled_at'):reasons.append(e['title']+': release time unconfirmed');continue
            due=stamp(e['scheduled_at'])
            if now<due:reasons.append(e['title']+f': pending {due:%I:%M %p %Z}');continue
            proof=e.get('release_confirmed_at')
            if not proof:reasons.append(e['title']+': publication/completion not yet verified');continue
            confirmed=stamp(proof)
            if not due<=confirmed<=now:reasons.append(e['title']+': invalid release confirmation');continue
            if now<confirmed+timedelta(minutes=self.post_news_minutes):reasons.append(e['title']+': post-release pause');continue
            try:
                if bias not in {'BULLISH','BEARISH'} or any(stamp(b['bar_end'])-timedelta(minutes=5)<confirmed for b in bars[-2:]):
                    reasons.append(e['title']+': awaiting two full post-release trend candles')
            except (ValueError,KeyError):reasons.append('Post-release candles unavailable')
        if now.weekday()>=5 or not (9,50)<=(now.hour,now.minute)<(15,0):reasons.append('Outside QQQ entry window (09:50–15:00 ET weekdays)')
        reasons=list(dict.fromkeys(reasons));light='RED' if reasons else 'GREEN'
        # Never issue a lease that extends past a required-input freshness deadline.
        deadlines=[now+timedelta(seconds=45),now.replace(hour=15,minute=0,second=0,microsecond=0)]
        if light=='GREEN':
            deadlines.extend([stamp(market['vix_at'])+timedelta(seconds=600),stamp(bars[-1]['bar_end'])+timedelta(seconds=180),stamp(news['checked_at'])+timedelta(seconds=120)])
        return {'schema_version':1,'heartbeat':now.isoformat(),'health':light,'current_bias':bias,
                'permission':{'light':light,'checked_at':now.isoformat(),'valid_until':min(deadlines).isoformat()},
                'briefing':('; '.join(reasons) if reasons else 'Required macro inputs available; no active configured block. HERO/BEAR must still pass their own entry rules.')+' '+breadth_note+' News: only HIGH material-event reports can pause; WATCH is informational.',
                'reasons':reasons,'vix':vix,'mag7':mag7,'news_alerts':alerts,'policy':{'max_vix':self.max_vix,'post_news_minutes':self.post_news_minutes},
                'events':context.get('events',[]),'news':news,'calendar_errors':context.get('calendar_errors',[]),
                'calendar_sources':{s:{k:v for k,v in b.items() if k!='events'} for s,b in context.get('sources',{}).items()},
                'scope':'Fed/BLS/BEA calendar + market-wide Yahoo Finance/CNBC/BBC Business RSS. Material-event heuristics are unverified headline triage, not comprehensive coverage or AI sentiment. Mag-7 is context only.'}


def mag7_snapshot(bar_end):
    """Yahoo context for standalone VIC/dashboard. Executor uses aligned Alpaca bars."""
    def work():
        import yfinance as yf
        import pandas as pd
        end=stamp(bar_end);ts=pd.Timestamp(end)-pd.Timedelta(minutes=5)
        def one(symbol):
            try:
                f=yf.Ticker(symbol).history(period='5d',interval='5m',prepost=False,auto_adjust=False,actions=False,timeout=8,raise_errors=True)
                if f.index.tz is None or f.index.has_duplicates:return symbol,None
                f=f.tz_convert(ET).sort_index().between_time('09:30','15:55')
                f=f[f.index+pd.Timedelta(minutes=5)<=end];prior=f[f.index.date<end.date()]
                if ts not in f.index or prior.empty or prior.index[-1].strftime('%H:%M') not in ('15:55','12:55'):return symbol,None
                # Reject missing intervening weekday sessions conservatively (holiday may yield UNKNOWN).
                day=prior.index[-1].date();expected=end.date()-timedelta(days=1)
                while expected.weekday()>=5:expected-=timedelta(days=1)
                if day!=expected:return symbol,None
                current,previous=finite(f.loc[ts,'Close']),finite(prior.Close.iloc[-1])
                if min(current,previous)<=0:return symbol,None
                return symbol,'GREEN' if current>previous else 'RED' if current<previous else 'FLAT'
            except Exception:return symbol,None
        with ThreadPoolExecutor(max_workers=4) as pool:statuses={s:v for s,v in pool.map(one,MAG7) if v}
        return {'mag7_status':statuses,'mag7_bar_end':end.isoformat()}
    end=stamp(bar_end);current=datetime.now(ET)
    if end.date()!=current.date() or not 0<=(current-end).total_seconds()<=180:
        return {'mag7_status':{},'mag7_bar_end':bar_end}
    return cached('mag7:'+str(bar_end),60,work)


def market_snapshot(include_mag7=True):
    import yfinance as yf
    import pandas as pd
    now=datetime.now(ET);out={'qqq_bars':[]}
    for symbol in ('QQQ','^VIX'):
        try:
            df=yf.Ticker(symbol).history(period='5d',interval='5m',prepost=False,auto_adjust=False,actions=False,timeout=12,raise_errors=True)
            if df.index.tz is None:raise ValueError('Unzoned bars')
            df=df.tz_convert(ET).sort_index()
            df=df[(df.index+pd.Timedelta(minutes=5)<=now)&(df.index.hour*60+df.index.minute>=570)&(df.index.hour*60+df.index.minute<960)]
            if df.empty or df.index.has_duplicates:raise ValueError('Missing/duplicate bars')
            if symbol=='^VIX':out.update(vix=float(df.Close.iloc[-1]),vix_at=(df.index[-1]+pd.Timedelta(minutes=5)).isoformat())
            else:
                df['ema9']=df.Close.ewm(span=9,adjust=False,min_periods=9).mean();df['ema21']=df.Close.ewm(span=21,adjust=False,min_periods=21).mean()
                out['qqq_bars']=[{'bar_end':(ts+pd.Timedelta(minutes=5)).isoformat(),'close':float(r.Close),'ema9':float(r.ema9),'ema21':float(r.ema21)} for ts,r in df.tail(2).iterrows()]
        except Exception:pass  # Evaluator supplies an explicit missing/stale reason.
    if include_mag7 and out['qqq_bars']:
        out.update(mag7_snapshot(out['qqq_bars'][-1]['bar_end']))
    return out


def run_once():
    from dotenv import load_dotenv
    load_dotenv(BASE/'.env',override=False)
    context=collect_context();market=market_snapshot()
    report=VicRiskManager().evaluate(context,market)
    atomic_json(BASE/'vic_telemetry.json',report)
    return report


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--once',action='store_true');args=parser.parse_args()
    try:
        while True:
            try:
                result=run_once();print(result['heartbeat'],result['health'],result['briefing'],flush=True)
            except Exception as exc:print('VIC unavailable:',type(exc).__name__,'— previous permission will expire.',flush=True)
            if args.once:break
            time.sleep(15)
    except KeyboardInterrupt:print('VIC stopped; entry permission will expire.')
