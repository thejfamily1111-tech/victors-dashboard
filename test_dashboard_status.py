import io
import unittest
from unittest.mock import patch
import pandas as pd
from dashboard_status import fetch_treasury,select_research,research_status,ai_schedule_lines

NOW=pd.Timestamp('2026-10-10T16:30:00-04:00')
class DashboardStatusTests(unittest.TestCase):
    def test_independent_series_and_missing_daily_values(self):
        def opener(request,**kwargs):
            if 'id=DGS2&' in request.full_url:raise TimeoutError()
            self.assertIn('id=DGS10&',request.full_url)
            return io.BytesIO(b'observation_date,DGS10\n2026-10-08,4.1\n2026-10-09,4.2\n2026-10-10,.\n')
        result=fetch_treasury(NOW,opener)
        self.assertAlmostEqual(result['DGS10']['change']*100,10)
        self.assertEqual(result['DGS10']['date'],'2026-10-09')
        self.assertEqual(result['DGS2']['error'],'TimeoutError')
    def test_old_or_truncated_response_is_not_a_current_yield(self):
        for payload in (b'observation_date,DGS10\n1976-06-01,7.0\n', b'x'*2_000_001):
            result=fetch_treasury(NOW,lambda *a,**k:io.BytesIO(payload))
            self.assertNotIn('value',result['DGS10'])
            self.assertIn('error',result['DGS10'])
    def test_new_session_monitor_wins_over_old_brief(self):
        monitor={'session_date':'2026-10-12','slot':'MONITOR'}
        self.assertEqual(select_research({'brief':{'session_date':'2026-10-09'},'monitor':monitor}),monitor)
        self.assertIn('Collecting preview',research_status(monitor,NOW))
    def test_active_expired_missing_timestamp(self):
        b={'session_date':'2026-10-10','slot':'0915','status':'READY','issued_at':'2026-10-10T16:00:00-04:00','valid_until':'2026-10-10T17:00:00-04:00'}
        self.assertEqual(research_status(b,NOW),'Active morning context')
        self.assertIn('Expired',research_status(b,NOW+pd.Timedelta(hours=1)))
        b['valid_until']=None
        self.assertIn('unavailable',research_status(b,NOW))
    def test_weekend_next_window_and_no_fabricated_success(self):
        lines=ai_schedule_lines({}, {'session_open':'2026-10-12T09:30:00-04:00','ai':{'status':'NOT_REQUESTED'}},NOW)
        self.assertIn('Oct 12, 2026 09:12 AM EDT',' '.join(lines))
        self.assertIn('not recorded',' '.join(lines))
    def test_unstamped_quotes_hidden(self):
        import dashboard_views
        with patch('yfinance.Ticker') as ticker:
            ticker.return_value.get_info.return_value={'regularMarketPrice':751.27,'bid':717.24,'ask':717.49}
            q=dashboard_views.quote_one('QQQ')
        self.assertIsNone(q['bid']);self.assertIsNone(q['ask']);self.assertIsNone(q['spread'])

if __name__=='__main__':unittest.main()
