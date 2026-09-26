"""Victor Terminal: authenticated Streamlit analysis and QQQ execution monitor.
Run: python3 -m streamlit run dashboard.py --server.address 127.0.0.1
Keep next to vic.py, hero.py, bear.py, avatar_logo.png and your existing .env.
DASHBOARD_PIN is mandatory; define it in .env or server Streamlit secrets.
This dashboard never submits orders. It computes an informational VIC report;
run run_paper.py --run --paper-orders for VIC/HERO/BEAR paper execution.
Positions/orders come from a configured private relay or local hero_telemetry.json (or bot_telemetry.json)
and bear_telemetry.json. Only explicitly permitted fields are rendered;
account balances, buying power, equity and allocation figures are omitted.
HERO/BEAR are loaded as class definitions; VIC is imported without running CLI.
"""
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import hmac
import re
import ast
import contextlib
import io
import html
import json
import math
import os

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent
ET = ZoneInfo('America/New_York')
TICKER = 'QQQ'
load_dotenv(BASE / '.env', override=False)

CSS = '''<style>
.stApp {background:#0e1117; color:#e6edf3;}
[data-testid="stSidebar"] {background:#141923;}
.block-container {padding-top:2rem;}
.status-bar {background:#161b22;border:1px solid #30363d;border-radius:8px;
padding:12px 16px;margin-bottom:18px;font-family:monospace;font-size:.85rem;
display:flex;justify-content:space-between;flex-wrap:wrap;gap:10px;}
.metric-badge-card {background:#161b22;border:1px solid #30363d;border-radius:8px;
padding:14px;margin-bottom:12px;min-height:115px;}
.metric-badge-label {font-size:.75rem;color:#8b949e;text-transform:uppercase;letter-spacing:.6px;font-weight:600;}
.metric-badge-val {font-size:1.65rem;font-weight:800;margin:5px 0;font-family:monospace;}
.metric-badge-note {font-size:.78rem;color:#a4afbd;}
.footer-note {margin-top:35px;padding:16px;border-top:1px solid #30363d;color:#8b949e;font-size:.75rem;text-align:center;}
</style>'''


def number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def money(value):
    value = number(value)
    return f'${value:,.2f}' if value is not None else '—'


def mapping(value):
    return value if isinstance(value, dict) else {}


def card(label, value, note='', color='#ffb300'):
    esc = lambda x: html.escape(str(x))
    st.markdown(f'<div class="metric-badge-card"><div class="metric-badge-label">{esc(label)}</div>'
                f'<div class="metric-badge-val" style="color:{color}">{esc(value)}</div>'
                f'<div class="metric-badge-note">{esc(note)}</div></div>', unsafe_allow_html=True)


def read_json(path):
    try:
        if not path.exists():
            return None, None
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            raise ValueError('Expected a JSON object')
        return data, None
    except (OSError, ValueError) as exc:
        return None, f'{path.name}: {type(exc).__name__}; status unavailable'


def load_status(name):
    paths = [BASE / f'{name}_telemetry.json']
    if name == 'hero':
        paths.append(BASE / 'bot_telemetry.json')
    # First explicit source wins, including errors; never hide a corrupt new file.
    for path in paths:
        if path.exists():
            data, error = read_json(path)
            return data, error, path.name
    return None, None, None


def telemetry_setting(name, default=''):
    value=os.getenv(name)
    if value is not None:return value
    try:return str(st.secrets.get(name,default))
    except Exception:return default


@st.cache_data(ttl=10,show_spinner=False)
def remote_execution_report(url,key,token):
    from telemetry_link import fetch_remote
    return fetch_remote(url,key,token)


def execution_reports(now):
    mode=telemetry_setting('TELEMETRY_MODE','local').lower()
    if mode=='local':
        return {name:load_status(name) for name in ('hero','bear')}
    unavailable={name:(None,'Remote execution report unavailable','private connection') for name in ('hero','bear')}
    if mode!='remote':
        st.error('Invalid TELEMETRY_MODE. Use local or remote.')
        return unavailable
    try:
        envelope=remote_execution_report(telemetry_setting('TELEMETRY_URL'),
            telemetry_setting('TELEMETRY_PUBLISHABLE_KEY'),telemetry_setting('TELEMETRY_READ_TOKEN'))
    except Exception:
        st.error('Private trading connection unavailable. Check the telemetry service and Streamlit secrets. No current positions can be confirmed.')
        return unavailable
    if envelope is None:
        st.info('Private connection configured; waiting for the first upload from your Mac.')
        return unavailable
    snap=envelope['snapshot']
    bridge_state,_=freshness({'heartbeat':snap.get('observed_at')},now)
    st.caption('Private paper-trading connection · Mac upload: '+display_time(snap.get('observed_at'))+
               ' · Server received: '+display_time(envelope.get('received_at')))
    if bridge_state!='RECENT REPORT':
        st.warning('Mac connection is stale or its clock is invalid. The records below are historical, not a confirmed current account view.')
    v=snap.get('vic')
    if isinstance(v,dict):
        vic_state,_=freshness(v,now)
        st.caption('VIC on Mac: '+str(v.get('health','UNKNOWN'))+' · Bias: '+str(v.get('current_bias','UNKNOWN'))+
                   ' · '+vic_state+' · Last report: '+display_time(v.get('heartbeat')))
    reports={}
    for name in ('hero','bear'):
        data=snap['reports'].get(name)
        problem=None if data else 'No valid paper executor report received from the Mac.'
        reports[name]=(data,problem,'private connection')
    return reports


def freshness(data, now):
    if not data:
        return 'NOT CONNECTED', None
    try:
        ts = pd.Timestamp(data.get('heartbeat'))
        if pd.isna(ts) or ts.tzinfo is None:
            raise ValueError()
        age = (pd.Timestamp(now) - ts).total_seconds()
        if age < -5:
            return 'CLOCK MISMATCH', age
        return ('RECENT REPORT' if age <= 90 else 'STALE REPORT'), age
    except (TypeError, ValueError):
        return 'NO VALID HEARTBEAT', None


@st.cache_data(ttl=45, show_spinner=False)
def fetch_bars(symbol=TICKER):
    import yfinance as yf
    data = yf.Ticker(symbol).history(period='1mo', interval='5m', prepost=False,
                                    auto_adjust=False, actions=False, timeout=12, raise_errors=True)
    if data.empty:
        raise ValueError(f'Provider returned no candles for {symbol}')
    return data


def rsi_series(closes, period=14):
    """Wilder smoothing with an SMA seed; neutral 50 for all-flat history."""
    values=list(closes); result=[float('nan')]*len(values)
    if len(values)<=period: return pd.Series(result,index=closes.index)
    changes=[b-a for a,b in zip(values,values[1:])]
    gain=sum(max(x,0) for x in changes[:period])/period
    loss=sum(max(-x,0) for x in changes[:period])/period
    def value():
        if gain==0 and loss==0: return 50.0
        if loss==0:return 100.0
        return 100-100/(1+gain/loss)
    result[period]=value()
    for i in range(period+1,len(values)):
        change=changes[i-1]
        gain=(gain*(period-1)+max(change,0))/period
        loss=(loss*(period-1)+max(-change,0))/period
        result[i]=value()
    return pd.Series(result,index=closes.index)


def prepare_bars(raw, now):
    df = raw.copy()
    required = ['Open', 'High', 'Low', 'Close', 'Volume']
    if not isinstance(df.index, pd.DatetimeIndex) or df.index.tz is None:
        raise ValueError('Provider timestamps must include a timezone')
    if not set(required).issubset(df.columns):
        raise ValueError('Missing candle columns')
    df.index = df.index.tz_convert(ET)
    if df.index.has_duplicates:
        raise ValueError('Duplicate candle timestamps')
    df = df.sort_index()
    df = df.between_time('09:30', '15:55')
    df = df[df.index + pd.Timedelta(minutes=5) <= pd.Timestamp(now)]
    df[required] = df[required].apply(pd.to_numeric, errors='coerce')
    if df.empty or df[required].isna().any().any():
        raise ValueError('No valid completed candles')
    if not df[required].map(math.isfinite).all().all():
        raise ValueError('Non-finite candle values')
    if ((df.High < df[['Open','Close','Low']].max(axis=1)) |
        (df.Low > df[['Open','Close','High']].min(axis=1)) |
        (df.Volume < 0) | (df.Close <= 0)).any():
        raise ValueError('Invalid OHLCV values')
    # Continuous regular-session history provides indicator warmup across days.
    df['RSI14'] = rsi_series(df.Close)
    df['EMA9'] = df.Close.ewm(span=9, adjust=False, min_periods=9).mean()
    df['EMA21'] = df.Close.ewm(span=21, adjust=False, min_periods=21).mean()
    df['BB_MID'] = df.Close.rolling(20).mean()
    dev = df.Close.rolling(20).std(ddof=0)
    df['BB_UPPER'] = df.BB_MID + 2 * dev
    df['BB_LOWER'] = df.BB_MID - 2 * dev
    df['BB_WIDTH'] = (df.BB_UPPER - df.BB_LOWER) / df.BB_MID * 100
    typical = (df.High + df.Low + df.Close) / 3
    group = df.index.date
    df['VWAP'] = (typical * df.Volume).groupby(group).cumsum() / df.Volume.groupby(group).cumsum().replace(0, float('nan'))
    return df


def opening_range(session):
    day = session.index[-1].date()
    grid = pd.date_range(f'{day} 09:30', periods=3, freq='5min', tz=ET)
    opening = session[session.index < pd.Timestamp(f'{day} 09:45', tz=ET)]
    if not opening.index.equals(grid):
        return None
    return float(opening.High.max()), float(opening.Low.min())


def qqq_orders(data):
    orders = mapping(data).get('orders', {})
    rows = list(orders.values()) if isinstance(orders, dict) else orders if isinstance(orders, list) else []
    return [o for o in rows if isinstance(o, dict) and o.get('ticker') == TICKER]


def chart_bars(df, minutes=5):
    """Aggregate complete regular-session bars; never change execution inputs."""
    if minutes not in (5, 15, 30):
        raise ValueError('Unsupported chart interval')
    if minutes == 5:
        return df.copy()
    rule = f'{minutes}min'
    grouped = df.resample(rule, origin='start_day', offset='9h30min',
                          closed='left', label='left')
    bars = grouped.agg({'Open':'first', 'High':'max', 'Low':'min',
                        'Close':'last', 'Volume':'sum'})
    # Require every constituent 5m candle; drop forming or incomplete groups.
    bars = bars[grouped.Close.count() == minutes // 5].dropna()
    if bars.empty:
        return bars
    chart = prepare_bars(bars, df.index[-1] + pd.Timedelta(minutes=5))
    # Session VWAP stays based on the original 5m volume/price observations.
    chart['VWAP'] = grouped.VWAP.last().reindex(chart.index)
    return chart


def render_chart(df, days, bands, emas, vwap, symbol=TICKER, minutes=5):
    source = df
    df = chart_bars(source, minutes)
    if df.empty:
        st.info('No complete candles available for this chart interval yet.')
        return
    dates = sorted(set(df.index.date))[-days:]
    plot = df[[d in dates for d in df.index.date]].copy()
    # Naive Eastern labels ensure browser timezone cannot shift chart times.
    x = plot.index.tz_localize(None)
    fig = go.Figure(go.Candlestick(x=x, open=plot.Open, high=plot.High, low=plot.Low,
                                  close=plot.Close, name=f'{symbol} · completed {minutes}m',
                                  increasing_line_color='#00e676', decreasing_line_color='#ff5252'))
    lines = []
    if emas:
        lines += [('EMA9','#ffd600'), ('EMA21','#ff9100')]
    if bands:
        lines += [('BB_UPPER','#8291bc'), ('BB_MID','#56617f'), ('BB_LOWER','#8291bc')]
    if vwap:
        lines += [('VWAP','#00d9ff')]
    for key, color in lines:
        fig.add_trace(go.Scatter(x=x, y=plot[key], name=key.replace('_',' '),
                                line=dict(color=color, width=1.4)))
    for day in dates:
        session = plot[plot.index.date == day]
        orb = opening_range(source[source.index.date == day])
        if orb:
            for value, color, name in [(orb[0],'#00e676','ORB15 High'), (orb[1],'#ff5252','ORB15 Low')]:
                fig.add_shape(type='line', x0=f'{day} 09:45', x1=session.index[-1].tz_localize(None),
                              y0=value, y1=value, line=dict(color=color, dash='dash', width=1.5))
                if day == dates[-1]:
                    fig.add_annotation(x=session.index[-1].tz_localize(None), y=value,
                                       text=f'{name} {value:.2f}', showarrow=False, yshift=10)
    if st.session_state.get('show_structure',True):
        try:
            layer=analysis_inputs(source)['structure'];price=float(source.Close.iloc[-1])
            # Current snapshot only: short forward extensions prevent hindsight chart lines.
            start=source.index[-1].tz_localize(None)+pd.Timedelta(minutes=5);finish=start+pd.Timedelta(minutes=15)
            for z in nearest_zones(layer,price):
                color='#00e676' if z['price']<=price else '#ff5252'
                fig.add_trace(go.Scatter(x=[start,finish],y=[z['price'],z['price']],mode='lines',
                    name=('S ' if z['price']<=price else 'R ')+f"{z['price']:.2f}",line=dict(color=color,dash='dot'),
                    hovertemplate=', '.join(z['sources'])+'<br>%{y:.2f}<extra></extra>'))
                if z['high']>z['low']:
                    fig.add_shape(type='rect',x0=start,x1=finish,y0=z['low'],y1=z['high'],fillcolor=color,opacity=.15,line_width=0)
        except (ValueError,KeyError,TypeError):pass
    fig.update_layout(template='plotly_dark', paper_bgcolor='#0e1117', plot_bgcolor='#0e1117',
                      height=520, margin=dict(l=10,r=15,t=25,b=15),
                      xaxis_rangeslider_visible=False, legend=dict(orientation='h', y=1.1),
                      xaxis_title='Eastern time · completed candles', yaxis_title=f'{symbol} price',
                      uirevision=f'{symbol}-{days}-{minutes}')
    fig.update_xaxes(rangebreaks=[dict(bounds=['sat','mon']), dict(bounds=[16,9.5],pattern='hour')])
    st.plotly_chart(fig, width='stretch')


def show_pipeline(hero, reports, now):
    """Render a strict allowlist: never send balances/account/config dictionaries to the UI."""
    for name in ('hero','bear'):
        data,error,_=reports[name];data=mapping(data)
        state,_=freshness(data,now)
        st.markdown(f'#### {name.upper()} · QQQ Positions, Orders & Activity')
        st.caption(f'Report: {state} · Last bot update: {display_time(data.get("heartbeat"))}')
        if data.get('paper') is True:
            st.caption('ALPACA PAPER · simulated orders')
        if isinstance(data.get('health'),str):st.write('Executor:',data['health'])
        if isinstance(data.get('message'),str):st.caption(data['message'])
        if isinstance(data.get('stock_feed'),str) and isinstance(data.get('option_feed'),str):
            st.caption('Execution feeds: '+data['stock_feed']+' / '+data['option_feed']+' · dashboard charts may use a different source')
        decision=data.get('decision')
        if isinstance(decision,dict):
            st.caption('Latest executor decision: '+str(decision.get('action','UNKNOWN')))
            reasons=decision.get('reasons',[])
            if isinstance(reasons,list):
                for reason in reasons:
                    if isinstance(reason,str):st.caption(reason)
            if isinstance(decision.get('reason'),str):st.caption(decision['reason'])
        if name=='hero' and isinstance(data.get('structure'),dict):
            layer=data['structure']
            with st.expander('Alpaca QQQ structure · executor snapshot'):
                st.caption('Available at '+display_time(layer.get('asof'))+' · report '+state)
                zones=layer.get('zones',[])
                selected=(sorted([z for z in zones if z.get('side')=='SUPPORT'],key=lambda z:z['price'],reverse=True)[:3]
                          +sorted([z for z in zones if z.get('side')=='RESISTANCE'],key=lambda z:z['price'])[:3])
                if selected:st.dataframe([{'Side':z['side'],'Low':z['low'],'High':z['high'],'Sources':', '.join(z['sources'])} for z in selected],hide_index=True,width='stretch')
        if error:st.warning(error)
        orders=qqq_orders(data)
        rows=[]
        for o in orders:
            # Fixed field selection prevents nested account values from being rendered.
            row={label:o.get(key) for label,key in [('Contract','symbol'),('Action','side'),('Status','state'),
                ('Quantity','quantity'),('Filled quantity','filled_qty'),('Open quantity','owned_qty'),
                ('Average fill price','avg_fill_price'),('Submitted','submitted_at'),('Updated','updated_at')]}
            row['Contract']=o.get('contract_symbol') or row['Contract']
            row['Quantity']=o.get('qty',row['Quantity'])
            row['Status']=o.get('status',row['Status'])
            for key in ('Submitted','Updated'):
                if row[key]:row[key]=display_time(row[key])
            rows.append({k:v if isinstance(v,(str,int,float,bool)) or v is None else None for k,v in row.items()})
        c1,c2,c3=st.columns(3)
        c1.metric('Reported orders',len(rows) if data else '—')
        c2.metric('Reported open order positions',sum((number(o.get('owned_qty')) or 0)>0 for o in orders) if data else '—')
        c3.metric('Reported pending orders',sum(str(o.get('state',o.get('status',''))).upper() in {'INTENT','SUBMITTED','PARTIAL','UNKNOWN','CLOSE_PENDING','NEW','ACCEPTED','PARTIALLY_FILLED','PENDING_NEW','PENDING_CANCEL'} for o in orders) if data else '—')
        if rows:st.dataframe(rows,hide_index=True,width='stretch')
        else:st.info(f'{name.upper()} has no order records connected. This does not confirm the account is flat.')
        positions=data.get('positions',[])
        if isinstance(positions,dict):positions=list(positions.values())
        if isinstance(positions,list):
            safe=[{k:o.get(k) for k in ('symbol','qty','side','avg_entry_price','current_price') if isinstance(o.get(k),(str,int,float))} for o in positions if isinstance(o,dict)]
            if safe:st.dataframe(safe,hide_index=True,width='stretch')
        activities=data.get('activities',[])
        if isinstance(activities,list):
            safe=[{k:o.get(k) for k in ('timestamp','type','symbol','side','qty','price','status') if isinstance(o.get(k),(str,int,float))} for o in activities if isinstance(o,dict)]
            if safe:
                with st.expander(f'{name.upper()} activity history'):st.dataframe(safe,hide_index=True,width='stretch')
        if data and state!='RECENT REPORT':st.warning('This report is stale or unverified; records may be historical.')
    st.caption('Trade records above come from the executor reports. run_paper.py connects the HERO/BEAR rules to Alpaca paper orders. This dashboard does not start or stop that process.')
    return {}


MAG7 = ('MSFT','AAPL','NVDA','AMZN','GOOGL','META','TSLA')


def load_rule_class(filename, class_name):
    """Load the supplied self-contained rule class, without executing module-level code.
    Only the exact API class is extracted. Classes needing imports fail visibly.
    This is not a sandbox; local Python files must be trusted.
    """
    path = BASE / filename
    if not path.is_file():
        raise ValueError(f'{filename} is not in the dashboard folder')
    tree = ast.parse(path.read_text(encoding='utf-8'))
    matches = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name]
    if len(matches) != 1:
        raise ValueError(f'{class_name} was not found in {filename}')
    namespace = {'__name__': 'dashboard_rules'}
    exec(compile(ast.Module(body=matches, type_ignores=[]), str(path), 'exec'), namespace)
    return namespace[class_name]


def mag7_context(asof):
    rows=[]; statuses={}
    for symbol in MAG7:
        try:
            frame=prepare_bars(fetch_bars(symbol),asof+pd.Timedelta(minutes=5))
            if asof not in frame.index:
                raise ValueError('Matching completed candle missing')
            previous=frame[frame.index.date<asof.date()]
            if previous.empty: raise ValueError('Prior close missing')
            # Require prior regular-session end (early closes allowed at 13:00).
            prior=previous.index[-1]
            if prior.strftime('%H:%M') not in ('15:55','12:55'):
                raise ValueError('Prior session close incomplete')
            change=(float(frame.loc[asof,'Close'])/float(previous.Close.iloc[-1])-1)*100
            status='GREEN' if change>0 else 'RED' if change<0 else 'FLAT'
            statuses[symbol]=status
            rows.append({'Symbol':symbol,'Status':status,'Change vs prior close (%)':round(change,3)})
        except Exception:
            rows.append({'Symbol':symbol,'Status':'UNAVAILABLE','Change vs prior close (%)':None})
    return statuses,rows


def analysis_inputs(df):
    from market_structure import strategy_inputs
    return strategy_inputs(df.rename(columns={'Open':'open','High':'high','Low':'low','Close':'close','Volume':'volume'}))


def nearest_zones(layer,price):
    zones=layer.get('zones',[])
    return (sorted([z for z in zones if z['price']<=price],key=lambda z:z['price'],reverse=True)[:3]
            +sorted([z for z in zones if z['price']>price],key=lambda z:z['price'])[:3])


def structure_panel(df,symbol):
    st.markdown(f'#### {symbol} · Support & Resistance')
    try:
        layer=analysis_inputs(df)['structure'];price=float(df.Close.iloc[-1])
        rows=[{'Side':'Support' if z['price']<=price else 'Resistance','Zone low':z['low'],'Zone high':z['high'],
               'Level':z['price'],'Sources':', '.join(z['sources']),'Confirmed swing visits':z['visits']} for z in nearest_zones(layer,price)]
        if rows:st.dataframe(rows,hide_index=True,width='stretch')
        else:st.info('Insufficient completed history to establish levels.')
        st.caption(f"Yahoo observation as of {display_time(layer['asof'])}. {layer['completed_sessions']} complete prior sessions available. Five-session 15m swings, prior session pivots and confirmed current-session levels; 20-session extremes appear only with enough history. Levels are zones, not guaranteed turning points.")
        sd=layer.get('daily_sd')
        if sd:
            with st.expander('Five-day standard deviation · reference only'):
                st.dataframe([{'Mean':sd['mean'],'Sample σ':sd['sample_std'],'Mean − 2σ':sd['minus_2s'],'Mean + 2σ':sd['plus_2s'],
                               'Mean − 3σ':sd['minus_3s'],'Mean + 3σ':sd['plus_3s'],'Completed through':sd['through']}],hide_index=True,width='stretch')
                st.caption('Five completed daily closes; sample standard deviation (n − 1). Multipliers apply after the square root. Separate from 20-bar Bollinger Bands; no entry veto.')
    except (ValueError,KeyError,TypeError) as exc:st.info('Structure unavailable: '+str(exc))


def rule_panel(df, vic_report=None):
    st.subheader('⚡ HERO & BEAR · Strategy Checklist')
    st.caption('BB rejection → 9/21 EMA confirmation → support/resistance and ≥1.5R room. RSI is context; no mandatory ORB breakout or Mag-7 vote. Paper-test settings have not been optimized.')
    if df is None:
        st.info('QQQ candles unavailable; rule evaluation paused.');return
    try:
        values=analysis_inputs(df);values['rsi_14_5m']=float(df.RSI14.iloc[-1])
        values['vic_permission']=mapping(vic_report).get('permission')
    except (ValueError,KeyError,TypeError) as exc:
        st.info('Strategy data unavailable: '+str(exc));return
    for name,filename,classname in [('HERO','hero.py','HeroCallExecutor'),('BEAR','bear.py','BearPutExecutor')]:
        st.markdown(f'#### {name} · QQQ entry checklist')
        try:
            cls=load_rule_class(filename,classname);result=cls().evaluate_entry(values,{})
            st.write('Yahoo observation:',result['action'])
            st.caption('Reasons: '+(', '.join(result['reasons']) or 'All entry checks passed'))
            if result.get('signal_id'):
                st.dataframe([{'Setup age (bars)':result.get('setup_age_bars'),'QQQ invalidation':result.get('stop_price'),
                               'Next opposing level':result.get('target_level'),'Available room / QQQ risk':result.get('room_r')}],hide_index=True,width='stretch')
        except Exception as exc:st.warning(f'{name} evaluation unavailable ({type(exc).__name__}). Install all matching Python files.')
    st.caption('This Yahoo checklist is observational. The Alpaca executor decision in Positions, Orders & Activity is authoritative. Stale data or expired VIC permission blocks new orders; exits are evaluated independently.')


@st.cache_data(ttl=60,show_spinner=False)
def fetch_vix_display():
    """Show the latest valid level independently; daily closes are never live permissions."""
    errors=[];now=pd.Timestamp(datetime.now(ET))
    try:
        import yfinance as yf
        raw=yf.Ticker('^VIX').history(period='5d',interval='5m',prepost=False,auto_adjust=False,actions=False,timeout=12,raise_errors=True)
        if raw.index.tz is None:raise ValueError('Missing timezone')
        raw=raw.tz_convert(ET).sort_index()
        raw=raw[(raw.index+pd.Timedelta(minutes=5)<=now)]
        closes=pd.to_numeric(raw.Close,errors='coerce')
        closes=closes[closes.map(lambda v:pd.notna(v) and math.isfinite(v) and v>0)]
        if closes.empty:raise ValueError('No completed VIX values')
        ts=closes.index[-1]+pd.Timedelta(minutes=5)
        return {'value':float(closes.iloc[-1]),'as_of':ts.isoformat(),'kind':'5-minute close','source':'Yahoo Finance','error':None}
    except Exception as exc:errors.append('Yahoo VIX: '+type(exc).__name__)
    try:
        import ssl,certifi
        from urllib.request import Request,urlopen
        ctx=ssl.create_default_context();ctx.load_verify_locations(cafile=certifi.where())
        url='https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv'
        with urlopen(Request(url,headers={'User-Agent':'Mozilla/5.0'}),context=ctx,timeout=12) as response:
            table=pd.read_csv(io.StringIO(response.read(2_000_000).decode('utf-8-sig')))
        table['DATE']=pd.to_datetime(table.DATE,format='%m/%d/%Y',errors='coerce')
        table['CLOSE']=pd.to_numeric(table.CLOSE,errors='coerce')
        table=table.dropna(subset=['DATE','CLOSE'])
        table=table[(table.DATE.dt.date<=now.date()) & table.CLOSE.map(lambda v:math.isfinite(v) and v>0)].sort_values('DATE')
        if table.empty:raise ValueError('No valid daily VIX close')
        row=table.iloc[-1]
        return {'value':float(row.CLOSE),'as_of':str(row.DATE.date()),'kind':'Daily close · historical','source':'Cboe','error':None}
    except Exception as exc:errors.append('Cboe VIX: '+type(exc).__name__)
    return {'value':None,'as_of':None,'kind':'Unavailable','source':None,'error':'; '.join(errors)}


def volatility_panel(vic_report):
    st.subheader('Macro Volatility & Execution Radar · VIC')
    quote=fetch_vix_display()
    value=number(quote.get('value'))
    st.metric('CBOE Volatility Index · VIX',f'{value:.2f}' if value is not None else '—')
    if quote.get('error'):st.warning(quote['error'])
    elif quote['kind'].startswith('Daily'):st.caption(f"{quote['source']} · {quote['kind']} · {quote['as_of']}. Display only; not a current trading quote.")
    else:st.caption(f"{quote['source']} · {quote['kind']} · {display_time(quote['as_of'])}. May be delayed; VIC separately checks freshness.")
    policy=mapping(mapping(vic_report).get('policy'))
    if policy:st.caption(f"Entry gate: VIX below {policy.get('max_vix')} · post-release pause {policy.get('post_news_minutes')} minutes. Initial configurable rules, not optimized parameters.")


@st.cache_data(ttl=900, show_spinner=False)
def fetch_fundamentals(symbol):
    import yfinance as yf
    ticker=yf.Ticker(symbol)
    result={'info':{},'errors':[], 'fetched_at':datetime.now(ET).isoformat()}
    try: result['info']=ticker.get_info() or {}
    except Exception: result['errors'].append('Company profile unavailable')
    for key,method in [('income','get_income_stmt'),('balance','get_balance_sheet'),('cashflow','get_cashflow')]:
        try:
            frame=getattr(ticker,method)(freq='yearly',pretty=False)
            if not isinstance(frame,pd.DataFrame): raise ValueError('Invalid table')
            frame=frame.copy()
            frame.columns=pd.to_datetime(frame.columns)
            frame=frame.loc[:,~frame.columns.duplicated()].sort_index(axis=1,ascending=False)
            result[key]=frame
            if frame.empty:result['errors'].append(f'{key.title()} statement unavailable')
        except Exception:
            result[key]=pd.DataFrame();result['errors'].append(f'{key.title()} statement unavailable')
    return result


def statement_value(frame, date, *names):
    if date is None or date not in frame.columns:return None
    for name in names:
        if name in frame.index:
            value=number(frame.at[name,date])
            if value is not None:return value
    return None


def pillar_report(bundle):
    income=bundle['income'];balance=bundle['balance'];cash=bundle['cashflow'];info=bundle['info']
    date=income.columns[0] if len(income.columns) else None
    bd=balance.columns[0] if len(balance.columns) else None
    cd=cash.columns[0] if len(cash.columns) else None
    previous=income.columns[1] if len(income.columns)>1 else None
    rev=statement_value(income,date,'TotalRevenue');ni=statement_value(income,date,'NetIncome')
    prev_rev=statement_value(income,previous,'TotalRevenue')
    growth=(rev/prev_rev-1)*100 if rev is not None and prev_rev is not None and prev_rev>0 and 300<=(date-previous).days<=430 else None
    def fcf_at(day):
        fcf=statement_value(cash,day,'FreeCashFlow')
        if fcf is None:
            op=statement_value(cash,day,'OperatingCashFlow');cap=statement_value(cash,day,'CapitalExpenditure')
            # Only accept a signed expenditure outflow; ambiguous positive sign stays unavailable.
            if op is not None and cap is not None and cap<=0:fcf=op+cap
        return fcf
    fcf=fcf_at(cd)
    debt=statement_value(balance,bd,'TotalDebt')
    assets=statement_value(balance,bd,'CurrentAssets');liabilities=statement_value(balance,bd,'CurrentLiabilities')
    ratio=assets/liabilities if assets is not None and liabilities is not None and liabilities>0 else None
    margin=ni/rev*100 if ni is not None and rev is not None and rev>0 else None
    # ROIC estimate: annual NOPAT / average (debt + stockholders equity - cash).
    roic=None
    if date is not None and previous is not None and 300<=(date-previous).days<=430:
        capitals=[]
        for day in (date,previous):
            vals=[statement_value(balance,day,'TotalDebt'),statement_value(balance,day,'StockholdersEquity'),
                  statement_value(balance,day,'CashAndCashEquivalents')]
            capitals.append(vals[0]+vals[1]-vals[2] if all(v is not None for v in vals) else None)
        operating=statement_value(income,date,'OperatingIncome');tax=statement_value(income,date,'TaxProvision');pretax=statement_value(income,date,'PretaxIncome')
        if all(v is not None and v>0 for v in capitals) and operating is not None and tax is not None and pretax is not None and pretax>0 and 0<=tax/pretax<=1:
            roic=operating*(1-tax/pretax)/(sum(capitals)/2)*100
    pe=number(info.get('trailingPE'))
    if pe is not None and pe<=0:pe=None
    currency=info.get('financialCurrency') or 'currency unavailable'
    fmt_date=lambda d:str(d.date()) if d is not None else 'Unavailable'
    rows=[]
    def add(label,value,passed,rule,period,unit=''):
        display='Unavailable' if value is None else f'{value:,.2f}{unit}'
        rows.append({'Pillar':label,'Value':display,'Rule':rule,'Result':'UNAVAILABLE' if passed is None else 'PASS' if passed else 'FAIL','Period / basis':period})
    add('1. P/E',pe,pe<22.5 if pe is not None else None,'0 < trailing P/E < 22.5','Provider trailing P/E · fetched '+bundle['fetched_at'],'x')
    add('2. ROIC estimate',roic,roic>9 if roic is not None else None,'ROIC > 9%',fmt_date(date),'%')
    add('3. Revenue growth',growth,growth>0 if growth is not None else None,'Latest annual revenue > prior year',fmt_date(date)+' vs '+fmt_date(previous),'%')
    add('4. Net income',ni,ni>0 if ni is not None else None,'Annual net income > 0',fmt_date(date)+' · '+currency)
    add('5. Free cash flow',fcf,fcf>0 if fcf is not None else None,'Annual FCF > 0',fmt_date(cd)+' · '+currency)
    matched_fcf=fcf_at(bd)
    coverage=debt/matched_fcf if debt is not None and matched_fcf is not None and matched_fcf>0 else None
    coverage_pass=debt<5*matched_fcf if debt is not None and matched_fcf is not None and matched_fcf>0 else False if debt is not None and matched_fcf is not None else None
    add('6. Debt / annual FCF',coverage,coverage_pass,'Debt < 5 × annual FCF; FCF must be positive',fmt_date(bd),'x')
    add('7. Current ratio',ratio,ratio>=1.2 if ratio is not None else None,'Current assets / liabilities ≥ 1.2',fmt_date(bd),'x')
    add('8. Profit margin',margin,margin>=10 if margin is not None else None,'Annual net margin ≥ 10%',fmt_date(date),'%')
    return pd.DataFrame(rows)


def financial_panel(symbol):
    st.divider()
    st.subheader(f'🏛️ {symbol} · Balance Sheet & Financial Health')
    with st.spinner(f'Loading {symbol} financial statements…'):
        bundle=fetch_fundamentals(symbol)
    info=bundle['info']
    st.caption(f"Source: Yahoo Finance via yfinance · fetched {bundle['fetched_at']} · annual reported statements, not a historical point-in-time backtest.")
    if info.get('quoteType') in {'ETF','MUTUALFUND'} or symbol=='QQQ':
        st.info('This is a fund. Company balance-sheet ratios and the corporate eight-pillar scorecard are not applicable. Enter a company ticker such as AAPL or MSFT to use them.')
        return
    if info.get('longName'):st.write(info['longName'])
    for error in bundle['errors']:st.caption(error)
    balance=bundle['balance'];day=balance.columns[0] if len(balance.columns) else None
    currency=info.get('financialCurrency') or 'currency unavailable'
    values=[statement_value(balance,day,'TotalAssets'),statement_value(balance,day,'TotalLiabilitiesNetMinorityInterest'),statement_value(balance,day,'TotalDebt'),statement_value(balance,day,'CashAndCashEquivalents')]
    for col,label,value in zip(st.columns(4),['Total assets','Total liabilities','Total debt','Cash & equivalents'],values):
        col.metric(label,f'{value:,.0f}' if value is not None else '—')
    st.caption(f'Balance-sheet date: {day.date() if day is not None else "unavailable"} · amounts in {currency}, full units.')
    for title,key in [('Balance sheet','balance'),('Income statement','income'),('Cash-flow statement','cashflow')]:
        with st.expander(title,expanded=key=='balance'):
            table=bundle[key].copy()
            if table.empty:st.info('Statement unavailable from provider.')
            else:
                table.columns=[str(c.date()) for c in table.columns]
                st.dataframe(table,width='stretch')
                st.download_button(f'Download {title} CSV',table.to_csv().encode(),file_name=f'{symbol}_{key}.csv',mime='text/csv',key=f'dl_{key}_{symbol}')
    st.subheader('🏛️ Eight-Pillar Financial Scorecard')
    report=pillar_report(bundle)
    available=int((report.Result!='UNAVAILABLE').sum());passed=int((report.Result=='PASS').sum())
    st.write(f'Passed {passed} of {available} assessable pillars · {8-available} unavailable')
    columns=st.columns(4)
    for i,row in report.iterrows():
        with columns[i%4]:card(row['Pillar'],row['Value'],row['Result'], '#00e676' if row['Result']=='PASS' else '#ff5252' if row['Result']=='FAIL' else '#ffb300')
    st.dataframe(report,width='stretch',hide_index=True)
    st.caption('Screening thresholds follow your old dashboard. ROIC is an estimate: operating income × (1 − effective tax rate), divided by average annual debt + equity − cash. Invalid tax rates or missing matched periods leave it unavailable. Debt coverage assumes five years at the latest annual FCF; it is not a forecast. These checks are not universal across sectors or a buy/sell recommendation.')
    st.download_button('Save scorecard CSV for future reference',report.to_csv(index=False).encode(),file_name=f'{symbol}_eight_pillars_{datetime.now(ET):%Y%m%d}.csv',mime='text/csv',key=f'score_{symbol}')


def fund_sections(df, symbol=TICKER):
    st.divider()
    st.subheader(f'🏛️ Section 1: {symbol} Session Overview')
    if df is None:
        st.info('Session data unavailable.')
        return
    session=df[df.index.date==df.index[-1].date()];last=session.iloc[-1]
    cols=st.columns(4)
    for col,label,value in zip(cols,['Session open','Session high','Session low','Completed close'],[session.Open.iloc[0],session.High.max(),session.Low.min(),last.Close]):
        col.metric(label,money(value))
    st.caption('Session observations from completed candles; no company valuation or analyst forecast is implied.')
    st.divider()
    st.subheader(f'🏛️ Section 2: Eight-Point {symbol} Monitor')
    orb=opening_range(session)
    points=[('1. ORB15', 'Complete' if orb else 'Incomplete'),('2. 9 EMA',money(last.EMA9)),
            ('3. 21 EMA',money(last.EMA21)),('4. VWAP',money(last.VWAP)),
            ('5. Upper band',money(last.BB_UPPER)),('6. Lower band',money(last.BB_LOWER)),
            ('7. Volume · last bar',f'{last.Volume:,.0f}'),('8. Data session',str(session.index[-1].date()))]
    cols=st.columns(4)
    for i,(label,value) in enumerate(points):
        with cols[i%4]:card(label,value,'Observed value','#00e5ff')
    st.markdown('#### 🎮 Interactive Future Assumptions Simulator')
    st.caption('Hypothetical price-only scenarios; no dividend, fee or tax model. These are user assumptions, not forecasts.')
    years=st.radio('Select your modeling horizon:',[1,3,5],index=2,horizontal=True,format_func=lambda x:f'{x}-Year Horizon')
    cols=st.columns(3)
    for col,label,default in zip(cols,['Low Case','Mid Case','High Case'],[-5.0,5.0,10.0]):
        with col:
            rate=st.number_input(f'{label} · annual price change (%)',min_value=-100.0,max_value=100.0,value=default,step=1.0,key=label)
            st.metric('Hypothetical ending price',money(float(last.Close)*(1+rate/100)**years))


@st.cache_resource
def vic_module():
    import importlib.util
    spec=importlib.util.spec_from_file_location('victor_vic_runtime',BASE/'vic.py')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module,'collect_context') or not hasattr(module,'headline_signal'):raise ImportError('Replace vic.py with the complete matched macro version')
    return module


def display_time(value):
    try:
        ts=pd.Timestamp(value)
        if pd.isna(ts) or ts.tzinfo is None:return 'Time / timezone not supplied'
        return ts.tz_convert(ET).strftime('%b %d, %Y · %I:%M %p %Z')
    except (ValueError,TypeError):return 'Time unavailable'


@st.cache_data(ttl=900,show_spinner=False)
def fetch_earnings(symbol):
    try:
        import yfinance as yf
        frame=yf.Ticker(symbol).get_earnings_dates(limit=8)
        if frame is None or frame.empty:return [],'No earnings dates supplied by Yahoo.'
        rows=[]
        for date in frame.index:
            ts=pd.Timestamp(date)
            time=display_time(ts) if ts.tzinfo is not None and (ts.hour or ts.minute) else 'Time not supplied'
            rows.append({'Date':str(ts.date()),'Date & time (Eastern)':time,'Event':symbol+' earnings','Status':'Provider schedule; verify with investor relations'})
        return rows,None
    except Exception as exc:return [],f'Earnings schedule unavailable ({type(exc).__name__}).'


def vic_dashboard_report(df, selected_ticker, now):
    """Keep successful public feeds even if quote loading or decision evaluation fails."""
    context={};stage='loading vic.py'
    try:
        vm=vic_module()
        stage='loading macro feeds'
        try:context=vm.collect_context()
        except Exception as exc:
            # Independent source recovery is display-only: it cannot authorize an entry.
            context={'events':[],'sources':{},'calendar_errors':[f'VIC context assembly failed ({type(exc).__name__}); entry permission remains RED.']}
            for source in vm.CALENDARS:
                try:
                    bundle=vm.fetch_calendar(source)
                    context['sources'][source]=bundle
                    context['events'].extend(e for e in bundle.get('events',[]) if str(now.date())<=e['date']<=str((pd.Timestamp(now)+pd.Timedelta(days=45)).date()))
                    if bundle.get('error'):context['calendar_errors'].append(bundle['error'])
                except Exception as feed_exc:context['calendar_errors'].append(f'{source} feed unavailable ({type(feed_exc).__name__})')
            raise RuntimeError('Context assembly failed') from exc
        stage='evaluating VIC permission'
        market={'qqq_bars':[]}
        qqq=df if selected_ticker==TICKER else None
        if selected_ticker!=TICKER:
            try:qqq=prepare_bars(fetch_bars(TICKER),now)
            except Exception:pass
        if qqq is not None and not qqq.empty:
            market['qqq_bars']=[{'bar_end':(ts+pd.Timedelta(minutes=5)).isoformat(),'close':float(r.Close),'ema9':float(r.EMA9),'ema21':float(r.EMA21)} for ts,r in qqq.tail(2).iterrows()]
        quote=fetch_vix_display()
        if quote.get('value') is not None and quote.get('kind')=='5-minute close':
            market.update(vix=quote['value'],vix_at=quote['as_of'])
        report=vm.VicRiskManager().evaluate(context,market)
    except Exception as exc:
        report={'health':'RED','current_bias':'UNKNOWN',
                'briefing':f'VIC unavailable while {stage} ({type(exc).__name__}). News and calendar feeds are displayed separately.',
                'permission':{'light':'RED'},'evaluation_error':f'{stage}: {type(exc).__name__}'+(' — replace BOTH dashboard.py and vic.py from the matched package, then restart.' if stage=='loading vic.py' else '')}
    # Never discard source data because a separate calculation raised an exception.
    report['events']=context.get('events',[])
    report['calendar_errors']=context.get('calendar_errors',[])
    report['calendar_sources']={source:{k:v for k,v in bundle.items() if k!='events'} for source,bundle in context.get('sources',{}).items()}
    if not report['calendar_sources'] and not report['calendar_errors']:
        report['calendar_errors']=['Calendar feeds were not loaded. '+report.get('evaluation_error','Check VIC setup.')]
    return report


def news_calendar_panel(symbol,vic):
    st.subheader('📅 Catalysts & Macro Schedule')
    st.caption('All times use America/New_York (EST/EDT automatically). Publication times and scheduled event times are shown separately. Calendar scope: Fed, BLS and BEA; not a complete global event calendar.')
    events=vic.get('events',[])
    show_all=st.checkbox('Show other scheduled releases too',value=False,key='all_macro_events')
    if not show_all:events=[e for e in events if e.get('impact')=='HIGH' or 'speech' in e.get('title','').lower() or 'chair' in e.get('title','').lower()]
    events=sorted(events,key=lambda e:(e['date'],e.get('scheduled_at') or ''))
    if events:
        rows=[]
        now=datetime.now(ET)
        for e in events:
            status='Published / completed — verified' if e.get('release_confirmed_at') else 'Scheduled'
            if not e.get('scheduled_at'):status='Time unconfirmed'
            elif not e.get('release_confirmed_at') and pd.Timestamp(e['scheduled_at'])<=now:status='Scheduled time passed; publication/completion unverified'
            rows.append({'Date':e['date'],'Time (Eastern)':display_time(e.get('scheduled_at')) if e.get('scheduled_at') else 'Time not supplied',
                         'Event':e['title'],'Impact rule':e['impact'],'Source':e['source'],'Status':status,'Source link':e['url']})
        st.dataframe(rows,hide_index=True,width='stretch',column_config={'Source link':st.column_config.LinkColumn('Source')})
    else:st.info('No matching upcoming events returned. Check feed status below; this is not confirmation of an event-free calendar.')
    for source,item in vic.get('calendar_sources',{}).items():
        if item.get('mode')=='LOCAL SNAPSHOT':
            st.info(f"{source}: saved calendar · imported {display_time(item.get('imported_at'))} · refresh before {display_time(item.get('expires_at'))}. Schedule changes since import are not reflected.")
    for error in vic.get('calendar_errors',[]):st.warning(error)
    st.caption('HIGH events pause new entries from the start of the day until publication/completion is verified, the pause expires and QQQ confirms a trend. A Fed press conference requires verified completion; the clock alone does not unlock trading.')
    with st.expander('Calendar connection details'):
        for source,item in vic.get('calendar_sources',{}).items():
            st.write(source, item.get('error') or (item.get('mode','ONLINE')+' · checked '+display_time(item.get('checked_at'))))
            if item.get('online_error'):st.caption(item['online_error'])
    st.subheader('📰 Market-Moving News · VIC Watch')
    try:news=vic_module().fetch_news()
    except Exception as exc:news={'error':f'Market news could not load ({type(exc).__name__}). Check that the updated vic.py is beside dashboard.py and restart Streamlit.','items':[]}
    if news.get('error'):st.info(news['error'])
    elif news.get('checked_at'):st.caption('Feed fetched '+display_time(news['checked_at'])+' · headlines may be delayed and are not exhaustive.')
    for warning in news.get('warnings',[]):st.caption(warning)
    st.caption('Positive/negative labels are provisional keyword flags. Either can pause new entries for 30 minutes while price action settles; a positive headline never authorizes a trade by itself.')
    rows=[{'Published (Eastern)':display_time(n.get('published_at')),'Headline':n.get('title'),'VIC flag':n.get('signal','UNCLASSIFIED'),'Freshness':'Historical' if n.get('stale') else 'Recent',
           'Publisher':n.get('source'),'Article':n.get('url') if str(n.get('url','')).startswith(('https://','http://')) else None} for n in news.get('items',[])]
    if rows:st.dataframe(rows,hide_index=True,width='stretch',column_config={'Article':st.column_config.LinkColumn('Read article')})
    elif not news.get('error'):st.info('No market headlines returned. Try Refresh market data; this does not mean there is no market-moving news.')
    st.link_button('Federal Reserve calendar','https://www.federalreserve.gov/newsevents/calendar.htm')
    st.link_button('BLS calendar','https://www.bls.gov/schedule/')
    st.link_button('BEA calendar','https://www.bea.gov/news/schedule')


def main():
    st.set_page_config(page_title="Victor's Dashboard | Stock Analysis", page_icon='⚡', layout='wide', initial_sidebar_state='expanded')
    st.markdown(CSS,unsafe_allow_html=True)
    pin=os.getenv('DASHBOARD_PIN','')
    if not pin:
        try:pin=str(st.secrets.get('DASHBOARD_PIN',''))
        except Exception:pass
    if not pin:
        st.error('Dashboard access is not configured. Set DASHBOARD_PIN in the server environment or Streamlit secrets, then restart.')
        st.stop()
    if not st.session_state.get('authenticated',False):
        st.title('⚡ Victor Terminal')
        st.caption('Apex Quantitative Intelligence Terminal')
        with st.form('login'):
            entered=st.text_input('Enter Access Passcode',type='password')
            submitted=st.form_submit_button('Authenticate Session')
        if submitted:
            if hmac.compare_digest(entered.encode(),pin.encode()):
                st.session_state.authenticated=True
                st.session_state.pop('login',None)
                st.rerun()
            else: st.error('Invalid PIN.')
        st.stop()
    with st.sidebar:
        if (BASE/'avatar_logo.png').is_file(): st.image(str(BASE/'avatar_logo.png'),width='stretch')
        st.markdown('## VICTOR TERMINAL')
        st.caption('QQQ · HERO / BEAR / VIC')
        st.divider()
        st.markdown('### Trading Desk')
        st.caption('QQQ calls · HERO | QQQ puts · BEAR')
        st.caption('Positions, orders and activity are shown when an executor reports them. Account balances and allocation amounts are hidden.')
        st.markdown('### Macro Officer · VIC')
        st.caption('Market news · Fed / BLS / BEA calendars')
        if st.button('Refresh market data',width='stretch'):
            fetch_bars.clear()
            fetch_vix_display.clear()
            fetch_fundamentals.clear()
            fetch_earnings.clear()
            try:vic_module().CACHE.clear()
            except Exception:pass
        auto=st.toggle('Auto-refresh · 15 seconds',value=True)
        st.markdown('### Chart overlays')
        bands=st.checkbox('Bollinger Bands · 20 / 2',True)
        st.checkbox('Support & resistance',True,key='show_structure')
        emas=st.checkbox('9 / 21 EMA',True)
        vwap=st.checkbox('VWAP',True)
        if pin and st.button('Lock Terminal',width='stretch'):
            st.session_state.authenticated=False
            st.rerun()
        st.caption('Monitor only · no order buttons')
    st.title('⚡ Victor Terminal')
    st.caption('Apex Quantitative Intelligence Terminal | QQQ Execution Monitor · Macro build 2026-09-26')
    c1,c2=st.columns(2)
    selected_ticker=c1.text_input('Asset Ticker Symbol',value=TICKER,key='analysis_ticker',help='Enter a stock or ETF symbol and press Enter. This changes analysis only; trading remains QQQ.').strip().upper()
    if not re.fullmatch(r'[A-Z0-9][A-Z0-9.\-]{0,14}',selected_ticker):
        st.info('Enter a valid stock or ETF ticker, such as AAPL, NVDA, TSLA or QQQ.')
        return
    st.caption(f'Analysis: {selected_ticker} · HERO / BEAR trade universe: QQQ only. US regular-session charts use Eastern time.')
    days=c2.slider('Lookback (Sessions)',1,5,1)

    @st.fragment(run_every='15s' if auto else None)
    def body():
        now=datetime.now(ET)
        reports=execution_reports(now)
        hero=reports['hero'][0]
        vic=None
        context=None
        state,_=freshness(hero,now)
        data_error=None
        try: df=prepare_bars(fetch_bars(selected_ticker),now)
        except Exception as exc:
            df=None
            data_error=f'{type(exc).__name__}: {selected_ticker} price data unavailable. Check the symbol and connection, then retry.'
        recent_bar='—' if df is None else (df.index[-1]+pd.Timedelta(minutes=5)).strftime('%b %d · %H:%M ET')
        esc=lambda x:html.escape(str(x))
        st.markdown(f'<div class="status-bar"><div>{esc(selected_ticker)} &nbsp;|&nbsp; Last completed candle: <b>{esc(recent_bar)}</b></div>'
                    f'<div>HERO: {esc(state)} &nbsp;|&nbsp; Dashboard: {now:%H:%M:%S} ET</div></div>',unsafe_allow_html=True)
        vic=vic_dashboard_report(df,selected_ticker,now)
        with st.expander('🏛️ VIC Desk Manager Briefing & Macro Bias',expanded=True):
            c1,c2=st.columns(2)
            c1.metric('New-entry permission',vic['health'])
            c2.metric('QQQ technical bias',vic['current_bias'])
            st.write(vic['briefing'])
            st.caption('Rule-based briefing · market-wide headlines and official calendars. Bias describes completed QQQ price action, not AI sentiment. RED never blocks exits.')
            if vic.get('heartbeat'):st.caption('Evaluated '+display_time(vic['heartbeat']))
        tab_analysis,tab_engine,tab_calendar=st.tabs(['📈 Deep-Dive Ticker Analysis','📉 VIX & Market Volatility','📅 Important Events & Market News'])
        with tab_analysis:
            st.subheader('⚡ HERO & BEAR · Positions & Trading Activity')
            snap=show_pipeline(hero,reports,now)
            st.divider()
            st.subheader(f'⚡ Technical Confluence: {selected_ticker}')
            if df is None:
                st.warning(data_error)
            else:
                last=df.iloc[-1]
                session=df[df.index.date==df.index[-1].date()]
                orb=opening_range(session)
                previous=df[df.index.date<df.index[-1].date()]
                change=(last.Close/previous.Close.iloc[-1]-1)*100 if not previous.empty else None
                cols=st.columns(5)
                with cols[0]: card(f'{selected_ticker} · completed close',money(last.Close),f'{change:+.2f}% vs prior session close' if change is not None else 'Prior session unavailable','#00e5ff')
                with cols[1]: card('EMA alignment','Bullish' if last.EMA9>last.EMA21 else 'Bearish' if last.EMA9<last.EMA21 else 'Unavailable / flat','9 EMA vs 21 EMA')
                with cols[2]: card('Bollinger Band Width',f'{last.BB_WIDTH:.2f}%' if pd.notna(last.BB_WIDTH) else '—','20 completed bars · 2σ')
                with cols[3]: card('15-Minute ORB','Locked' if orb else 'Incomplete','09:30–09:45 ET · chart session')
                with cols[4]: card(f'{selected_ticker} RSI · 14 / 5m',f'{last.RSI14:.1f}' if pd.notna(last.RSI14) else '—','Wilder · completed candles','#00e5ff')
                st.subheader(f'📊 Tactical Intraday Structure: {selected_ticker}')
                chart_minutes = st.selectbox('Chart candle interval', [5, 15, 30],
                    format_func=lambda value: f'{value} minutes', key='chart_minutes')
                st.caption(f'Chart: {chart_minutes}-minute candles, EMAs and Bollinger Bands. '
                           'Trading signals and technical cards remain on 5 minutes. '
                           'ORB stays 15 minutes; support/resistance levels and session VWAP retain their original calculation.')
                render_chart(df,days,bands,emas,vwap,selected_ticker,chart_minutes)
                structure_panel(df,selected_ticker)
                st.caption(f'Yahoo Finance · may be delayed · last displayed session: {df.index[-1].date()}. Only completed regular-session candles. Indicators use available prior sessions for warmup.')
                if df.index[-1].date()!=now.date(): st.info('Showing the latest available historical session, not today’s trading activity.')
                elif (pd.Timestamp(now)-df.index[-1]-pd.Timedelta(minutes=5)).total_seconds()>180:
                    st.info('The latest completed candle is over 3 minutes old. Session may have ended or the feed may be delayed.')
                with st.expander('🔬 Indicator Values & Opening Range',expanded=False):
                    st.dataframe([{'Close':last.Close,'EMA9':last.EMA9,'EMA21':last.EMA21,'RSI14':last.RSI14,'VWAP':last.VWAP,
                                   'Upper band':last.BB_UPPER,'Lower band':last.BB_LOWER,
                                   'ORB15 high':orb[0] if orb else None,'ORB15 low':orb[1] if orb else None}],hide_index=True,width='stretch')
            financial_panel(selected_ticker)
            fund_sections(df,selected_ticker)
        with tab_engine:
            volatility_panel(vic)
            qqq_df=df if selected_ticker==TICKER else None
            if selected_ticker!=TICKER:
                try: qqq_df=prepare_bars(fetch_bars(TICKER),now)
                except Exception: pass
            rule_panel(qqq_df,vic)
        with tab_calendar:
            news_calendar_panel(selected_ticker,vic)
        st.markdown('<div class="footer-note">Victor Terminal · QQQ monitor · Market observations and executor reports are separate data sources. Account balances are hidden.</div>',unsafe_allow_html=True)
    body()


if __name__=='__main__':
    main()
