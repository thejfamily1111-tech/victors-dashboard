import unittest
from beta_panel.views import research_progress


class ResearchProgressTests(unittest.TestCase):
    def test_failed_round_is_not_success_and_research_watch_is_completed(self):
        scan = dict(round_complete=True, round_started_at='2026-10-12T10:00:00Z',
                    completed_at='2026-10-12T11:00:00Z',
                    finalists_attempted=['A', 'B', 'C', 'D'],
                    finalists_analyzed=['D'], finalists_pending=['A', 'B', 'C'])
        rows = [dict(symbol='A', failure_stage='ai_analysis'),
                dict(symbol='B', research_status='insufficient'),
                dict(symbol='C', failure_stage='option_metadata'),
                dict(symbol='D', research_status='insufficient')]
        for row in rows:
            row['as_of'] = '2026-10-12T06:30:00-04:00'
        result = research_progress(scan, rows)
        self.assertEqual((result['completed'], result['total'], result['pending']), (1, 4, 3))
        self.assertEqual(result['counts'], {'AI analysis errors': 1, 'Missing data or context': 1,
                                          'Unsuitable option metadata': 1, 'Other pending research': 0})
        rows[0]['as_of'] = '2026-10-12T12:00:00Z'
        self.assertEqual(research_progress(scan, rows)['counts']['Other pending research'], 1)

    def test_unknown_or_in_progress_round_is_not_invented(self):
        for scan in ({}, {'round_complete': True}, {'round_complete': False}):
            self.assertIsNone(research_progress(scan, []))

    def test_zero_research_warning_renders_with_existing_tabs(self):
        from streamlit.testing.v1 import AppTest
        from beta_panel.snapshot import CONFIG, SECTIONS, OBJECTS
        raw = dict(config=CONFIG, runtime={}, **{k: [] for k in SECTIONS}, **{k: {} for k in OBJECTS})
        raw['scan'] = dict(round_complete=True, finalists_attempted=['AAPL', 'NVDA'],
                           finalists_analyzed=[], finalists_pending=['AAPL', 'NVDA'])
        def app(snapshot):
            from beta_panel.ui import render
            render(snapshot)
        result = AppTest.from_function(app, args=(raw,)).run(timeout=30)
        self.assertFalse(result.exception)
        self.assertTrue(any('AI research completed: 0/2' in row.value for row in result.warning))
        self.assertEqual([tab.label for tab in result.tabs], ['Overview', 'Research', 'Positions', 'Activity'])


if __name__ == '__main__':
    unittest.main()
