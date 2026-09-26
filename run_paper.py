"""QQQ paper executor. --check is read-only. --run --paper-orders enables simulated orders.
No live trading host, live switch, account balances in telemetry, or secret logging.
"""
import argparse,hashlib,json,os,time,threading,fcntl,signal
from pathlib import Path
from datetime import datetime,timedelta
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv
from hero import HeroCallExecutor
from bear import BearPutExecutor
import vic
from paper_broker import PaperBroker,BrokerError,num,whole,valid_quote
from execution_data import build_inputs,session_time

BASE=Path(__file__).resolve().parent
TERMINAL={'filled','canceled','expired','rejected'}
ACTIVE={'new','accepted','pending_new','partially_filled','pending_cancel','accepted_for_bidding','stopped','suspended','calculated','done_for_day','pending_replace'}


def now():return datetime.now(vic.ET)


def safe_error(exc):
    # Never print HTTP bodies, credential-bearing objects, account responses or stack locals.
    return str(exc) if isinstance(exc,(BrokerError,ValueError)) else type(exc).__name__


class Engine:
    def __init__(self,broker,base=BASE,qty=1,premium_cap=500,daily_loss=100,max_entries=3):
        self.b=broker;self.base=Path(base);self.path=self.base/'paper_execution_state.json'
        self.qty=whole(qty);self.cap=num(premium_cap);self.loss=num(daily_loss);self.max_entries=whole(max_entries)
        if not 1<=self.qty<=2 or not 0<self.cap<=1000 or not 0<self.loss<=1000 or not 1<=self.max_entries<=10:
            raise ValueError('Invalid paper test limits')
        if self.path.exists():
            self.s=json.loads(self.path.read_text())
            if self.s.get('version')!=1 or self.s.get('mode')!='PAPER':raise ValueError('Invalid execution state; do not delete it to bypass recovery')
        else:self.s={'version':1,'mode':'PAPER','account_hash':None,'orders':{},'trade':None,'rules':{},'day':{},'activities':[],'halt':None}
        self.rules={'hero':HeroCallExecutor(state=self.s['rules'].get('hero')),'bear':BearPutExecutor(state=self.s['rules'].get('bear'))}
        self.decisions={};self.health='STARTING';self.message='Starting paper executor';self.values={};self.last_positions=[]
        self.calendar=[];self.clock={};self.calendar_day=None;self.clock_at=None
        self.data_at=0;self.raw_inputs=None;self.pool=ThreadPoolExecutor(max_workers=2);self.data_future=None;self.macro_future=None
        self.macro_at=0;self.context=None;self.vix={};self.latest_report=None
        self.save()

    def save(self):
        self.s['rules']={k:r.export_state() for k,r in self.rules.items()}
        vic.atomic_json(self.path,self.s)

    def bind(self):
        account=self.b.account()
        identity=hashlib.sha256(str(account['id']).encode()).hexdigest()
        if self.s['account_hash'] not in (None,identity):raise ValueError('State belongs to another paper account')
        self.s['account_hash']=identity;self.save()
        return account

    def activity(self,owner,kind,symbol,qty=0,price=0,status=''):
        self.s['activities'].append({'owner':owner,'timestamp':now().isoformat(),'type':kind,'symbol':symbol,'qty':qty,'price':price,'status':status})
        self.s['activities']=self.s['activities'][-500:]

    def submit(self,owner,purpose,symbol,qty,price=None,signal_id=None):
        if any(o['status'] not in TERMINAL for o in self.s['orders'].values()):raise ValueError('An order is already unresolved')
        seq=len(self.s['orders'])
        cid='vtp-'+owner+'-'+hashlib.sha256(f'{self.s["account_hash"]}:{signal_id}:{symbol}:{purpose}:{seq}'.encode()).hexdigest()[:24]
        payload={'symbol':symbol,'qty':str(whole(qty)),'side':'buy' if purpose=='ENTRY' else 'sell',
                 'position_intent':'buy_to_open' if purpose=='ENTRY' else 'sell_to_close','time_in_force':'day',
                 'type':'limit' if price is not None else 'market','client_order_id':cid}
        if price is not None:payload['limit_price']=str(price)
        order={'owner':owner,'purpose':purpose,'payload':payload,'status':'INTENT','filled_qty':0,'filled_avg_price':None,
               'created_at':now().isoformat(),'registered':False,'accounted':0,'accounted_value':0}
        if purpose=='ENTRY':
            order['entry_plan']={k:self.decisions.get(owner,{}).get(k) for k in ('stop_price','target_level','setup_bar_end','room_r')}
        self.s['orders'][cid]=order
        if purpose=='ENTRY':self.rules[owner].mark_entry_submitted(signal_id)
        self.save()  # Submission intent survives a crash before/after POST. Never blind POST retries.
        try:
            result=self.b.submit(payload)
            order['broker_id']=result['id']
        except Exception:
            order['status']='UNKNOWN';self.save();raise
        self.apply_order(cid,result)

    def apply_order(self,cid,result):
        o=self.s['orders'][cid];p=o['payload']
        if result.get('client_order_id')!=cid or result.get('symbol')!=p['symbol'] or result.get('side')!=p['side'] or whole(result['qty'])!=whole(p['qty']):
            raise ValueError('Broker order identity mismatch')
        count=whole(result.get('filled_qty',0))
        if not o['filled_qty']<=count<=whole(p['qty']):raise ValueError('Inconsistent cumulative order fills')
        status=result['status']
        if status not in TERMINAL|ACTIVE:raise ValueError('Unsupported broker order state: '+str(status))
        avg=num(result['filled_avg_price']) if count else None
        if count and avg<=0:raise ValueError('Invalid average fill')
        if status=='filled' and count!=whole(p['qty']):raise ValueError('Filled order quantity mismatch')
        o.update(status=status,filled_qty=count,filled_avg_price=avg,broker_id=result['id'])
        owner=o['owner'];rule=self.rules[owner]
        if o['purpose']=='ENTRY' and status in TERMINAL and not o['registered']:
            if count:
                if self.s['trade']:raise ValueError('Multiple simultaneous entry fills')
                rule.register_position(cid,count,avg)
                plan=o.get('entry_plan',{})
                if plan.get('stop_price') is not None:rule.state['positions'][cid].update(plan)
                self.s['trade']={'owner':owner,'symbol':p['symbol'],'position_id':cid,'entry_date':o['created_at'][:10]}
                day=o['created_at'][:10];bucket=self.s['day'].setdefault(day,{'entries':0,'pnl':0})
                bucket['entries']+=1
                self.activity(owner,'ENTRY_FILLED',p['symbol'],count,avg,status)
            o['registered']=True
        elif o['purpose']!='ENTRY' and count:
            trade=self.s['trade']
            if not trade or trade['owner']!=owner:raise ValueError('Exit has no matching owned trade')
            pos=rule.state['positions'][trade['position_id']]
            delta=count-o['accounted'];value=count*avg
            # Cumulative VWAP correction is included even if quantity does not change.
            pnl=(value-o['accounted_value']-delta*pos['entry_price'])*100
            day=str(now().date());bucket=self.s['day'].setdefault(day,{'entries':0,'pnl':0});bucket['pnl']+=pnl
            rule.confirm_exit_fill(trade['position_id'],cid,count,o['purpose'])
            if delta:self.activity(owner,'EXIT_FILLED',p['symbol'],delta,avg,status)
            o['accounted']=count;o['accounted_value']=value
            if pos['remaining_qty']==0:
                if status not in TERMINAL:raise ValueError('Zero position while exit remains active')
                self.s['trade']=None
        self.save()

    def reconcile(self):
        for cid,o in self.s['orders'].items():
            if o['status'] in TERMINAL:continue
            try:r=self.b.get_order(cid)
            except BrokerError as exc:
                if exc.status==404:raise ValueError('Uncertain submission: client order ID not found. No automatic retry; inspect paper account and state.') from None
                raise
            self.apply_order(cid,r)
        positions=self.b.positions();opened=self.b.open_orders();self.last_positions=positions
        known=set(self.s['orders'])
        for o in opened:
            if str(o.get('symbol','')).startswith('QQQ') and o.get('client_order_id') not in known:
                raise ValueError('Unmanaged QQQ order detected; no automated actions until reconciled')
        expected={}
        trade=self.s['trade']
        if trade:
            p=self.rules[trade['owner']].state['positions'][trade['position_id']]
            expected[trade['symbol']]=p['remaining_qty']
        for o in self.s['orders'].values():
            if o['purpose']=='ENTRY' and not o['registered'] and o['filled_qty']:
                expected[o['payload']['symbol']]=o['filled_qty']
        actual={p['symbol']:whole(p['qty']) for p in positions if str(p['symbol']).startswith('QQQ')}
        if actual!={s:q for s,q in expected.items() if q}:raise ValueError('QQQ positions differ from owned fills; possible external trade or fill race. Retrying reconciliation; no new orders.')

    def cancel_active(self,entry_only=False):
        for o in self.s['orders'].values():
            if o['status'] in TERMINAL or (entry_only and o['purpose']!='ENTRY'):continue
            if not o.get('broker_id'):raise ValueError('Unknown submission must be reconciled before cancel')
            try:self.b.cancel(o['broker_id'])
            except BrokerError as exc:
                if exc.status not in {404,422}:raise
            # Cancellation requested does not mean canceled. Next reconcile determines final fills.

    def publish(self):
        for owner in self.rules:
            orders=[]
            for cid,o in self.s['orders'].items():
                if o['owner']!=owner:continue
                p=o['payload'];orders.append({'ticker':'QQQ','symbol':p['symbol'],'side':p['position_intent'],
                     'status':o['status'],'qty':whole(p['qty']),'filled_qty':o['filled_qty'],'avg_fill_price':o['filled_avg_price'],
                     'submitted_at':o['created_at'],'updated_at':now().isoformat(),'owned_qty':0,'client_order_id':cid})
            trade=self.s['trade'];positions=[]
            if trade and trade['owner']==owner:
                pos=self.rules[owner].state['positions'][trade['position_id']]
                positions=[{'symbol':trade['symbol'],'qty':pos['remaining_qty'],'side':'long','avg_entry_price':pos['entry_price']}]
                for o in orders:
                    if o['client_order_id']==trade['position_id']:o['owned_qty']=pos['remaining_qty']
            for cid,o in self.s['orders'].items():
                if o['owner']==owner and o['purpose']=='ENTRY' and not o['registered'] and o['filled_qty']:
                    positions.append({'symbol':o['payload']['symbol'],'qty':o['filled_qty'],'side':'long','avg_entry_price':o['filled_avg_price']})
                    for row in orders:
                        if row['client_order_id']==cid:row['owned_qty']=o['filled_qty']
            vic.atomic_json(self.base/(owner+'_telemetry.json'),{'heartbeat':now().isoformat(),'paper':True,'health':self.health,
               'message':self.message,'stock_feed':self.b.stock_feed,'option_feed':self.b.option_feed,
               'decision':self.decisions.get(owner),'strategy':'BB_EMA_STRUCTURE_V1','structure':self.values.get('structure'),'orders':orders[-100:],'positions':positions,
               'activities':[{k:v for k,v in a.items() if k!='owner'} for a in self.s['activities'] if a['owner']==owner][-100:]})

    def refresh_session(self):
        t=now()
        if self.clock_at is None or (t-self.clock_at).total_seconds()>=10:
            self.clock=self.b.clock();self.clock_at=now()
            if abs((self.clock_at-vic.stamp(self.clock['timestamp'])).total_seconds())>10:raise ValueError('Broker/local clock mismatch')
        if self.calendar_day!=t.date():
            self.calendar=self.b.calendar(t.date()-timedelta(days=45),t.date()+timedelta(days=3));self.calendar_day=t.date()
        today=next((r for r in self.calendar if r['date']==str(t.date())),None)
        if not today:return False,None
        opening,closing=session_time(today['date'],today['open']),session_time(today['date'],today['close'])
        return bool(self.clock.get('is_open')) and opening<=t<closing,closing

    def background(self):
        t=now()
        if self.data_future and self.data_future.done():
            try:self.raw_inputs=self.data_future.result()
            finally:self.data_future=None
        if self.macro_future and self.macro_future.done():
            try:self.context,self.vix=self.macro_future.result()
            finally:self.macro_future=None
        if self.data_future is None and time.monotonic()-self.data_at>=15:
            self.data_at=time.monotonic()
            self.data_future=self.pool.submit(self.b.bars,['QQQ'],t-timedelta(days=40),t)
        if self.macro_future is None and time.monotonic()-self.macro_at>=30:
            self.macro_at=time.monotonic()
            self.macro_future=self.pool.submit(lambda:(vic.collect_context(),vic.market_snapshot()))

    def tick(self):
        self.reconcile()  # Actual fills/positions first. No new trade on uncertain ownership.
        is_open,closing=self.refresh_session();t=now()
        flatten=(self.base/'FLATTEN_AND_PAUSE').exists() or (closing is not None and t>=closing-timedelta(minutes=15))
        paused=(self.base/'PAUSE_ENTRIES').exists() or (self.base/'FLATTEN_AND_PAUSE').exists()
        active=[o for o in self.s['orders'].values() if o['status'] not in TERMINAL]
        # Cancel entry remainder on any partial fill; manage the position after terminal confirmation.
        for o in active:
            if o['purpose']=='ENTRY' and (o['filled_qty'] or flatten or paused or not is_open or (t-vic.stamp(o['created_at'])).total_seconds()>=20):
                self.cancel_active(entry_only=True)
        if not is_open:
            self.health='MARKET_CLOSED';self.message='Paper executor waiting for regular session'
            if self.s['trade']:self.message='Market closed with an owned position; inspect paper account. No after-hours order submitted.'
            return
        data_error=None
        try:self.background()
        except Exception as exc:data_error=safe_error(exc)
        values={};statuses={};bars=[]
        if self.raw_inputs:
            try:values,statuses,bars=build_inputs(self.raw_inputs,self.calendar,t)
            except Exception as exc:data_error=safe_error(exc)
        self.values=values
        try:
            report=vic.VicRiskManager().evaluate(self.context or {},{**self.vix,'qqq_bars':bars},now())
        except Exception:
            report={'permission':{'light':'RED','checked_at':t.isoformat(),'valid_until':t.isoformat()},'briefing':'VIC evaluation unavailable; new entries blocked'}
        self.latest_report=report
        try:vic.atomic_json(self.base/'vic_telemetry.json',report)
        except OSError:pass  # Reporting failure must not veto evaluable exits.
        values['vic_permission']=report['permission']
        trade=self.s['trade']
        if trade:
            owner=trade['owner'];rule=self.rules[owner];pos=rule.state['positions'][trade['position_id']]
            # Exits do not depend on VIC, macro feeds, MAG7, RSI, or entry permission.
            forced=flatten or trade['entry_date']!=str(t.date())
            try:
                quote=self.b.quotes([trade['symbol']])[trade['symbol']];bid,_=valid_quote(quote,now())
                exit_data={**values,'option_bid':bid,'option_quote_timestamp':quote['t'],'force_exit':forced}
            except Exception:
                exit_data={**values,'force_exit':forced};bid=None
            # Permit risk/flatten to cancel an outstanding scale order, then wait for terminal fills.
            action=rule.evaluate_exit(trade['position_id'],exit_data,now());self.save();self.decisions[owner]=action
            if active:
                if action['action']=='CLOSE_ALL' and any(o['purpose']=='SCALE_OUT_50' for o in active):self.cancel_active()
                elif any(o['purpose']=='SCALE_OUT_50' and (t-vic.stamp(o['created_at'])).total_seconds()>20 for o in active):self.cancel_active()
                self.health='ORDER_PENDING';self.message='Waiting for terminal order confirmation';return
            if action['action'] in {'CLOSE_ALL','SCALE_OUT_50'}:
                price=f'{bid:.2f}' if action['action']=='SCALE_OUT_50' and bid else None
                self.submit(owner,action['action'],trade['symbol'],action['quantity'],price)
            self.health='MANAGING_POSITION' if action['action']!='DATA_UNAVAILABLE' else 'EXIT_DATA_UNAVAILABLE'
            self.message=action['reason'];return
        if active:self.health='ORDER_PENDING';self.message='Entry awaiting fill/cancel confirmation';return
        day=self.s['day'].get(str(t.date()),{'entries':0,'pnl':0})
        cutoff=min(t.replace(hour=15,minute=0,second=0,microsecond=0),closing-timedelta(minutes=30))
        if paused or flatten or t>=cutoff or day['pnl']<=-self.loss or day['entries']>=self.max_entries:
            self.health='ENTRY_PAUSED';self.message='Pause flag, entry cutoff, daily loss or daily entry limit';return
        self.health='SCANNING';self.message=data_error or report['briefing']
        for owner,rule in self.rules.items():
            decision=rule.evaluate_entry(values,statuses,now());self.decisions[owner]=decision
            if decision['action'] not in {'BUY_CALL_SIGNAL','BUY_PUT_SIGNAL'}:continue
            account=self.bind()
            if account.get('status')!='ACTIVE' or account.get('trading_blocked') or account.get('trade_suspended_by_user') or int(account.get('options_trading_level',0))<2:
                raise ValueError('Paper account inactive, blocked or lacks long-option permission')
            symbol,limit,quote=self.b.choose_contract('call' if owner=='hero' else 'put',values['price_close'],now(),self.cap,self.qty)
            if num(account.get('options_buying_power',0))<float(limit)*100*self.qty:raise ValueError('Insufficient paper options buying power')
            # Re-check time-sensitive authorization after account/contract API calls.
            if rule.evaluate_entry(values,statuses,now())['action']!=decision['action']:return
            valid_quote(quote,now(),entry=True)
            if now()>=cutoff:return
            self.submit(owner,'ENTRY',symbol,self.qty,limit,decision['signal_id']);break


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    group=parser.add_mutually_exclusive_group(required=True);group.add_argument('--check',action='store_true');group.add_argument('--run',action='store_true')
    parser.add_argument('--paper-orders',action='store_true');args=parser.parse_args()
    load_dotenv(BASE/'.env',override=False)
    # No accidental live-host configuration silently interpreted as paper.
    for key in ('APCA_API_BASE_URL','ALPACA_BASE_URL'):
        if os.getenv(key) and os.environ[key].rstrip('/') not in {'https://paper-api.alpaca.markets','https://paper-api.alpaca.markets/v2'}:
            parser.error(key+' must point to Alpaca paper; live endpoints are unsupported')
    if args.run and not args.paper_orders:parser.error('--run requires --paper-orders for simulated orders')
    with (BASE/'paper_executor.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:parser.error('Another paper executor is already running in this folder')
        broker=PaperBroker()
        engine=Engine(broker,qty=int(os.getenv('PAPER_CONTRACTS','1')),premium_cap=float(os.getenv('PAPER_MAX_PREMIUM','500')),
                      daily_loss=float(os.getenv('PAPER_DAILY_LOSS','100')),max_entries=int(os.getenv('PAPER_MAX_ENTRIES','3')))
        try:
            account=engine.bind();engine.reconcile();opened,closing=engine.refresh_session()
            print('PAPER account connection OK; status:',account.get('status'),'options level:',account.get('options_trading_level'),flush=True)
            print('Feeds:',broker.stock_feed,'/',broker.option_feed,'| Market open:',opened,flush=True)
            if args.check:
                if account.get('status')!='ACTIVE' or account.get('trading_blocked') or account.get('trade_suspended_by_user') or int(account.get('options_trading_level',0))<2:
                    raise ValueError('Paper account cannot open long options')
                history=broker.bars(['QQQ'],now()-timedelta(days=40),now())
                if not history.get('QQQ'):raise ValueError('No historical QQQ candles returned')
                values,_,_=build_inputs(history,engine.calendar,now())
                layer=values['structure']
                print('Strategy data OK; complete prior sessions:',layer['completed_sessions'],'structure zones:',len(layer['zones']))
                if layer['completed_sessions']<5 or layer['daily_sd'] is None:raise ValueError('Need all five most recent complete prior QQQ sessions')
                context=vic.collect_context();snapshot=vic.market_snapshot()
                report=vic.VicRiskManager().evaluate(context,snapshot,now())
                print('VIC current light:',report['permission']['light'],'|',report['briefing'])
                contracts=broker.request('GET','/v2/options/contracts',{'underlying_symbols':'QQQ','status':'active','type':'call',
                    'expiration_date_gte':str(now().date()+timedelta(days=1)),'expiration_date_lte':str(now().date()+timedelta(days=7)),'limit':1})
                listed=contracts.get('option_contracts',[])
                if not listed:raise ValueError('No QQQ option contracts returned')
                quote=broker.quotes([listed[0]['symbol']])
                if not quote:raise ValueError('Options quote feed returned no data')
                print('QQQ historical bars, options contracts and options quote endpoint responded. Quote freshness not certified outside market hours.')
                print('READ-ONLY broker check finished. No orders submitted. Market-hour quotes, signals and complete fills/exits still require a paper-session test.')
                return
            print('PAPER ORDERS ENABLED. VIC + HERO + BEAR are managed here. Keep Mac awake. No live-money endpoint.',flush=True)
            stop=threading.Event()
            signal.signal(signal.SIGTERM,lambda *_:stop.set());signal.signal(signal.SIGINT,lambda *_:stop.set())
            while not stop.is_set():
                try:engine.tick()
                except Exception as exc:engine.health='ATTENTION';engine.message=safe_error(exc)
                engine.publish();print(now().isoformat(),engine.health,engine.message,flush=True)
                stop.wait(3)
            try:engine.cancel_active(entry_only=True)
            except Exception:pass
            engine.health='STOPPED';engine.message='Executor stopped. Entry cancellation requested; verify all orders/positions directly in Alpaca paper. Exits are no longer monitored.';engine.publish()
            print(engine.message,flush=True)
        finally:engine.pool.shutdown(wait=False,cancel_futures=True)


if __name__=='__main__':
    try:main()
    except Exception as exc:raise SystemExit('Paper executor: '+safe_error(exc)) from None
