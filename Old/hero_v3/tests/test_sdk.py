"""Real SDK model construction; network is mocked. Optional dependency required."""
import unittest,importlib.util
from unittest.mock import Mock,patch
from types import SimpleNamespace as NS
from datetime import datetime
from zoneinfo import ZoneInfo
import research_momentum_bot as bot
import option_engine as oe

HAS_SDK=importlib.util.find_spec('alpaca') is not None
@unittest.skipUnless(HAS_SDK,'Install requirements.txt to run real SDK adapter tests')
class SDKTests(unittest.TestCase):
    def broker(self):
        b=bot.PaperBroker.__new__(bot.PaperBroker);b.paper=True;b.trading=Mock();b.options=Mock();return b
    def test_buy_order_model(self):
        b=self.broker();b.order_data=lambda x:x
        b.buy('SPY260925P00110000',1,1,'HERO-test')
        r=b.trading.submit_order.call_args.args[0]
        self.assertEqual(r.position_intent.value,'buy_to_open');self.assertEqual(r.type.value,'limit')
    def test_sell_order_model(self):
        b=self.broker();b.order_data=lambda x:x;b.sell('SPY260925P00110000',1,'HERO-exit')
        r=b.trading.submit_order.call_args.args[0];self.assertEqual(r.position_intent.value,'sell_to_close')
    def test_calendar_sdk_normalization(self):
        from alpaca.trading.models import Calendar
        b=self.broker();b.trading.get_calendar.return_value=[Calendar(date='2026-09-23',open='09:30',close='16:00')]
        result=b.calendar(datetime(2026,9,23,tzinfo=ZoneInfo('America/New_York')))
        self.assertEqual(result[0]['open'],'2026-09-23T09:30:00-04:00')
    def test_options_buying_power(self):
        b=self.broker();b.trading.get_account.return_value=NS(trading_blocked=False,account_blocked=False,equity='100',options_buying_power='25',buying_power='400',cash='50')
        self.assertEqual(b.account()['buying_power'],25)
    def test_selection_pagination(self):
        now=datetime.now(ZoneInfo('America/New_York'));b=self.broker()
        b.trading.get_option_contracts.side_effect=[NS(option_contracts=[],next_page_token='p2'),NS(option_contracts=[],next_page_token=None)]
        self.assertIsNone(oe.select_contract(b.trading,b.options,'SPY',100,'PUT',now))
        self.assertEqual(b.trading.get_option_contracts.call_count,2)
        self.assertEqual(b.trading.get_option_contracts.call_args.args[0].page_token,'p2')
    def test_paper_client_hardcoded(self):
        with patch.dict('os.environ',{'APCA_API_KEY_ID':'offline_dummy','APCA_API_SECRET_KEY':'offline_dummy'}),patch('dotenv.load_dotenv'),patch('alpaca.trading.client.TradingClient') as tc,patch('alpaca.data.historical.option.OptionHistoricalDataClient'),patch('alpaca.data.historical.stock.StockHistoricalDataClient'):
            bot.PaperBroker();self.assertIs(tc.call_args.kwargs['paper'],True)
