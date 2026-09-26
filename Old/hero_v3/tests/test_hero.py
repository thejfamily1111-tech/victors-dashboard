import unittest,tempfile,json,copy,ast
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
import pandas as pd
import market_mechanics_bible as m
import research_momentum_bot as bot
import learn_tracker as lt
import option_engine as oe
import market_barometer as mb
import dashboard

DAY='2026-09-23';TZ='America/New_York'
def t(hh):return pd.Timestamp(f'{DAY} {hh}',tz=TZ)
def candle(h=109,l=101,c=105,o=105):return pd.Series({'Open':o,'High':h,'Low':l,'Close':c,'Volume':100})
def opening():
    idx=pd.date_range(t('09:30'),periods=6,freq='5min')
    return pd.DataFrame([candle(110,100)]*6,index=idx)
def orb():return m.calculate_multi_orb(opening(),t('10:00').date(),t('10:00'),1)
def machine():return m.new_fade_state('SPY',orb())
def step(s,hh,bar,cfg=m.FadeConfig()):return m.advance_fade(s,bar,t(hh),t(hh)+pd.Timedelta(minutes=5),1,105,cfg)
def candidate():
    s=machine();step(s,'10:00',candle(112,106,109,109));_,cs=step(s,'10:05',candle(109,107,108,109))
    return next(c for c in cs if c['mode']=='B')
def option():return {'symbol':'SPY260925P00110000','mid':1.,'quote_timestamp':t('10:10').isoformat()}
def feat():return {'latest_5m_ts':t('10:05').isoformat(),'anatomy':{'clv':-.5,'body_pct':50},'rvol':{'percentile':50}}

class FakeBroker:
    paper=True
    def __init__(self):self.book={};self.pos={};self.buys=[];self.sells=[];self.fail=False;self.cancel_requests=[];self.timeout_buy=False
    def positions(self):
        if self.fail:raise ConnectionError('offline')
        return self.pos.copy()
    def open_orders(self):return [o for o in self.book.values() if o['status'] not in bot.TERMINAL]
    def get_order(self,cid):
        if self.fail:raise ConnectionError('offline')
        return dict(self.book[cid])
    def buy(self,symbol,qty,mid,cid):
        self.buys.append(cid);self.book[cid]={'id':cid,'client_order_id':cid,'symbol':symbol,'status':'new','qty':qty,'filled_qty':0,'filled_avg_price':None,'filled_at':None}
        if self.timeout_buy:raise TimeoutError('accepted then disconnected')
        return self.book[cid]
    def sell(self,symbol,qty,cid):
        self.sells.append((symbol,qty));self.book[cid]={'id':cid,'client_order_id':cid,'symbol':symbol,'status':'new','qty':qty,'filled_qty':0,'filled_avg_price':None,'filled_at':None};return self.book[cid]
    def cancel(self,oid):self.cancel_requests.append(oid)
    def account(self):return {'equity':100000,'buying_power':100000,'cash':100000}
    def select(self,*a):return option()
    def spot(self,*a):return 108.

class MechanicsTests(unittest.TestCase):
    def test_orb_six_bars(self):
        o=orb();self.assertEqual(o.bars_30m,6);self.assertTrue(o.orb30_locked);self.assertEqual(o.orb30_high,110)
    def test_orb_missing(self):
        self.assertFalse(m.calculate_multi_orb(opening().iloc[:-1],t('10:00').date(),t('10:00'),1).orb30_locked)
    def test_orb_duplicates(self):
        with self.assertRaisesRegex(ValueError,'DUPLICATE'):m.calculate_multi_orb(pd.concat([opening(),opening().iloc[:1]]),t('10:00').date(),t('10:00'),1)
    def test_orb_before_ten(self):
        self.assertFalse(m.calculate_multi_orb(opening(),t('09:59').date(),t('09:59'),1).orb30_locked)
    def test_end_labels(self):
        df=opening();df.index+=pd.Timedelta(minutes=5)
        self.assertTrue(m.calculate_multi_orb(df,t('10:00').date(),t('10:00'),1,bar_label='end').orb30_locked)
    def test_no_preorb_entry(self):self.assertEqual(step(machine(),'09:55',candle(112,106,109,109))[1],[])
    def test_forming_bar(self):
        with self.assertRaisesRegex(ValueError,'FORMING'):m.advance_fade(machine(),candle(),t('10:00'),t('10:04'),1,105,m.FadeConfig())
    def test_upside_no_failure(self):
        s=machine();self.assertFalse(step(s,'10:00',candle(112,108,111,109))[1]);self.assertEqual(s['state'],'TESTING_ACCEPTANCE')
    def test_downside_no_failure(self):self.assertFalse(step(machine(),'10:00',candle(102,98,99,101))[1])
    def test_upside_failure(self):
        s=machine();step(s,'10:00',candle(112,108,111,109));e,c=step(s,'10:05',candle(111,107,109,110));self.assertEqual(c[0]['direction'],'PUT');self.assertGreater(c[0]['stop'],112)
    def test_downside_reclaim(self):
        s=machine();step(s,'10:00',candle(102,98,99,101));e,c=step(s,'10:05',candle(103,99,102,100));self.assertEqual(c[0]['direction'],'CALL');self.assertLess(c[0]['stop'],98)
    def test_accepted_no_fade(self):
        s=machine();step(s,'10:00',candle(112,108,111,109));step(s,'10:05',candle(113,110,112,111));self.assertEqual(s['state'],'UPSIDE_ACCEPTED');self.assertFalse(step(s,'10:10',candle(112,106,108,111))[1])
    def test_downside_accepted(self):
        s=machine();step(s,'10:00',candle(101,98,99,100));step(s,'10:05',candle(100,97,98,99));self.assertEqual(s['state'],'DOWNSIDE_ACCEPTED');self.assertFalse(step(s,'10:10',candle(103,98,102,99))[1])
    def test_one_bar_sweep_requires_close(self):
        s=machine();e,c=step(s,'10:00',candle(112,106,109,109));self.assertEqual(c[0]['mode'],'A')
    def test_same_bar_twice(self):
        s=machine();step(s,'10:00',candle(112,106,109,109));self.assertEqual(step(s,'10:00',candle(112,106,109,109)),([],[]))
    def test_confirm_and_retest(self):
        s=machine();step(s,'10:00',candle(112,106,109,109));_,cs=step(s,'10:05',candle(110,107,108,109));self.assertEqual({x['mode'] for x in cs},{'B','C'})
    def test_stop_never_widened(self):
        s=machine();step(s,'10:00',candle(112,106,109,109));stop=s['episode']['stop'];_,cs=step(s,'10:05',candle(114,107,108,109));self.assertFalse(cs);self.assertEqual(s['episode']['stop'],stop)
    def test_dual_breach_ambiguous(self):
        s=machine();e,c=step(s,'10:00',candle(112,98,105));self.assertFalse(c);self.assertEqual(e[0]['reason_code'],'DUAL_BOUNDARY_PATH_AMBIGUOUS')
    def test_restart_same_state(self):
        s=machine();step(s,'10:00',candle(112,108,111,109));s=json.loads(json.dumps(s));self.assertEqual(step(s,'10:05',candle(111,107,109,110))[1][0]['direction'],'PUT')
    def test_frozen_orb(self):
        s=machine();step(s,'10:00',candle(112,108,111,109));self.assertEqual(s['orb']['orb30_high'],110)
    def test_attempts(self):
        s=machine();step(s,'10:00',candle(112,108,111,109));step(s,'10:05',candle(113,110,112,111));step(s,'10:10',candle(112,106,108,111));step(s,'10:15',candle(112,106,109,109));self.assertEqual(s['episode']['attempt_number'],2)
    def test_history_asof_not_clock(self):
        df=opening();df.loc[t('10:00')]=candle(999,100,105)
        self.assertEqual(m.calculate_multi_orb(df,t('10:00').date(),t('10:00'),1).orb30_high,110)
    def test_rvol_same_clock_only(self):
        df=opening();past=df.copy();past.index-=pd.Timedelta(days=1);past.Volume=50
        allbars=pd.concat([past,df]);r=m.compute_same_clock_rvol(allbars,t('09:30'));self.assertEqual(r.ratio_mean,2);self.assertEqual(r.sample_size,1)
    def test_rvol_missing_not_neutral(self):self.assertEqual(m.compute_same_clock_rvol(opening(),t('09:30')).sample_size,0)

class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.b=FakeBroker();self.e=bot.HeroEngine(self.b,self.temp.name);self.e.sync(t('10:10'))
    def tearDown(self):self.temp.cleanup()
    def arm(self):
        with patch.object(mb,'evaluate_macro_clearance',return_value={'verdict':'PERMIT','sizing_scalar':1.,'reason_code':'OK'}),patch.object(bot,'now_et',return_value=t('10:10')):
            self.e.decide(candidate(),feat(),None,[],t('10:10'),t('16:00'))
        return next(iter(self.e.state['orders'].values()))
    def filled(self):
        o=self.arm();b=self.b.book[o['client_order_id']];b.update(status='filled',filled_qty=o['requested_qty'],filled_avg_price=1.,filled_at=t('10:11').isoformat());self.b.pos[o['contract']]=o['requested_qty'];self.e.sync(t('10:11'));return o
    def test_veto_always_blocks(self):
        r=self.e.gate(candidate(),feat(),{'verdict':'VETO','mode':'SHADOW','reason_code':'TEST'},option(),self.b.account(),t('10:10'),t('16:00'));self.assertEqual(r[0],'VETOED')
    def test_qty_zero(self):self.assertEqual(bot.calculate_position_qty(100,100,10),0)
    def test_quantity_full_premium_risk(self):self.assertEqual(bot.calculate_position_qty(100000,100000,1),5)
    def test_stale_option(self):
        o=option();o['quote_timestamp']=t('10:00').isoformat();r=self.e.gate(candidate(),feat(),{'verdict':'PERMIT','sizing_scalar':1},o,self.b.account(),t('10:10'),t('16:00'));self.assertEqual(r[1],'STALE_OPTION_QUOTE')
    def test_stale_signal(self):
        r=self.e.gate(candidate(),feat(),{'verdict':'PERMIT','sizing_scalar':1},option(),self.b.account(),t('10:20'),t('16:00'));self.assertEqual(r[1],'STALE_SIGNAL')
    def test_duplicate_setup(self):self.arm();self.arm();self.assertEqual(len(self.b.buys),1)
    def test_restart_reconciles(self):
        o=self.filled();e=bot.HeroEngine(self.b,self.temp.name);e.sync(t('10:12'));self.assertEqual(e.live_orders()[0]['owned_qty'],o['requested_qty'])
    def test_failed_positions_does_not_erase(self):
        self.filled();self.b.fail=True
        with self.assertRaises(ConnectionError):self.e.sync(t('10:12'))
        self.assertEqual(len(self.e.live_orders()),1);self.assertFalse(self.e.healthy)
    def test_pending_ttl_only_new_bars(self):
        o=self.arm();bot.pending_bar_tick(o,t('10:05'),self.e.risk);self.assertEqual(o['bars_elapsed'],0)
        bot.pending_bar_tick(o,t('10:10'),self.e.risk);bot.pending_bar_tick(o,t('10:10'),self.e.risk);self.assertEqual(o['bars_elapsed'],1)
        bot.pending_bar_tick(o,t('10:15'),self.e.risk);self.assertEqual(o['cancel_reason'],'PENDING_TTL_EXPIRED')
    def test_eod_only_hero(self):
        o=self.filled();self.b.pos['AAPL']=50;self.e.manage(t('15:45'),t('16:00'));self.assertEqual(self.b.sells,[(o['contract'],o['requested_qty'])]);self.assertEqual(len(self.e.live_orders()),1)
    def test_exit_ack_not_closed(self):
        o=self.filled();self.e.exit(o,'STOP',t('10:12'));self.assertEqual(o['state'],'CLOSE_PENDING');self.e.sync(t('10:13'));self.assertEqual(o['state'],'CLOSE_PENDING')
    def test_partial_cancel_keeps_fills(self):
        o=self.arm();self.b.book[o['client_order_id']].update(status='canceled',filled_qty=2,filled_avg_price=1.);self.b.pos[o['contract']]=2;self.e.sync(t('10:12'));self.assertEqual(o['owned_qty'],2);self.assertEqual(o['state'],'FILLED')
    def test_cancel_waits_ack(self):
        o=self.arm();self.e.exit(o,'EOD',t('15:45'));self.assertFalse(self.b.sells);self.assertEqual(len(self.e.live_orders()),1)
    def test_timeout_lookup(self):
        self.b.timeout_buy=True;self.arm();self.assertEqual(self.e.live_orders()[0]['state'],'UNKNOWN');self.e.sync(t('10:12'));self.assertEqual(self.e.live_orders()[0]['state'],'SUBMITTED');self.assertEqual(len(self.b.buys),1)
    def test_closed_only_broker_filled(self):
        o=self.filled();self.e.exit(o,'TARGET',t('10:12'));x=o['exits'][0];self.b.book[x['client_order_id']].update(status='filled',filled_qty=o['requested_qty'],filled_avg_price=1.2);self.b.pos={};self.e.sync(t('10:13'));self.assertEqual(o['state'],'CLOSED');self.assertAlmostEqual(o['actual_option_pnl_dollars'],100.)
    def test_shared_contract_blocks_exit(self):
        o=self.filled();self.e.positions[o['contract']]+=1
        with self.assertRaisesRegex(RuntimeError,'SHARED_CONTRACT'):self.e.exit(o,'STOP',t('10:12'))
    def test_early_close(self):
        o=self.filled();self.e.manage(t('12:45'),t('13:00'));self.assertEqual(len(self.b.sells),1)
    def test_paper_enforced(self):
        self.b.paper=False
        with self.assertRaises(ValueError):bot.HeroEngine(self.b,self.temp.name)
    def test_dashboard_matches_state(self):
        self.filled();self.e.publish(t('10:12'));data=dashboard.load_snapshot(Path(self.temp.name)/'bot_telemetry.json');self.assertEqual(data['orders'],self.e.state['orders']);self.assertEqual(data['snapshots']['SPY']['stage'],'FILLED')
    def test_dashboard_no_trading_import(self):
        tree=ast.parse(Path(dashboard.__file__).read_text());imports=[ast.unparse(n) for n in ast.walk(tree) if isinstance(n,(ast.Import,ast.ImportFrom))]
        self.assertFalse(any('research_momentum_bot' in x or 'alpaca' in x or 'market_mechanics' in x for x in imports))
    def test_corrupt_state_fails(self):
        self.e.path.write_text('{broken')
        with self.assertRaises(ValueError):bot.HeroEngine(self.b,self.temp.name)

class LearnTests(unittest.TestCase):
    def path(self):
        c=candidate();idx=pd.date_range(t('10:10'),t('15:59'),freq='1min');df=pd.DataFrame([candle(108.5,107.5,108,108)]*len(idx),index=idx)
        rec=lt.candidate_record(c,feat(),final_state='SHADOW',reason_code='TEST');return rec,df
    def test_ambiguous_stop_target(self):
        r,df=self.path();df.iloc[0]=candle(120,90,108,108);out=lt.resolve_candidate_path(r,df,as_of=t('16:05'),session_close=t('16:00'));self.assertTrue(out['path_ambiguous']);self.assertIsNone(out['underlying_result_r'])
    def test_missing_path_no_tail_fallback(self):
        r,df=self.path();df.index+=pd.Timedelta(days=1);out=lt.resolve_candidate_path(r,df,as_of=t('16:05'),session_close=t('16:00'));self.assertFalse(out['resolved'])
    def test_horizons_continue_after_target(self):
        r,df=self.path();df.iloc[0]=candle(108,104,105,108);out=lt.resolve_candidate_path(r,df,as_of=t('16:05'),session_close=t('16:00'));self.assertIsNotNone(out['returns_r']['60']);self.assertTrue(out['paths']['MIDPOINT']['hit_before_stop'])
    def test_not_resolved_before_eod(self):
        r,df=self.path();self.assertFalse(lt.resolve_candidate_path(r,df,as_of=t('12:00'),session_close=t('16:00'))['resolved'])
    def test_candidate_stop_exact(self):
        r,_=self.path();self.assertEqual(r['candidate']['initial_r'],abs(r['candidate']['entry_spot']-r['candidate']['stop']))
    def test_immutable(self):
        r,df=self.path();before=copy.deepcopy(r);lt.resolve_candidate_path(r,df,as_of=t('16:05'),session_close=t('16:00'));self.assertEqual(r,before)

class OptionTests(unittest.TestCase):
    def sample(self):
        c=NS(symbol='TEST',expiration_date=t('10:10').date()+pd.Timedelta(days=2),strike_price=110,open_interest=1000,size=100,tradable=True)
        s=NS(latest_quote=NS(timestamp=t('10:10'),bid_price=1,ask_price=1.04),greeks=NS(delta=-.65,gamma=.01,theta=-.1,vega=.2),implied_volatility=.2)
        return c,s
    def test_broker_greeks(self):
        c,s=self.sample();self.assertEqual(oe.evaluate_snapshot(c,s,'PUT',t('10:10'))['delta'],-.65)
    def test_missing_timestamp_blocks(self):
        c,s=self.sample();s.latest_quote.timestamp=None;self.assertIsNone(oe.evaluate_snapshot(c,s,'PUT',t('10:10')))
    def test_future_quote_blocks(self):
        c,s=self.sample();s.latest_quote.timestamp=t('10:11');self.assertIsNone(oe.evaluate_snapshot(c,s,'PUT',t('10:10')))
    def test_missing_greeks_blocks(self):
        c,s=self.sample();s.greeks=None;self.assertIsNone(oe.evaluate_snapshot(c,s,'PUT',t('10:10')))
    def test_adjusted_contract_blocks(self):
        c,s=self.sample();c.size=10;self.assertIsNone(oe.evaluate_snapshot(c,s,'PUT',t('10:10')))

if __name__=='__main__':unittest.main()
