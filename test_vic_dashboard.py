"""VIC wire round-trips and existing activity layout with stock options."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import unittest

from telemetry_link import sanitize_teams, sanitize_engine_status, sanitize_snapshot

NOW='2026-10-13T19:58:00+00:00'


def report():
    return {'team_id':'vic','label':'VIC','paper':True,'heartbeat':NOW,'day':'2026-10-13',
            'starting_equity':10000,'health':'SCANNING','entry_enabled':True,'entry_budget':10000,
            'realized_pnl':25,'unrealized_pnl':0,'completed_trades':1,'wins':1,
            'roster_version':'vic-2026-10-13-v1','exit_policy':'Session close and position risk controls.',
            'decisions':{'vic':{'action':'BUY_CALL_SIGNAL','reasons':['FRESH_CATALYST'],
                                'symbol':'AAPL','score':0.8,'strategy_id':'orb_005',
                                'entry_reason':'Opening-range break after fresh company news.'}},
            'metrics':{'bar_end':NOW,'universe_count':3450,'scanned_count':3400,'candidate_count':20,'strategies_evaluated':1000},
            'trades':[{'symbol':'AAPL261023C00250000','owner':'VIC','quantity':1,'remaining_qty':0,
                       'entry_at':NOW,'closed_at':NOW,'quote_at':NOW,'entry_price':2,'exit_price':2.25,
                       'realized_pnl':25,'unrealized_pnl':0,'setup':'opening_range','strategy_id':'orb_005',
                       'entry_reason':'Opening-range break after fresh company news.','exit_reason':'TARGET',
                       'strategy_provenance':{'team_id':'vic','strategy_version':'vic-v1.0.0',
                          'roster_version':'vic-2026-10-13-v1','label':'ORB 5 minute','captured_at':NOW},
                       'raw_account':{'secret':'DO_NOT_PUBLISH'}}],
            'activities':[{'symbol':'AAPL261023C00250000','owner':'VIC','type':'ENTRY_FILLED','timestamp':NOW,'qty':1,'price':2}],
            'api_key':'DO_NOT_PUBLISH'}


class VicTelemetryTests(unittest.TestCase):
    def test_all_stock_positions_and_reasons_survive_sanitization(self):
        clean=sanitize_teams({'teams':[report()]})
        self.assertEqual(len(clean),1)
        row=clean[0]
        self.assertEqual(row['team_id'],'vic')
        self.assertEqual(row['starting_equity'],10000)
        self.assertEqual(row['trades'][0]['symbol'],'AAPL261023C00250000')
        self.assertEqual(row['trades'][0]['owner'],'VIC')
        self.assertEqual(row['trades'][0]['strategy_id'],'orb_005')
        self.assertIn('fresh company news',row['trades'][0]['entry_reason'])
        self.assertEqual(row['decisions']['vic']['symbol'],'AAPL')
        self.assertEqual(row['metrics']['universe_count'],3450)
        self.assertNotIn('DO_NOT_PUBLISH',json.dumps(clean))
        self.assertEqual(sanitize_teams(clean),clean)

    def test_nonpaper_unknown_owners_and_bad_contracts_are_not_published(self):
        raw=report();raw['paper']=False
        self.assertEqual(sanitize_teams([raw]),[])
        raw=report();raw['team_id']='unknown'
        self.assertEqual(sanitize_teams([raw]),[])
        raw=report();raw['trades'][0]['symbol']='AAPL'
        self.assertEqual(sanitize_teams([raw])[0]['trades'],[])

    def test_absent_vic_capital_is_not_fabricated(self):
        raw=report();raw.pop('starting_equity')
        self.assertIsNone(sanitize_teams([raw])[0]['starting_equity'])

    def test_vic_engine_and_whole_snapshot_round_trip(self):
        engine={'release':'VIC_Paper_v1.0.0','active_team_ids':['vic'],
                'roster_version':'vic-2026-10-13-v1',
                'reconciliation':{'ok':True,'checked_at':NOW,'issues':[]},'api_key':'DO_NOT_PUBLISH'}
        self.assertEqual(sanitize_engine_status(engine)['engine_name'],'VIC')
        self.assertEqual(sanitize_engine_status(engine)['active_team_ids'],['vic'])
        raw={'schema':1,'paper':True,'observed_at':NOW,'reports':{},'teams':[report()],'engine_status':engine}
        clean=sanitize_snapshot(raw,wire=False)
        self.assertEqual(clean['teams'][0]['trades'][0]['strategy_id'],'orb_005')
        self.assertEqual(sanitize_snapshot(clean,wire=False),clean)
        self.assertNotIn('DO_NOT_PUBLISH',json.dumps(clean))

    def test_existing_activity_layout_displays_stock_option_and_entry_reason(self):
        from streamlit.testing.v1 import AppTest
        raw=report()
        script='''
from datetime import datetime, timezone
from types import SimpleNamespace
import streamlit as st
from dashboard_views import teams_panel
from telemetry_link import sanitize_teams
raw = '''+repr(raw)+'''
d=SimpleNamespace(money=lambda v:'Unavailable' if v is None else f'${v:,.2f}',
    display_time=lambda v:str(v or 'Unavailable'),card=lambda name,value,note,*args:st.caption(name+': '+str(value)))
teams_panel(d,sanitize_teams([raw]),'test',datetime(2026,10,13,19,58,tzinfo=timezone.utc))
'''
        app=AppTest.from_string(script).run(timeout=20)
        self.assertFalse(app.exception)
        self.assertIn('VIC Activity',app.subheader[0].value)
        self.assertEqual(app.selectbox(key='team_detail').value,'vic')
        tables=[table.value for table in app.dataframe]
        trades=next(table for table in tables if 'Entry reason' in table.columns and len(table))
        self.assertEqual(trades.iloc[0]['Side'],'CALL')
        self.assertEqual(trades.iloc[0]['Contract'],'AAPL261023C00250000')
        self.assertIn('fresh company news',trades.iloc[0]['Entry reason'])


if __name__=='__main__':unittest.main()
