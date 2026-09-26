"""Broker snapshot selection only. No estimated Greeks or fabricated contracts."""
from dataclasses import dataclass
from datetime import timedelta, datetime
import math
import pandas as pd

@dataclass(frozen=True)
class OptionConfig:
    target_delta: float=.65
    delta_tolerance: float=.10
    max_spread: float=.06
    min_dte: int=1
    max_dte: int=7
    max_quote_age: float=30
    min_bid: float=.05
    min_open_interest: int=100


def number(value):
    try:
        x=float(value)
        return x if math.isfinite(x) else None
    except (TypeError,ValueError):
        return None


def evaluate_snapshot(contract, snap, direction, now, config=OptionConfig()):
    if not snap or not getattr(snap,'latest_quote',None):
        return None
    q=snap.latest_quote
    try:
        ts=pd.Timestamp(q.timestamp)
        if ts.tzinfo is None:
            return None
        age=(pd.Timestamp(now)-ts).total_seconds()
    except (TypeError,ValueError,AttributeError):
        return None
    if not 0<=age<=config.max_quote_age:
        return None
    bid,ask=number(q.bid_price),number(q.ask_price)
    if bid is None or ask is None or bid<=config.min_bid or ask<=bid:
        return None
    mid=(bid+ask)/2
    spread=(ask-bid)/mid
    g=getattr(snap,'greeks',None)
    delta=number(getattr(g,'delta',None))
    iv=number(getattr(snap,'implied_volatility',None))
    if delta is None or iv is None or iv<=0 or abs(abs(delta)-config.target_delta)>config.delta_tolerance:
        return None
    if (direction=='CALL' and delta<=0) or (direction=='PUT' and delta>=0):
        return None
    oi=number(getattr(contract,'open_interest',None))
    size=number(getattr(contract,'size',None))
    if size!=100 or not getattr(contract,'tradable',False) or oi is None or oi<config.min_open_interest:
        return None
    expiry=pd.Timestamp(contract.expiration_date).date()
    dte=(expiry-pd.Timestamp(now).date()).days
    if not config.min_dte<=dte<=config.max_dte or spread>config.max_spread:
        return None
    score=100*(.6*max(0,1-spread/config.max_spread)+.4*max(0,1-abs(abs(delta)-config.target_delta)/config.delta_tolerance))
    return {'symbol':contract.symbol,'strike':float(contract.strike_price),'expiration':str(expiry),
            'dte':dte,'delta':delta,'iv':iv,'gamma':number(getattr(g,'gamma',None)),
            'theta':number(getattr(g,'theta',None)),'vega':number(getattr(g,'vega',None)),
            'bid':bid,'ask':ask,'mid':round(mid,2),'spread_ratio':spread,'quote_timestamp':ts.isoformat(),
            'quote_age_seconds':age,'open_interest':oi,'volume':None,
            'volume_status':'NOT_PROVIDED_BY_SNAPSHOT','execution_score':score,'multiplier':100,
            'open_interest_date':str(getattr(contract,'open_interest_date',''))}


def select_contract(trading, data, ticker, spot, direction, now, config=OptionConfig()):
    from alpaca.trading.requests import GetOptionContractsRequest
    from alpaca.trading.enums import ContractType
    from alpaca.data.requests import OptionSnapshotRequest
    contracts=[]; token=None
    for _ in range(20):
        req=GetOptionContractsRequest(underlying_symbols=[ticker],status='active',
            type=ContractType.CALL if direction=='CALL' else ContractType.PUT,
            expiration_date_gte=now.date()+timedelta(days=config.min_dte),
            expiration_date_lte=now.date()+timedelta(days=config.max_dte),
            strike_price_gte=str(round(spot*.95,2)),strike_price_lte=str(round(spot*1.05,2)),
            limit=100,page_token=token)
        response=trading.get_option_contracts(req)
        contracts.extend(response.option_contracts or [])
        token=getattr(response,'next_page_token',None)
        if not token:
            break
    else:
        raise RuntimeError('OPTION_CONTRACT_PAGINATION_LIMIT')
    eligible=[]
    for start in range(0,len(contracts),100):
        batch=contracts[start:start+100]
        snaps=data.get_option_snapshot(OptionSnapshotRequest(symbol_or_symbols=[c.symbol for c in batch]))
        for c in batch:
            result=evaluate_snapshot(c,snaps.get(c.symbol),direction,datetime.now(now.tzinfo),config)
            if result:
                eligible.append(result)
    return min(eligible,key=lambda c:(abs(abs(c['delta'])-config.target_delta),c['spread_ratio'])) if eligible else None
