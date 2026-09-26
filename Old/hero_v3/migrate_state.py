"""Offline legacy state conversion; never edits the source or contacts the broker."""
import argparse,json
from pathlib import Path
from research_momentum_bot import fresh_state,atomic_json
from market_mechanics_bible import stable_id

def migrate(old):
    if old.get('pending_setups'): raise ValueError('Cancel and reconcile legacy pending orders before migration')
    result=fresh_state()
    for ticker,t in old.get('active_trades',{}).items():
        if not t.get('client_order_id','').startswith('HERO-') or not t.get('qty'):
            raise ValueError('Unverifiable legacy ownership')
        sid=stable_id(t['client_order_id'],'LEGACY')
        c={'strategy_version':'HERO_MOMENTUM_BASELINE','hero_version':'LEGACY_MIGRATED','ticker':ticker,
           'setup_id':sid,'signal_id':sid,'breach_id':None,'mode':'LEGACY','direction':t['direction'],
           'decision_ts':t['signal_created_at'],'entry_spot':t['entry_spot'],'stop':t['stop'],
           'target':t['target'],'initial_r':t['initial_r'],'target_model':'LEGACY','targets':{'LEGACY':t['target']}}
        result['orders'][sid]={'ticker':ticker,'candidate':c,'contract':t['contract'],
            'entry_mid':t['entry_mid'],'requested_qty':t['qty'],'client_order_id':t['client_order_id'],
            'order_id':t['order_id'],'buy_status':'filled','state':'FILLED','filled_qty':t['qty'],
            'owned_qty':t['qty'],'avg_entry':t['avg_entry'],'exits':[],
            'bars_elapsed':0,'last_revalidation_bar_ts':t['last_revalidation_bar_ts']}
    return result

def main():
    p=argparse.ArgumentParser();p.add_argument('source');p.add_argument('output');a=p.parse_args()
    if Path(a.output).exists(): raise ValueError('Output exists; choose a new staging path')
    atomic_json(a.output,migrate(json.loads(Path(a.source).read_text())))
    print('Staged state only. Broker verification required on startup; mismatched quantity blocks.')

if __name__=='__main__':main()
