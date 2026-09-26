"""Descriptive shadow score from HERO's existing snapshot; no data fetch or gate.
Weights are hypotheses. This is not the legacy score or a probability of profit.
"""
import math

def compute_alpha_score(features: dict, direction: str) -> dict:
    anatomy=features['anatomy']; rv=features['rvol']
    clv=anatomy['clv']*(1 if direction=='CALL' else -1)
    pct=rv.get('percentile')
    volume=25*pct/100 if pct is not None and math.isfinite(pct) else None
    if volume is None:
        return {'alpha_score':None,'status':'MISSING_RVOL','mode':'SHADOW','version':'FADE_DESCRIPTIVE_V1'}
    return {'alpha_score':round(50*(clv+1)/2+volume+25*anatomy['body_pct']/100,2),
            'status':'DESCRIPTIVE_ONLY','mode':'SHADOW','version':'FADE_DESCRIPTIVE_V1'}
