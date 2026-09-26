"""VIC QQQ macro monitor. Publishes entry permission; NEVER submits orders.
Run: python3 vic.py (continuous) or python3 vic.py --once.
The dashboard also evaluates VIC while open. All times are America/New_York.
Calendar scope: Fed events, BLS releases, BEA releases; not every global event.
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
import json, os, re, html, time, tempfile
import xml.etree.ElementTree as XML

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