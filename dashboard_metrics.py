"""Display-only metrics. Never grants execution permission."""
import pandas as pd

def aggregate_bars(df, minutes, now):
    if minutes not in (5,10,15): raise ValueError('Select 5, 10 or 15 minutes')
    if minutes==5:return df
    rows=[]
    for day,frame in df.groupby(df.index.date):
        anchor=pd.Timestamp(str(day)+' 09:30',tz=df.index.tz)
        groups=((frame.index-anchor).total_seconds()//(minutes*60)).astype(int)
        for bucket,part in frame.groupby(groups):
            start=anchor+pd.Timedelta(minutes=int(bucket)*minutes)
            grid=pd.date_range(start,periods=minutes//5,freq='5min')
            if not part.index.equals(grid) or start+pd.Timedelta(minutes=minutes)>pd.Timestamp(now):continue
            rows.append((start,part.Open.iloc[0],part.High.max(),part.Low.min(),part.Close.iloc[-1],part.Volume.sum()))
    if not rows:raise ValueError('No completed candles for selected interval')
    return pd.DataFrame([r[1:] for r in rows],index=pd.DatetimeIndex([r[0] for r in rows]),columns=['Open','High','Low','Close','Volume'])

def volume_label(df):
    base=df.Volume.shift(1).rolling(20).mean().iloc[-1]
    if pd.isna(base) or base<=0:return 'Unavailable','Need 20 prior candles'
    ratio=float(df.Volume.iloc[-1]/base)
    return ('High' if ratio>=1.2 else 'Low' if ratio<.8 else 'Neutral'),f'{ratio:.2f}× previous 20 candles'

def band_label(last):
    lo,hi,c=last.BB_LOWER,last.BB_UPPER,last.Close
    if pd.isna(lo) or pd.isna(hi) or hi<=lo:return 'Unavailable','Indicator warming up'
    pos=(c-lo)/(hi-lo)
    label='Outside lower band' if pos<0 else 'Outside upper band' if pos>1 else 'Near lower band' if pos<=.1 else 'Near upper band' if pos>=.9 else 'Inside bands'
    return label,f'Band range ${lo:.2f}–${hi:.2f}'

def direction_label(vic):
    """Transparent advisory vote; VIX level itself carries no directional vote."""
    votes=[];notes=[]
    bias=vic.get('current_bias')
    if bias in ('BULLISH','BEARISH'):votes.append(1 if bias=='BULLISH' else -1);notes.append('QQQ '+bias.lower())
    mag=vic.get('mag7',{})
    if isinstance(mag,dict):
        bias=mag.get('bias')
        if bias in ('BULLISH','BEARISH'):votes.append(1 if bias=='BULLISH' else -1);notes.append('Mag-7 '+bias.lower())
    trend=vic.get('vix_trend')
    if trend in ('RISING','FALLING'):votes.append(-1 if trend=='RISING' else 1);notes.append('VIX '+trend.lower())
    if vic.get('news_alerts'):notes.append('News risk: review VIC briefing')
    return ('Unavailable' if not votes else 'Mixed' if min(votes)!=max(votes) else 'Bullish' if votes[0]>0 else 'Bearish'),(' · '.join(notes) or 'No directional inputs available')+' · Advisory only'
