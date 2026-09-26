"""Explicit unverified calendar status. No fabricated forward event schedule.
News risk is not integrated into VIC in this release.
"""
def get_economic_events(*args,**kwargs):
    return {'status':'NOT_CONFIGURED','events':[],'reason':'Verified calendar provider required'}
