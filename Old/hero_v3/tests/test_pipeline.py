import unittest,tempfile,json
from pathlib import Path
from unittest.mock import patch
import pandas as pd
import numpy as np
import market_mechanics_bible as m
import market_barometer as mb
import research_momentum_bot as bot
import learn_tracker as lt
from test_hero import FakeBroker,candle,t,TZ


def history():
    sessions=[];frames=[]
    for day in pd.bdate_range('2026-08-10','2026-09-23'):
        start=pd.Timestamp(str(day.date())+' 09:30',tz=TZ);end=start+pd.Timedelta(minutes=390)
        sessions.append({'open':start.isoformat(),'close':end.isoformat()})
        idx=pd.date_range(start,end-pd.Timedelta(minutes=5),freq='5min')
        frames.append(pd.DataFrame([candle(110,100,105,105)]*len(idx),index=idx))
    f=pd.concat(frames)
    f.loc[t('10:00')]=candle(112,106,109,109)
    f.loc[t('10:05')]=candle(110,107,108,109)
    f15=f.resample('15min',origin='start_day').agg({'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'}).dropna()
    return f,f15,sessions

class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.raw,cls.raw15,cls.sessions=history()
    def test_completed_feature_ignores_future(self):
        raw=self.raw.copy();raw.loc[t('10:10')]=candle(999,1,500,500)
        f=m.completed_features(raw,self.raw15,t('10:10'))
        self.assertEqual(f['close'],108);self.assertEqual(f['latest_5m_ts'],t('10:05').isoformat())
    def test_stale_features_block(self):
        raw=self.raw[self.raw.index<t('10:05')]
        with self.assertRaisesRegex(ValueError,'STALE'):m.completed_features(raw,self.raw15,t('10:15'))
    def test_htf_strict_completed_and_session_anchor(self):
        frames=mb.completed_htf(self.raw,t('10:10'),self.sessions)
        self.assertEqual(frames[60].index[-1].strftime('%Y-%m-%d %H:%M'),'2026-09-22 15:30')
        self.assertEqual(frames[240].index[-1].strftime('%Y-%m-%d %H:%M'),'2026-09-22 13:30')
        self.assertEqual(frames['daily'].index[-1].strftime('%Y-%m-%d %H:%M'),'2026-09-22 16:00')
    def test_vic_stale_expected_bar(self):
        raw=self.raw[self.raw.index<t('10:00')]
        v=mb.evaluate_macro_clearance('SPY','PUT',108,112,105,raw5=raw,decision_ts=t('11:00'),sessions=self.sessions)
        self.assertEqual(v['verdict'],'VETO');self.assertIn('STALE',v['reason_code'])
    def test_missing_4h_veto(self):
        raw=self.raw[self.raw.index.date==t('10:00').date()]
        v=mb.evaluate_macro_clearance('SPY','PUT',108,112,105,raw5=raw,decision_ts=t('10:10'),sessions=self.sessions)
        self.assertEqual(v['verdict'],'VETO')
    def test_full_scan_shadow_A_execute_B_restart(self):
        with tempfile.TemporaryDirectory() as root:
            b=FakeBroker();e=bot.HeroEngine(b,root)
            with patch.object(mb,'evaluate_macro_clearance',return_value={'verdict':'PERMIT','sizing_scalar':1.,'reason_code':'OK'}),patch.object(bot,'now_et',return_value=t('10:10')):
                e.process('SPY',self.raw,self.raw15,self.sessions,t('10:10'),t('16:00'))
                self.assertEqual(len(b.buys),1)
                restored=bot.HeroEngine(b,root)
                restored.process('SPY',self.raw,self.raw15,self.sessions,t('10:10'),t('16:00'))
                self.assertEqual(len(b.buys),1)
            records=[x for x in lt.read_events(e.events) if x['event']=='CANDIDATE']
            self.assertEqual({x['candidate']['mode'] for x in records},{'A','B','C'})
            self.assertTrue(all(x['final_state']=='SHADOW' for x in records if x['candidate']['mode']!='B'))
    def test_persistent_outbox_recovery(self):
        with tempfile.TemporaryDirectory() as root:
            b=FakeBroker();e=bot.HeroEngine(b,root)
            with patch.object(e,'decide',side_effect=RuntimeError('interrupt')):
                with self.assertRaisesRegex(RuntimeError,'interrupt'):
                    e.process('SPY',self.raw,self.raw15,self.sessions,t('10:10'),t('16:00'))
            restored=bot.HeroEngine(b,root)
            self.assertTrue(restored.state['candidate_queue'])
            with patch.object(mb,'evaluate_macro_clearance',return_value={'verdict':'PERMIT','sizing_scalar':1.,'reason_code':'OK'}),patch.object(bot,'now_et',return_value=t('10:10')):
                restored.process('SPY',self.raw,self.raw15,self.sessions,t('10:10'),t('16:00'))
            self.assertEqual(len(b.buys),1);self.assertFalse(restored.state['candidate_queue'])
    def test_orb_freeze_after_provider_revision(self):
        with tempfile.TemporaryDirectory() as root:
            b=FakeBroker();e=bot.HeroEngine(b,root)
            with patch.object(mb,'evaluate_macro_clearance',return_value={'verdict':'VETO','sizing_scalar':0.,'reason_code':'TEST'}):
                e.process('SPY',self.raw,self.raw15,self.sessions,t('10:10'),t('16:00'))
                modified=self.raw.copy();modified.loc[t('09:30'),'High']=500
                e.process('SPY',modified,self.raw15,self.sessions,t('10:10'),t('16:00'))
            self.assertEqual(e.state['snapshots']['SPY']['features']['orb']['orb30_high'],110)
    def test_config_change_midday_blocks(self):
        with tempfile.TemporaryDirectory() as root:
            b=FakeBroker();e=bot.HeroEngine(b,root)
            with patch.object(mb,'evaluate_macro_clearance',return_value={'verdict':'VETO','sizing_scalar':0.,'reason_code':'TEST'}):
                e.process('SPY',self.raw,self.raw15,self.sessions,t('10:10'),t('16:00'))
            e.fade=m.FadeConfig(entry_mode='C')
            with self.assertRaisesRegex(ValueError,'CONFIG_CHANGED'):e.process('SPY',self.raw,self.raw15,self.sessions,t('10:10'),t('16:00'))
