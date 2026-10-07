import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd
from dashboard_data import team_totals,event_windows,change,fresh
from telemetry_link import sanitize_teams
from dashboard_metrics import aggregate_bars
T=datetime(2026,10,6,12,0,tzinfo=ZoneInfo('America/New_York'))

def fixture(team='team1'):
    return {'team_id':team,'paper':True,'day':str(T.date()),'heartbeat':T.isoformat(),'health':'SCANNING',
        'starting_equity':5000,'completed_trades':1,'wins':1,'realized_pnl':120,'unrealized_pnl':50,
        'trades':[{'symbol':'QQQ261006C00600000','quantity':4,'remaining_qty':2,'entry_price':1,'entry_at':T.isoformat(),'quote_at':T.isoformat(),'unrealized_pnl':50,'realized_pnl':20},
                  {'symbol':'QQQ261006P00590000','quantity':1,'remaining_qty':0,'entry_price':2,'entry_at':T.isoformat(),'closed_at':T.isoformat(),'unrealized_pnl':0,'realized_pnl':100}],
        'activities':[],'metrics':{},'decisions':{'hero':{'action':'WAIT','reasons':['NO_SIGNAL']}}}

class Metrics(unittest.TestCase):
    def test_partial_exit_totals(self):
        v=team_totals(sanitize_teams([fixture()]),T.date())
        self.assertEqual((v['positions'],v['contracts'],v['premium'],v['market_value']),(1,2,200,250))
        self.assertEqual((v['closed_pnl'],v['realized'],v['closed_balance']),(100,120,5100))
    def test_missing_incomplete_pending_historical(self):
        f=fixture();f['pending_entry']=True
        self.assertIsNone(team_totals(sanitize_teams([f]),T.date())['premium'])
        f=fixture();f['completed_trades']=2
        self.assertIsNone(team_totals(sanitize_teams([f]),T.date())['closed_pnl'])
        self.assertIsNone(team_totals([fixture()],datetime(2026,10,7).date()))
    def test_old_roster(self):
        v=team_totals(sanitize_teams([fixture('team'+str(i)) for i in range(1,7)]),T.date())
        self.assertEqual(v['starting'],30000);self.assertEqual(v['closed_balance'],30600)
    def test_windows_and_changes(self):
        events=[{'date':str(T.date()),'title':'CPI','impact':'HIGH'},{'date':str(T.date()),'title':'Routine','impact':'LOW'},{'date':'2026-11-05','impact':'HIGH'}]
        v=event_windows(events,T)
        self.assertEqual(len(v['Today']),1);self.assertEqual(len(v['Next 30 days']),1)
        self.assertAlmostEqual(change(4.1,4)[0]*100,10)
        self.assertAlmostEqual(change(4.1,4)[1],2.5)
        self.assertFalse(fresh('bad',T));self.assertFalse(fresh('2026-10-06T08:00:00-04:00',T))
    def test_complete_chart_groups(self):
        index=pd.date_range('2026-10-06 09:30',periods=78,freq='5min',tz=T.tzinfo)
        df=pd.DataFrame({'Open':1,'High':2,'Low':.5,'Close':1.5,'Volume':100},index=index)
        hourly=aggregate_bars(df,60,T)
        self.assertEqual(len(hourly),2);self.assertTrue((hourly.Volume==1200).all())
        self.assertEqual(len(aggregate_bars(df.drop(index[3]),60,T)),1)
    def test_sanitizer_roundtrip(self):
        f=fixture();f['account']={'key':'DO_NOT_DISPLAY'};f['trades'][0]['market_entry']={'at':T.isoformat(),'bias':'BULLISH','score':.4}
        clean=sanitize_teams([f]);self.assertEqual(clean,sanitize_teams(clean));self.assertNotIn('DO_NOT_DISPLAY',str(clean))

if __name__=='__main__':unittest.main()
