"""VIC macro/risk governor; completed session-anchored HTF data only."""
import pandas as pd
import numpy as np
from market_mechanics_bible import _to_eastern, _normalize_decision_ts

VIC_MODE='ENFORCE'
TICKER_SECTOR_MAP={'SPY':'QQQ','QQQ':'SPY','SMH':'QQQ','NVDA':'SMH','AMD':'SMH',
                  'MSFT':'QQQ','AAPL':'QQQ','AMZN':'QQQ','META':'QQQ','TSLA':'QQQ','COIN':'QQQ'}

def completed_htf(raw5, decision_ts, sessions):
    """sessions: broker calendar [{open: aware ISO, close: aware ISO}].
    Strict 1H/4H windows start at session open. Short closing windows are excluded
    from HTF bars, retained in completed daily bars; never cross overnight gaps.
    """
    df=_to_eastern(raw5); now=_normalize_decision_ts(decision_ts)
    frames={60:[],240:[], 'daily':[]}; expected={60:None,240:None,'daily':None}
    for session in sessions:
        start,end=(_normalize_decision_ts(session[k]) for k in ('open','close'))
        for minutes in (60,240,'daily'):
            duration=int((end-start).total_seconds()/60) if minutes=='daily' else minutes
            cursor=start
            while cursor+pd.Timedelta(minutes=duration)<=end:
                finish=cursor+pd.Timedelta(minutes=duration)
                if finish<=now:
                    expected[minutes]=finish
                    grid=pd.date_range(cursor,finish-pd.Timedelta(minutes=5),freq='5min')
                    rows=df[(df.index>=cursor)&(df.index<finish)]
                    if rows.index.equals(grid):
                        frames[minutes].append({'timestamp':finish,'Open':float(rows.Open.iloc[0]),
                            'High':float(rows.High.max()),'Low':float(rows.Low.min()),
                            'Close':float(rows.Close.iloc[-1]),'Volume':float(rows.Volume.sum())})
                cursor=finish
    result={}
    for key,rows in frames.items():
        frame=pd.DataFrame(rows)
        if frame.empty or expected[key] is None or frame.timestamp.iloc[-1]!=expected[key]:
            raise ValueError('VIC_STALE_OR_INCOMPLETE_'+str(key))
        frame=frame.set_index('timestamp')
        frame['EMA20']=frame.Close.ewm(span=20,adjust=False).mean()
        tr=pd.concat([frame.High-frame.Low,(frame.High-frame.Close.shift()).abs(),(frame.Low-frame.Close.shift()).abs()],axis=1).max(axis=1)
        frame['ATR14']=tr.rolling(14).mean()
        result[key]=frame
    return result


def find_swing_pivot_zones(df):
    highs,lows=[],[]
    for i in range(2,len(df)-2):
        if df.High.iloc[i]>df.High.iloc[i-2:i].max() and df.High.iloc[i]>df.High.iloc[i+1:i+3].max():
            highs.append(float(df.High.iloc[i]))
        if df.Low.iloc[i]<df.Low.iloc[i-2:i].min() and df.Low.iloc[i]<df.Low.iloc[i+1:i+3].min():
            lows.append(float(df.Low.iloc[i]))
    return highs,lows


def evaluate_macro_clearance(ticker,direction,spot_price,stop_price,target_price,*,raw5,decision_ts,sessions):
    result={'mode':'ENFORCE','verdict':'VETO','sizing_scalar':0.,'decision_ts':str(decision_ts),
            'reason_code':'VIC_DATA_UNAVAILABLE','ticker':ticker}
    try:
        frames=completed_htf(raw5,decision_ts,sessions)
        h,f,d=frames[60],frames[240],frames['daily']
        if len(h)<25 or len(f)<7 or len(d)<20:
            raise ValueError('VIC_INSUFFICIENT_HISTORY')
        r=abs(spot_price-stop_price)
        atr=float(h.ATR14.iloc[-1])
        if r<=0 or not np.isfinite(atr) or atr<=0:
            raise ValueError('VIC_INVALID_RISK_OR_ATR')
        sign=1 if direction=='CALL' else -1
        dist=sign*(h.Close.iloc[-1]-h.EMA20.iloc[-1])
        slope=sign*(h.EMA20.iloc[-1]-h.EMA20.iloc[-3])
        verdict,scalar,code='PERMIT',1.,'1H_TREND_ALIGNED'
        if dist < -.2*atr and slope<0:
            verdict,scalar,code='VETO',0.,'1H_STRONG_COUNTER_TREND'
        elif dist<0 or slope<0:
            verdict,scalar,code='DOWNGRADE',.5,'1H_MARGINAL'
        highs,lows=find_swing_pivot_zones(f)
        levels=[x for x in (highs if sign==1 else lows) if sign*(x-spot_price)>0]
        obstacle=min(levels,key=lambda x:abs(x-spot_price)) if levels else None
        distance=abs(obstacle-spot_price)/r if obstacle is not None else None
        if distance is not None and distance<1:
            verdict,scalar,code='VETO',0.,'4H_OBSTACLE_WITHIN_1R'
        elif distance is not None and distance<2 and verdict!='VETO':
            verdict,scalar,code='DOWNGRADE',min(scalar,.5),'4H_OBSTACLE_INSIDE_2R'
        result.update(verdict=verdict,sizing_scalar=scalar,reason_code=code,
            data_timestamp_1h=h.index[-1].isoformat(),data_timestamp_4h=f.index[-1].isoformat(),
            data_timestamp_daily=d.index[-1].isoformat(),nearest_obstacle=obstacle,obstacle_distance_r=distance,
            trend_1h='BULLISH' if h.Close.iloc[-1]>=h.EMA20.iloc[-1] else 'BEARISH',
            structure_4h='BULLISH' if f.Close.iloc[-1]>=f.EMA20.iloc[-1] else 'BEARISH',
            daily_regime='BULLISH' if d.Close.iloc[-1]>=d.EMA20.iloc[-1] else 'BEARISH',
            daily_mode='CONTEXT_ONLY',news_status='NOT_IMPLEMENTED')
    except (ValueError,TypeError,KeyError,IndexError) as exc:
        result['reason_code']=str(exc)
    return result
