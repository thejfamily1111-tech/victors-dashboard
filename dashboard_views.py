"""Approved Victor Terminal views. Display only; no broker or strategy mutations."""
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
import io
import json
import re
from urllib.request import Request,urlopen
import pandas as pd
import streamlit as st
from dashboard_data import num,change,fresh,team_totals,event_windows,daily_observation
from team_settings import NAMES,ENTRY_LABELS

GREEN='#28cf85';RED='#ff6464';YELLOW='#f5c451';GRAY='#8b949e'
MAG7=('AAPL','MSFT','AMZN','GOOGL','META','NVDA','TSLA')
IR={'AAPL':'https://investor.apple.com/','MSFT':'https://www.microsoft.com/en-us/Investor/','AMZN':'https://ir.aboutamazon.com/','GOOGL':'https://abc.xyz/investor/','META':'https://investor.atmeta.com/','NVDA':'https://investor.nvidia.com/','TSLA':'https://ir.tesla.com/'}

def color(value):
    v=num(value)
    return GRAY if v is None else GREEN if v>0 else RED if v<0 else YELLOW

def pct(value):return f'{value:+.2f}%' if num(value) is not None else 'N/A'

def quote_one(symbol):
    try:
        import yfinance as yf
        ticker=yf.Ticker(symbol)
        info=ticker.get_info()
        now=pd.Timestamp.now(tz='America/New_York')
        stamp=info.get('regularMarketTime')
        at=pd.Timestamp(stamp,unit='s',tz='UTC').isoformat() if num(stamp) else None
        value=num(info.get('regularMarketPrice'));prior=num(info.get('regularMarketPreviousClose'))
        delta,relative=change(value,prior)
        bid,ask=num(info.get('bid')),num(info.get('ask'))
        if bid is None or ask is None or not 0<bid<=ask:bid=ask=None
        prior_change=None
        if symbol in MAG7:
            try:
                daily=ticker.history(period='5d',interval='1d',auto_adjust=False,actions=False,timeout=8,raise_errors=True)
                if daily.index.tz is not None:
                    daily=daily.tz_convert('America/New_York');daily=daily[daily.index.date<now.date()]
                    if len(daily)>=2:prior_change=change(daily.Close.iloc[-1],daily.Close.iloc[-2])[1]
            except Exception:pass
        return dict(previous_session_change_pct=prior_change,value=value,prior=prior,change=delta,change_pct=relative,at=at,bid=bid,ask=ask,
                    spread=ask-bid if bid is not None else None,received_at=now.isoformat(),source='Yahoo Finance · indicative / may be delayed')
    except Exception as exc:return {'error':type(exc).__name__}

@st.cache_data(ttl=300,show_spinner=False)
def public_market(symbol):
    symbols=list(dict.fromkeys([symbol,'^VIX','^VXN',*MAG7]))
    with ThreadPoolExecutor(max_workers=4) as pool:return dict(zip(symbols,pool.map(quote_one,symbols)))

@st.cache_data(ttl=300,show_spinner=False)
def treasury():
    # Actual yields, daily observations. Never display TNX or IEF as a Treasury yield.
    try:
        now=pd.Timestamp.now(tz='America/New_York')
        start=str((now-timedelta(days=30)).date())
        url='https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10,DGS2&cosd='+start
        import ssl,certifi
        ctx=ssl.create_default_context(cafile=certifi.where())
        with urlopen(Request(url,headers={'User-Agent':'VictorTerminal/2'}),timeout=10,context=ctx) as response:
            frame=pd.read_csv(io.BytesIO(response.read(200000)),index_col=0,parse_dates=True)
        return {k:daily_observation(frame[[k]],now) for k in ('DGS10','DGS2')}
    except Exception as exc:return {'error':type(exc).__name__}

@st.cache_data(ttl=900,show_spinner=False)
def earnings():
    def one(symbol):
        try:
            import yfinance as yf
            frame=yf.Ticker(symbol).get_earnings_dates(limit=8)
            now=pd.Timestamp.now(tz='America/New_York');end=now+timedelta(days=30)
            if frame is None:return []
            rows=[]
            for index in frame.index:
                ts=pd.Timestamp(index)
                if ts.tzinfo is None:continue
                ts=ts.tz_convert('America/New_York')
                if now.date()<=ts.date()<end.date():
                    rows.append({'Company':symbol,'Release date':str(ts.date()),'Release time ET':ts.strftime('%I:%M %p %Z') if ts.hour or ts.minute else 'TBA',
                        'Session':'Before market' if 0<ts.hour<9 else 'After market' if ts.hour>=16 else 'Time unconfirmed',
                        'Call date / time ET':'TBA · verify investor relations','Confirmation':'Provider estimate; verify IR','Source':IR[symbol]})
            return rows
        except Exception:return [{'Company':symbol,'Release date':'Unavailable','Release time ET':'TBA','Session':'Unknown','Call date / time ET':'TBA','Confirmation':'Feed unavailable','Source':IR[symbol]}]
    with ThreadPoolExecutor(max_workers=4) as pool:return [r for group in pool.map(one,MAG7) for r in group]

def market_cards(d,symbol,market,teams,vic,now):
    q=market.get(symbol,{})
    direction=next(iter(sorted([t.get('market_direction',{}) for t in teams if t.get('market_direction',{}).get('mode')=='ACTIVE'],key=lambda x:x.get('at') or '',reverse=True)),{})
    cols=st.columns(4)
    with cols[0]:
        note=f"{d.money(q.get('change'))} / {pct(q.get('change_pct'))} vs previous close {d.money(q.get('prior'))}"
        d.card(symbol+' price',d.money(q.get('value')),note,color(q.get('change')))
        st.caption('Bid '+d.money(q.get('bid'))+' · Ask '+d.money(q.get('ask'))+' · Spread '+d.money(q.get('spread')))
        st.caption('Price time '+d.display_time(q.get('at'))+' · Yahoo indicative / delayed')
        st.caption('Bid/ask timestamps unavailable; not execution quotes.')
    with cols[1]:
        bias=direction.get('bias','Unavailable');score=num(direction.get('score'));coverage=num(direction.get('coverage'))
        d.card('VIC shared direction',bias,'Score '+(f'{score:+.2f}' if score is not None else 'N/A')+' · heuristic, not probability',GREEN if bias=='BULLISH' else RED if bias=='BEARISH' else GRAY if bias=='Unavailable' else YELLOW)
        st.caption('Coverage '+(f'{coverage:.0%}' if coverage is not None else 'N/A')+' · '+('Fresh' if fresh(direction.get('at'),now) else 'Stale / unavailable'))
        st.caption('Updated '+d.display_time(direction.get('at')))
        st.caption('Previous-session QQQ technical bias: '+vic.get('_previous_technical','Unavailable')+' · completed close vs EMA9/21')
    with cols[2]:
        yields=treasury();ten=yields.get('DGS10',{});two=yields.get('DGS2',{})
        value=num(ten.get('value'));delta=num(ten.get('change'))
        d.card('Treasury · 10-year',f'{value:.2f}%' if value is not None else 'N/A',
               (f'{delta*100:+.1f} bp · {pct(ten.get("change_pct"))}' if delta is not None else 'Daily change unavailable'),color(delta))
        st.caption('Previous '+(f'{ten["prior"]:.2f}%' if ten.get('prior') is not None else 'N/A')+' · 2-year '+(f'{two["value"]:.2f}%' if two.get('value') is not None else 'N/A'))
        if two.get('change') is not None:st.caption(f'2-year {two["change"]*100:+.1f} bp · {pct(two.get("change_pct"))}')
        st.caption('FRED daily observation '+str(ten.get('date','unavailable'))+' · not intraday')
    with cols[3]:
        v=market.get('^VIX',{});vxn=market.get('^VXN',{})
        d.card('VIX',f'{v["value"]:.2f}' if v.get('value') is not None else 'N/A',pct(v.get('change_pct'))+' vs previous close',color(v.get('change')))
        st.caption('Previous '+str(v.get('prior') or 'N/A')+' · VXN '+(f'{vxn["value"]:.2f}' if vxn.get('value') is not None else 'N/A')+' / '+pct(vxn.get('change_pct')))
        st.caption('VIX '+d.display_time(v.get('at'))+' · Yahoo indicative / delayed')
        vdelta=num(v.get('change'))
        if vdelta is not None:d.card('Volatility context','Rising risk' if vdelta>0 else 'Easing risk' if vdelta<0 else 'Flat','VIX movement; QQQ effect unconfirmed',RED if vdelta>0 else GREEN if vdelta<0 else YELLOW)
    observations=[(s,market.get(s,{})) for s in MAG7]
    available=[(s,q) for s,q in observations if num(q.get('change_pct')) is not None and q.get('at') and pd.Timestamp(q['at']).tz_convert(d.ET).date()==now.date()]
    up=sum(q['change_pct']>0 for _,q in available);down=sum(q['change_pct']<0 for _,q in available)
    st.markdown('#### Magnificent 7 · today vs prior close')
    prior=[q.get('previous_session_change_pct') for _,q in observations if num(q.get('previous_session_change_pct')) is not None]
    st.caption(f'{up} up · {down} down · {len(available)}/7 dated today · Previous session: {sum(v>0 for v in prior)} up / {sum(v<0 for v in prior)} down / {len(prior)}/7 available')
    for col,(s,q) in zip(st.columns(7),observations):
        with col:
            current=(s,q) in available
            d.card(s,pct(q.get('change_pct')) if current else 'N/A','Delayed observation' if current else 'Historical / unavailable',color(q.get('change_pct')) if current else GRAY)

def events_panel(d,vic,now,today_only=False):
    windows=event_windows(vic.get('events',[]),now)
    st.subheader('Major events today · '+now.strftime('%b %d, %Y')+' ET' if today_only else 'High-impact market calendar')
    def table(events):
        rows=[]
        for e in events:
            ts=e.get('scheduled_at');state='Time TBA'
            if ts:
                try:
                    seconds=(pd.Timestamp(ts)-pd.Timestamp(now)).total_seconds()
                    state='Released / completed · source confirmed' if e.get('release_confirmed_at') else f'In {int(seconds//60)} minutes' if seconds>0 else 'Scheduled time passed · release unverified'
                except (TypeError,ValueError):state='Time unavailable'
            rows.append({'Date':e.get('date'),'Time ET':d.display_time(ts),'Event':e.get('title'),'Status':state,
                'Actual':e.get('actual','N/A'),'Consensus':e.get('consensus','N/A'),'Prior':e.get('prior','N/A'),'Source':e.get('url')})
        if rows:st.dataframe(rows,hide_index=True,width='stretch',column_config={'Source':st.column_config.LinkColumn('Source')})
        else:st.info('No matching events supplied. Check calendar coverage; this does not confirm an event-free session.')
    if today_only:table(windows['Today'])
    else:
        tabs=st.tabs(list(windows))
        for tab,events in zip(tabs,windows.values()):
            with tab:table(events)
    for message in vic.get('calendar_errors',[]):st.warning(message)
    for source,bundle in vic.get('calendar_sources',{}).items():
        st.caption(source+' · '+str(bundle.get('mode','ONLINE'))+' · checked '+d.display_time(bundle.get('checked_at') or bundle.get('imported_at')))
    st.caption('Fed / BLS / BEA coverage · HIGH impact only · actual/consensus values require a configured release-data source.')

def teams_panel(d,teams,source,now,summary_only=False):
    import copy
    displayteams=copy.deepcopy(teams)
    for t in displayteams:
        for p in t.get('trades',[]):
            if (num(p.get('remaining_qty')) or 0)>0 and not fresh(p.get('quote_at'),now,30):
                p['unrealized_pnl']=None;t['unrealized_pnl']=None
    totals=team_totals(displayteams,now.date())
    st.subheader('Paper teams · '+now.strftime('%b %d')+' ET')
    if totals:
        stale=any(not fresh(t.get('heartbeat'),now) for t in teams if t.get('day')==str(now.date()))
        if stale:st.warning('Stale team reports: the displayed totals are the last reported values, not confirmed current activity.')
        cols=st.columns(5)
        labels=[('Active positions',str(totals['positions']) if totals['positions'] is not None else 'Unconfirmed',str(totals['contracts'])+' contracts'),
            ('Active balance · premium',d.money(totals['premium']),'Remaining filled contracts at entry cost'),
            ('Open mark P/L',d.money(totals['unrealized']),'Market value '+d.money(totals['market_value'])),
            ('Closed P/L today · gross',d.money(totals['closed_pnl']),'Fully closed trades only'),
            ('Closed-day balance · virtual',d.money(totals['closed_balance']),'Starting '+d.money(totals['starting'])+' + closed P/L')]
        for col,(label,value,note) in zip(cols,labels):
            with col:d.card(label,value,note)
        st.caption(f"{totals['teams']} reporting teams · closed trades {totals['closed_trades']} · wins {totals['wins']} · losses {totals['losses']} · all realized exits (including partials) {d.money(totals['realized'])} gross. Virtual allowances are not broker equity or buying power.")
        if totals['pending']:st.info('An entry has an unregistered partial fill. Exposure and active-balance totals are incomplete.')
    else:st.info('No team reports dated today. Historical reports are available in team details.')
    if summary_only:
        scanning=sum(t.get('health')=='SCANNING' and fresh(t.get('heartbeat'),now) and t.get('day')==str(now.date()) for t in teams)
        st.caption(f'{scanning} teams reporting SCANNING · {len(teams)} connected roster records · '+str(source or 'not connected'))
        return
    lookup={t['team_id']:t for t in displayteams}
    def select_team(teamid):st.session_state.team_detail=teamid
    selected=st.selectbox('Select a team for strategy, positions and activity',list(NAMES),format_func=lambda x:x.replace('team','Team ').replace('report','Report ')+' · '+NAMES[x],key='team_detail')
    for start in range(0,len(NAMES),3):
        ids=list(NAMES)[start:start+3]
        for col,teamid in zip(st.columns(3),ids):
            with col:
                t=lookup.get(teamid,{})
                st.markdown('#### '+teamid.replace('team','Team ').replace('report','Report '))
                st.caption(NAMES[teamid])
                state=t.get('health','NOT CONNECTED') if fresh(t.get('heartbeat'),now) else 'STALE / OFFLINE' if t else 'NOT CONNECTED'
                active=[p for p in t.get('trades',[]) if (num(p.get('remaining_qty')) or 0)>0]
                if active and state not in {'STALE / OFFLINE','NOT CONNECTED'}:state += ' · OPEN '+('CALL' if active[0].get('owner')=='HERO' else 'PUT')
                st.write(state)
                st.caption('Report date '+str(t.get('day') or 'N/A')+' · '+d.display_time(t.get('heartbeat')))
                d.card('Reported realized P/L · gross',d.money(t.get('realized_pnl')),'Open mark '+d.money(t.get('unrealized_pnl')),color(t.get('realized_pnl')))
                st.button('View strategy & activity',key='view_'+teamid,on_click=select_team,args=(teamid,))
    t=lookup.get(selected,{})
    st.divider();st.subheader(NAMES[selected]+' · detail')
    st.write(ENTRY_LABELS[selected])
    if not t:st.info('This team has not supplied a report.');return
    st.caption('Current configured exit policy: '+t.get('exit_policy','Unavailable')+' Position-specific historical policy may differ.')
    st.caption('Entry allowance '+d.money(t.get('entry_budget'))+' · latest report '+d.display_time(t.get('heartbeat')))
    trades=sorted(t.get('trades',[]),key=lambda p:p.get('closed_at') or p.get('entry_at') or '')
    rows=[]
    for p in trades:
        match=re.fullmatch(r'QQQ(\d{6})([CP])(\d{8})',p.get('symbol',''))
        q=num(p.get('remaining_qty'));entry=num(p.get('entry_price'));u=num(p.get('unrealized_pnl'))
        cost=q*entry*100 if q is not None and entry is not None else None
        rows.append({'Contract':p.get('symbol'),'Expiry':match[1] if match else None,'Side':'CALL' if match and match[2]=='C' else 'PUT' if match else None,
          'Entry ET':d.display_time(p.get('entry_at')),'Closed ET':d.display_time(p.get('closed_at')) if p.get('closed_at') else None,
          'Filled qty':p.get('quantity'),'Remaining qty':q,'Entry fill':entry,'Exit fill':p.get('exit_price'),
          'Active premium':cost if q else 0,'Market value':cost+u if q and cost is not None and u is not None else 0 if q==0 else None,
          'Open mark P/L':u,'Realized P/L gross':p.get('realized_pnl'),'Quote ET':d.display_time(p.get('quote_at')),
          'Exit reason':p.get('exit_reason'),'Setup':p.get('setup')})
    if rows:
        st.markdown('#### Open positions')
        st.dataframe([r for r in rows if (r['Remaining qty'] or 0)>0],hide_index=True,width='stretch')
        st.markdown('#### Closed trades · chronological')
        st.dataframe([r for r in rows if r['Remaining qty']==0],hide_index=True,width='stretch')
        for i,p in enumerate(trades):
            with st.expander(str(p.get('symbol'))+' · entry context / exit fills · '+str(i+1)):
                st.caption('Entry context at '+d.display_time(p.get('market_entry',{}).get('at'))+' · policy '+str(p.get('market_policy_version') or 'Not supplied'))
                st.json(p.get('market_entry',{}));st.dataframe(p.get('exit_fills',[]),hide_index=True,width='stretch')
    else:st.info('No reported trades for this report date.')
    st.markdown('#### Latest decisions and chart observations')
    st.dataframe([{'Side':owner.upper(),**decision} for owner,decision in t.get('decisions',{}).items()],hide_index=True,width='stretch')
    st.caption('Chart observation '+d.display_time(t.get('metrics',{}).get('bar_end')))
    st.json(t.get('metrics',{}))
    st.markdown('#### Fill activity · chronological')
    activity=sorted(t.get('activities',[]),key=lambda a:a.get('timestamp') or '')
    if activity:st.dataframe(activity,hide_index=True,width='stretch')
    else:st.info('No fill activities supplied. The latest scan decision is shown above; full scan history is not published by this engine version.')

def news_panel(d,vic,now):
    events_panel(d,vic,now)
    st.subheader('Upcoming QQQ-company earnings · next 30 days')
    rows=earnings()
    if rows:st.dataframe(rows,hide_index=True,width='stretch',column_config={'Source':st.column_config.LinkColumn('Investor relations')})
    else:st.info('No upcoming earnings dates supplied. Call times require confirmation from investor relations.')
    st.caption('Mag-7 coverage. Release estimates and conference calls are separate; unconfirmed calls remain TBA.')
    st.subheader('Market news · newest first')
    try:news=d.vic_module().fetch_news()
    except Exception:news={'items':[],'error':'News feed unavailable.'}
    if news.get('error'):st.warning(news['error'])
    st.caption('Feed checked '+d.display_time(news.get('checked_at'))+' · headlines may be delayed; coverage is not exhaustive.')
    items=sorted(news.get('items',[]),key=lambda n:n.get('published_at') or '',reverse=True)
    rows=[{'Published ET':d.display_time(n.get('published_at')),'Headline':n.get('title'),'Publisher':n.get('source'),
           'Freshness':'Historical' if n.get('stale') else 'Provider recent','Article':n.get('url'),'QQQ effect':'Unconfirmed'} for n in items]
    if rows:st.dataframe(rows,hide_index=True,width='stretch',column_config={'Article':st.column_config.LinkColumn('Read')})
    else:st.info('No headlines supplied.')


def render(d,auto):
    @st.fragment(run_every='15s' if auto else None)
    def body():
        now=d.datetime.now(d.ET)
        raw,error,source=d.load_status('teams')
        from telemetry_link import sanitize_teams
        teams=sanitize_teams(raw)
        if error:st.warning(error)
        overview,teamtab,news,research=st.tabs(['Overview','Teams & activity','News & events','Research'])
        with overview:
            c1,c2,c3=st.columns([3,1,1])
            symbol=c1.text_input('Stock / ETF symbol',value='QQQ',key='analysis_ticker').strip().upper()
            minutes=c2.selectbox('Chart interval',[5,15,30,60],format_func=lambda v:f'{v}m')
            days=c3.selectbox('Sessions',[1,2,3,4,5])
            if not re.fullmatch(r'[A-Z0-9][A-Z0-9.\-]{0,14}',symbol):st.info('Enter a valid stock or ETF symbol.');return
            options=st.columns(6)
            toggles={label:col.toggle(label,value=default,key='indicator_'+label) for col,(label,default) in zip(options,[('BBands',True),('RSI',True),('Volume',True),('EMA9',False),('EMA21',False),('VWAP',False)])}
            df=None
            try:
                rawbars=d.fetch_bars(symbol);base=d.prepare_bars(rawbars,now);df=d.prepare_bars(rawbars,now,minutes)
            except Exception as exc:st.warning('Completed chart candles unavailable ('+type(exc).__name__+').')
            executor,_,_=d.load_status('vic')
            # Shared direction comes from Mac telemetry; display-only calendars cannot change it.
            vic=d.vic_dashboard_report(base if df is not None else None,symbol,now)
            if executor:vic['market_direction']=executor.get('market_direction',{})
            try:
                qqqbase=base if symbol=='QQQ' and df is not None else d.prepare_bars(d.fetch_bars('QQQ'),now)
                prior=qqqbase[qqqbase.index.date<now.date()]
                if not prior.empty:
                    row=prior.iloc[-1]
                    vic['_previous_technical']='Bullish' if row.Close>row.EMA9>row.EMA21 else 'Bearish' if row.Close<row.EMA9<row.EMA21 else 'Mixed'
            except Exception:pass
            market_cards(d,symbol,public_market(symbol),teams,vic,now)
            if df is not None:
                d.render_chart(df,days,toggles['BBands'],False,toggles['VWAP'],symbol,orb_source=base,
                               rsi=toggles['RSI'],volume=toggles['Volume'],ema9=toggles['EMA9'],ema21=toggles['EMA21'])
                st.caption(f'{minutes}m completed candles · Eastern time · Yahoo Finance may be delayed · latest displayed session {df.index[-1].date()} · chart toggles affect display only.')
                if df.index[-1].date()!=now.date():st.info('Historical chart session; this is not today’s activity.')
            events_panel(d,vic,now,today_only=True)
            teams_panel(d,teams,source,now,summary_only=True)
        with teamtab:
            teams_panel(d,teams,source,now)
            if not teams:
                reports={n:d.load_status(n) for n in ('hero','bear')}
                d.show_pipeline(reports['hero'][0],reports,now)
        with news:news_panel(d,vic,now)
        with research:
            st.subheader('Stock analysis & simulation research')
            st.caption('Selected asset '+symbol+' · paper-trading universe remains QQQ')
            d.financial_panel(symbol);d.fund_sections(df,symbol)
            with st.expander('Strategy rules and QQQ chart inputs'):
                qqq=df if symbol=='QQQ' and minutes==5 else None
                if qqq is None:
                    try:qqq=d.prepare_bars(d.fetch_bars('QQQ'),now)
                    except Exception:pass
                d.rule_panel(qqq,vic)
            with st.expander('Saved simulation experiments'):
                from simulation_lab import render
                render()
            supervisor,err,_=d.load_status('supervisor')
            with st.expander('AI supervisor · session research'):
                if supervisor:
                    st.caption(str(supervisor.get('date','')));st.write(supervisor.get('summary',''))
                    st.write(supervisor.get('ai_text',''));st.dataframe(supervisor.get('recommendations',[]),hide_index=True,width='stretch')
                else:st.info(err or 'No supervisor report connected.')
        st.caption('Victor Terminal · paper telemetry · '+now.strftime('%H:%M:%S ET'))
    body()
