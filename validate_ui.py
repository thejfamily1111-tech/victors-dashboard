from pathlib import Path
from streamlit.testing.v1 import AppTest
import os
os.environ['DASHBOARD_PIN']='test-only'
a=AppTest.from_file(str(Path(__file__).with_name('dashboard.py').resolve())).run(timeout=30)
assert not a.exception,[e.message for e in a.exception]
assert not a.metric and any('Passcode' in x.label for x in a.text_input)
script='''
import sys,types
import dashboard as d
import dashboard_views as v
from test_dashboard_refresh import fixture,T
import pandas as pd
class Clock:
    @staticmethod
    def now(tz):return T
d.datetime=Clock
d.load_status=lambda n:({'teams':[fixture()]},None,'offline test') if n=='teams' else (None,None,None)
d.vic_dashboard_report=lambda *args:{'events':[],'calendar_errors':[]}
d.financial_panel=lambda s:None
d.fund_sections=lambda *a:None
d.rule_panel=lambda *a:None
d.vic_module=lambda:types.SimpleNamespace(fetch_news=lambda:{'items':[]})
sys.modules['simulation_lab']=types.SimpleNamespace(render=lambda:None)
index=pd.date_range('2026-10-05 09:30',periods=78,freq='5min',tz=T.tzinfo).append(pd.date_range('2026-10-06 09:30',periods=30,freq='5min',tz=T.tzinfo))
raw=pd.DataFrame({'Open':600.,'High':601.,'Low':599.,'Close':600.5,'Volume':10000.},index=index)
d.fetch_bars=lambda *a:raw
v.public_market=lambda *a:{}
v.treasury=lambda:{}
v.earnings=lambda:[]
v.render(d,False)
'''
a=AppTest.from_string(script).run(timeout=30)
assert not a.exception,[(e.message,e.stack_trace) for e in a.exception]
assert {'Overview','Teams & activity','News & events','Research'}.issubset({t.label for t in a.tabs})
assert len(a.button)==17
assert {x.label:x.value for x in a.toggle}=={'BBands':True,'RSI':True,'Volume':True,'EMA9':False,'EMA21':False,'VWAP':False}
a.button[2].click().run(timeout=30)
assert not a.exception,[(e.message,e.stack_trace) for e in a.exception]
assert a.session_state['team_detail']=='team3'
a.selectbox[0].select(60).run(timeout=30)
assert not a.exception,[e.message for e in a.exception]
print('PASS: PIN boundary; four tabs; missing feeds; team selection; 60m chart; indicator defaults')
import dashboard as d
from test_dashboard_refresh import T
exec(script.split('v.render')[0],globals())
frame=d.prepare_bars(raw,T)
fig=d.chart_figure(frame,1)
assert {'RSI 14','Volume','BB UPPER'}.issubset({t.name for t in fig.data})
assert len(d.chart_figure(frame,1,False,False,'QQQ',False,False).data)==1
print('PASS: RSI and volume on separate shared-axis panels; disabling indicators leaves candle trace')
