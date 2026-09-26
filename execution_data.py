"""Completed Alpaca candles for HERO/BEAR, with exchange-calendar session boundaries."""
from datetime import datetime,timedelta
import pandas as pd
from vic import ET,stamp
from hero import HeroCallExecutor
from paper_broker import num
from market_structure import strategy_inputs


def session_time(day,value):
    if 'T' in value or ' ' in value:return stamp(value)
    return datetime.fromisoformat(str(day)+'T'+value).replace(tzinfo=ET)


def prepare(raw,calendar,now):
    sessions={r['date']:(session_time(r['date'],r['open']),session_time(r['date'],r['close'])) for r in calendar}
    rows=[];seen=set()
    for r in raw:
        ts=stamp(r['t']);session=sessions.get(str(ts.date()))
        if not session or not session[0]<=ts<session[1] or ts+timedelta(minutes=5)>now:continue
        if ts in seen or ts.minute%5 or ts.second or ts.microsecond:raise ValueError('Duplicate or misaligned candle')
        seen.add(ts)
        o,h,l,c,v=[num(r[k]) for k in ('o','h','l','c','v')]
        if min(o,h,l,c)<=0 or v<0 or not l<=min(o,c)<=max(o,c)<=h:raise ValueError('Invalid OHLCV')
        rows.append({'t':ts,'open':o,'high':h,'low':l,'close':c,'volume':v})
    if len(rows)<100:raise ValueError('Insufficient completed candle warmup')
    df=pd.DataFrame(rows).set_index('t').sort_index()
    df['ema9']=df.close.ewm(span=9,adjust=False,min_periods=9).mean()
    df['ema21']=df.close.ewm(span=21,adjust=False,min_periods=21).mean()
    df['mid']=df.close.rolling(20).mean();dev=df.close.rolling(20).std(ddof=0)
    df['upper']=df.mid+2*dev;df['lower']=df.mid-2*dev
    return df


def build_inputs(raw,calendar,now):
    q=prepare(raw['QQQ'],calendar,now);last=q.iloc[-1];previous=q.iloc[-2]
    ts=q.index[-1];end=ts+timedelta(minutes=5)
    values={'price_close':float(last.close),'previous_close':float(previous.close),
       'ema_9_5m':float(last.ema9),'ema_21_5m':float(last.ema21),'middle_bband':float(last.mid),
       'lower_bband':float(last.lower),'upper_bband':float(last.upper),
       'previous_bb_width':float(previous.upper-previous.lower),'bar_end':end.isoformat(),
       'previous_bar_end':(q.index[-2]+timedelta(minutes=5)).isoformat(),'bar_complete':True,
       'rsi_14_5m':HeroCallExecutor.calculate_rsi(q.close.tolist()),'rsi_bar_end':end.isoformat(),
       'orb_end':now.replace(hour=9,minute=45,second=0,microsecond=0).isoformat(),'orb_locked':False,
       'mag7_bar_end':end.isoformat()}
    starts=[now.replace(hour=9,minute=m,second=0,microsecond=0) for m in (30,35,40)]
    if all(t in q.index for t in starts) and now>=now.replace(hour=9,minute=45,second=0,microsecond=0):
        opening=q.loc[starts];values.update(orb_locked=True,orb_high=float(opening.high.max()),orb_low=float(opening.low.min()))
    statuses={}
    prior_sessions=[r for r in calendar if r['date']<str(now.date())]
    if prior_sessions:
        prior=max(prior_sessions,key=lambda r:r['date'])
        previous_close_ts=session_time(prior['date'],prior['close'])-timedelta(minutes=5)
        for symbol in HeroCallExecutor.MAG7:
            try:
                f=prepare(raw[symbol],calendar,now)
                if ts not in f.index or previous_close_ts not in f.index:continue
                change=float(f.loc[ts,'close']-f.loc[previous_close_ts,'close'])
                statuses[symbol]='GREEN' if change>0 else 'RED' if change<0 else 'FLAT'
            except (ValueError,KeyError):continue
    bars=[{'bar_end':(t+timedelta(minutes=5)).isoformat(),'close':float(r.close),'ema9':float(r.ema9),'ema21':float(r.ema21)} for t,r in q.tail(2).iterrows()]
    values.update(strategy_inputs(q,calendar))
    return values,statuses,bars
