"""Offline EOD resolution with explicit date-labelled local 1m CSVs. No network."""
import argparse,json
from pathlib import Path
import pandas as pd
import learn_tracker as lt

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--bars-dir',required=True,help='TICKER_YYYY-MM-DD.csv with timestamp,Open,High,Low,Close')
    p.add_argument('--sessions',required=True,help='JSON broker calendar [{open,close}] with offsets')
    p.add_argument('--as-of',required=True,help='Timezone-aware ISO timestamp after session close')
    p.add_argument('--events',default=str(lt.LEARN_LOG_FILE));p.add_argument('--outcomes',default=str(lt.OUTCOME_FILE))
    a=p.parse_args();sessions=json.loads(Path(a.sessions).read_text())
    completed={x['setup_id'] for x in lt.read_events(a.outcomes) if x.get('resolved')}
    records={x['candidate']['setup_id']:x for x in lt.read_events(a.events) if x.get('event')=='CANDIDATE'}
    for sid,rec in records.items():
        if sid in completed: continue
        c=rec['candidate'];day=c['decision_ts'][:10]
        session=next((s for s in sessions if s['open'][:10]==day),None)
        path=Path(a.bars_dir)/f"{c['ticker']}_{day}.csv"
        if not session or not path.exists():
            print(sid,'MISSING_DATE_SPECIFIC_DATA');continue
        df=pd.read_csv(path);df.index=pd.to_datetime(df.pop('timestamp'),utc=True)
        outcome=lt.resolve_candidate_path(rec,df,as_of=a.as_of,session_close=session['close'])
        lt.append_event(outcome,a.outcomes)
        print(sid,outcome['reason_code'])

if __name__=='__main__':main()
