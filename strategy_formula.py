"""Shared unoptimized paper-test formula: BB rejection, EMA confirmation, room.
Every setup is reconstructed from at most four completed same-session candles;
its signal ID uses the rejection time, preventing repeat entries after restart.
"""
from datetime import datetime,timedelta,timezone


def evaluate(rule,data,side,now=None):
    result={'action':'WAIT','reasons':[],'signal_id':None,'strategy':'BB_EMA_STRUCTURE_V1'}
    reasons=result['reasons'];sign=1 if side=='CALL' else -1
    try:
        now=rule._time(now or datetime.now(timezone.utc))
        permission=data.get('vic_permission',{}) or {}
        if permission.get('light')!='GREEN':reasons.append('VIC_RED_OR_UNKNOWN')
        try:
            rule._fresh(permission['checked_at'],now,60)
            if rule._time(permission['valid_until'])<=now:raise ValueError('Expired')
        except (KeyError,ValueError,TypeError):reasons.append('VIC_PERMISSION_STALE_OR_INVALID')
        end=rule._fresh(data['bar_end'],now,180)
        if data.get('bar_complete') is not True or end.minute%5 or end.second or end.microsecond:raise ValueError('Incomplete candle')
        if now.date()!=end.date() or now.weekday()>=5 or not '09:50'<=now.strftime('%H:%M')<'15:00':reasons.append('OUTSIDE_ENTRY_WINDOW')
        bars=data['strategy_bars']
        if not 1<=len(bars)<=4:raise ValueError('Expected up to four strategy candles')
        if rule._time(bars[-1]['bar_end'])!=end:raise ValueError('Mismatched strategy candle')
        for i,b in enumerate(bars):
            t=rule._time(b['bar_end'])
            for key in ('open','high','low','close','ema9','ema21','previous_ema9','previous_ema21','lower','upper','atr'):
                if rule._num(b[key])<=0:raise ValueError('Invalid '+key)
            if not b['low']<=min(b['open'],b['close'])<=max(b['open'],b['close'])<=b['high'] or b['lower']>=b['upper']:raise ValueError('Invalid candle geometry')
            if i and t-rule._time(bars[i-1]['bar_end'])!=timedelta(minutes=5):
                # Overnight boundaries are allowed only outside the candidate's same-day window.
                if t.date()==rule._time(bars[i-1]['bar_end']).date():raise ValueError('Gap in completed candles')
        candidate=None;rejection_seen=False;invalidated=False
        for i in range(len(bars)-1,-1,-1):
            b=bars[i];t=rule._time(b['bar_end'])
            if t.date()!=end.date() or t.strftime('%H:%M')<'09:35':continue
            reject=(b['low']<b['lower']<b['close']<b['upper']) if sign==1 else (b['high']>b['upper']>b['close']>b['lower'])
            if not reject:continue
            rejection_seen=True
            stop=b['low']-.10*b['atr'] if sign==1 else b['high']+.10*b['atr']
            after=bars[i+1:]
            if any(x['low']<=stop if sign==1 else x['high']>=stop for x in after):invalidated=True;continue
            candidate=(i,b,stop,t);break
        if candidate is None:
            reasons.append('SETUP_INVALIDATED' if invalidated else 'NO_BB_REJECTION_IN_LAST_4_BARS')
        else:
            i,b,stop,t=candidate;age=len(bars)-1-i;result['setup_age_bars']=age
            result['signal_id']=f'QQQ-{side}-{t.isoformat()}'
            if age==0:reasons.append('WAIT_NEXT_BAR_EMA_CONFIRMATION')
            layer=b['structure'];asof=rule._time(layer['asof'])
            if asof>t-timedelta(minutes=5):raise ValueError('Structure uses future data')
            extreme=b['low'] if sign==1 else b['high']
            tol=.25*b['atr']
            zones=layer['zones']
            nearby=[z for z in zones if z['low']-tol<=extreme<=z['high']+tol and (z['price']<=b['close'] if sign==1 else z['price']>=b['close'])]
            if not nearby:reasons.append('REJECTION_NOT_NEAR_STRUCTURE')
            last=bars[-1];c=last['close'];e9=last['ema9'];e21=last['ema21']
            aligned=(c>e9>e21 and e9>last['previous_ema9'] and e21>last['previous_ema21']) if sign==1 else (c<e9<e21 and e9<last['previous_ema9'] and e21<last['previous_ema21'])
            if not aligned:reasons.append('EMA_ALIGNMENT_OR_SLOPE_NOT_CONFIRMED')
            # New levels confirmed before the entry candle also constrain available room.
            current=last['structure']['zones']
            targets=[max(c,z['low']) for z in current if z['price']>c] if sign==1 else [min(c,z['high']) for z in current if z['price']<c]
            target=(min(targets) if sign==1 else max(targets)) if targets else None
            risk=sign*(c-stop);reward=sign*(target-c) if target is not None else None
            rr=reward/risk if reward is not None and risk>0 else None
            result.update(stop_price=stop,target_level=target,underlying_risk=risk,room_r=rr,setup_bar_end=t.isoformat(),rsi_context=data.get('rsi_14_5m'))
            if risk<=0:reasons.append('INVALID_STOP_DISTANCE')
            if rr is None:reasons.append('NO_OPPOSING_LEVEL_FOR_ROOM_CHECK')
            elif rr<1.5:reasons.append('ROOM_BELOW_1_5R')
            if result['signal_id'] in rule.state['submitted_signals']:reasons.append('SIGNAL_ALREADY_SUBMITTED')
        if any(p['remaining_qty']>0 for p in rule.state['positions'].values()):reasons.append('POSITION_ALREADY_OPEN')
        if not reasons:result['action']='BUY_'+side+'_SIGNAL'
    except (KeyError,ValueError,TypeError,OverflowError) as exc:reasons.append('INVALID_ENTRY_DATA: '+str(exc))
    rule.last_entry_decision=result
    return result


def technical_exit(rule,p,data,side,now):
    """Evaluate bar-based exits independently of missing option quotes or VIC."""
    try:
        end=rule._fresh(data['bar_end'],now,330)
        if data.get('bar_complete') is not True or end.minute%5 or end.second or end.microsecond:return None
        c,e9,e21,hi,lo,upper,lower=[rule._num(data[k]) for k in ('price_close','ema_9_5m','ema_21_5m','price_high','price_low','upper_bband','lower_bband')]
        if min(c,e9,e21,hi,lo,upper,lower)<=0 or lo>c or hi<c or lower>=upper:return None
        stop=p.get('stop_price')
        if stop is not None and (lo<=stop if side=='CALL' else hi>=stop):return 'QQQ_SETUP_INVALIDATION'
        if (hi>upper>c>lower if side=='CALL' else lo<lower<c<upper):return 'OPPOSITE_BOLLINGER_REJECTION'
        if (c<e21 if side=='CALL' else c>e21):return 'EMA21_TECHNICAL_EXIT'
        if p['runner_active'] and (c<e9 if side=='CALL' else c>e9):return 'RUNNER_EMA9_EXIT'
    except (KeyError,ValueError,TypeError):pass
    return None
