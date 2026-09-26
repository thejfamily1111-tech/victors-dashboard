"""Causal RTH structure. Frames have timezone-aware candle START timestamps.
Levels for a rejection use only bars completed BEFORE that rejection started.
No order submission, credentials, or network access.
"""
import math
import pandas as pd


def indicators(frame):
    q=frame[['open','high','low','close','volume']].copy().sort_index()
    q['ema9']=q.close.ewm(span=9,adjust=False,min_periods=9).mean()
    q['ema21']=q.close.ewm(span=21,adjust=False,min_periods=21).mean()
    q['mid']=q.close.rolling(20).mean();dev=q.close.rolling(20).std(ddof=0)
    q['upper']=q.mid+2*dev;q['lower']=q.mid-2*dev
    tr=pd.concat([q.high-q.low,(q.high-q.close.shift()).abs(),(q.low-q.close.shift()).abs()],axis=1).max(axis=1)
    # Wilder ATR: arithmetic seed then recursive smoothing.
    atr=[];value=None
    for i,x in enumerate(tr):
        if i==13:value=float(tr.iloc[:14].mean())
        elif i>13:value=(13*value+float(x))/14
        atr.append(value if value is not None else float('nan'))
    q['atr']=atr
    return q


def complete_days(q,asof,calendar=None):
    result=[];sessions={r['date']:r for r in calendar or []}
    for day,g in q.groupby(q.index.date):
        if day>=asof.date():continue
        row=sessions.get(str(day))
        if calendar is not None and row is None:continue
        close=row['close'] if row else ('13:00' if g.index[-1].strftime('%H:%M')=='12:55' else '16:00')
        end=pd.Timestamp(str(day)+' '+close,tz=q.index.tz) if 'T' not in close else pd.Timestamp(close)
        start=pd.Timestamp(str(day)+' 09:30',tz=q.index.tz)
        if not g.index.equals(pd.date_range(start,end-pd.Timedelta(minutes=5),freq='5min')):continue
        result.append({'date':day,'high':float(g.high.max()),'low':float(g.low.min()),'close':float(g.close.iloc[-1])})
    return result


def swings(g,step):
    """Two left/right bars; strict extrema; only complete contiguous windows."""
    out=[]
    for i in range(2,len(g)-2):
        window=g.iloc[i-2:i+3]
        if window.index[-1]-window.index[0]!=pd.Timedelta(minutes=4*step):continue
        r=g.iloc[i];other=window.drop(g.index[i])
        if r.low<other.low.min():out.append((float(r.low),'swing low',str(g.index[i])))
        if r.high>other.high.max():out.append((float(r.high),'swing high',str(g.index[i])))
    return out


def structure(q,asof,atr,price,calendar=None):
    q=q[q.index+pd.Timedelta(minutes=5)<=asof]
    levels=[];days=complete_days(q,asof,calendar)
    expected=[r['date'] for r in calendar or [] if r['date']<str(asof.date())]
    expected.sort()
    byday={str(d['date']):d for d in days}
    prior=byday.get(expected[-1]) if expected else (days[-1] if days else None)
    def add(p,label,visit=None):
        if math.isfinite(p) and p>0:levels.append({'price':p,'source':label,'visit':visit})
    if prior:
        d=prior;h,l,c=d['high'],d['low'],d['close'];p=(h+l+c)/3
        for v,n in [(h,'Prior session high'),(l,'Prior session low'),(c,'Prior session close'),(p,'Daily pivot'),(2*p-h,'Pivot S1'),(2*p-l,'Pivot R1'),(p-(h-l),'Pivot S2'),(p+(h-l),'Pivot R2')]:add(v,n)
    prior_dates=[d['date'] for d in days[-5:]]
    for day,g in q.groupby(q.index.date):
        if day in prior_dates:
            bars=g.resample('15min',origin='start_day',offset='9h30min').agg({'open':'first','high':'max','low':'min','close':'last','volume':'sum'})
            counts=g.close.resample('15min',origin='start_day',offset='9h30min').count()
            bars=bars[counts==3]
            for v,n,visit in swings(bars,15):add(v,'15m '+n,visit)
        elif day==asof.date():
            grid=pd.date_range(str(day)+' 09:30',periods=3,freq='5min',tz=q.index.tz)
            if all(t in g.index for t in grid):
                add(float(g.loc[grid].high.max()),'ORB15 high');add(float(g.loc[grid].low.min()),'ORB15 low')
            for v,n,visit in swings(g,5):add(v,'Today 5m '+n,visit)
    # Context levels do not impose separate entry vetoes.
    last20=[byday[d] for d in expected[-20:] if d in byday] if expected else days[-20:]
    if len(last20)==20:
        add(max(d['high'] for d in last20),'20-session high');add(min(d['low'] for d in last20),'20-session low')
    week_start=asof.date()-pd.Timedelta(days=asof.weekday()).to_pytimedelta()
    week=[d for d in days if week_start-pd.Timedelta(days=7).to_pytimedelta()<=d['date']<week_start]
    if week:
        add(max(d['high'] for d in week),'Prior week high');add(min(d['low'] for d in week),'Prior week low')
    tolerance=max(float(atr)*.25,.01);zones=[]
    for level in sorted(levels,key=lambda x:x['price']):
        # Bounded cluster width avoids chaining many nearby levels into one giant zone.
        if not zones or level['price']-zones[-1]['low']>tolerance:
            zones.append({'low':level['price'],'high':level['price'],'sources':[],'visits':[]})
        z=zones[-1];z['high']=level['price']
        if level['source'] not in z['sources']:z['sources'].append(level['source'])
        if level['visit'] and level['visit'] not in z['visits']:z['visits'].append(level['visit'])
    for z in zones:
        z['price']=(z['low']+z['high'])/2;z['visits']=len(z['visits'])
        z['side']='SUPPORT' if z['price']<=price else 'RESISTANCE'
    sd=None
    last5=[byday[d] for d in expected[-5:] if d in byday] if expected else days[-5:]
    if len(last5)==5:
        closes=pd.Series([d['close'] for d in last5]);mean=float(closes.mean());s=float(closes.std(ddof=1))
        sd={'mean':mean,'sample_std':s,'minus_2s':mean-2*s,'plus_2s':mean+2*s,'minus_3s':mean-3*s,'plus_3s':mean+3*s,'through':str(last5[-1]['date'])}
    return {'zones':zones,'tolerance':tolerance,'daily_sd':sd,'completed_sessions':len(days),'prior_session_complete':prior is not None,'asof':asof.isoformat()}


def strategy_inputs(frame,calendar=None):
    q=indicators(frame)
    if len(q)<100:raise ValueError('At least 100 completed candles required')
    history=[]
    for i in range(max(1,len(q)-4),len(q)):
        ts=q.index[i];r=q.iloc[i];p=q.iloc[i-1]
        if not all(math.isfinite(float(r[k])) for k in ('ema9','ema21','lower','upper','atr')):continue
        # Available at bar START: excludes this bar and future confirmation bars.
        layer=structure(q.iloc[:i],ts,float(p.atr),float(p.close),calendar)
        history.append({'bar_end':(ts+pd.Timedelta(minutes=5)).isoformat(),
            'open':float(r.open),'high':float(r.high),'low':float(r.low),'close':float(r.close),
            'ema9':float(r.ema9),'ema21':float(r.ema21),'previous_ema9':float(p.ema9),'previous_ema21':float(p.ema21),
            'lower':float(r.lower),'upper':float(r.upper),'atr':float(r.atr),'structure':layer})
    r=q.iloc[-1];p=q.iloc[-2];end=q.index[-1]+pd.Timedelta(minutes=5)
    return {'strategy_bars':history,'price_close':float(r.close),'price_high':float(r.high),'price_low':float(r.low),
        'ema_9_5m':float(r.ema9),'ema_21_5m':float(r.ema21),'lower_bband':float(r.lower),'middle_bband':float(r.mid),'upper_bband':float(r.upper),
        'previous_bb_width':float(p.upper-p.lower),'bar_end':end.isoformat(),'bar_complete':True,
        'structure':structure(q,end,float(r.atr),float(r.close),calendar)}
