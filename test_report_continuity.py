from copy import deepcopy
import unittest
from report_continuity import retain_report


class ContinuityTests(unittest.TestCase):
    def setUp(self):
        self.state = {}
        self.report = {'received_at': '2026-10-13T14:00:00Z', 'snapshot': {
            'observed_at': '2026-10-13T14:00:00Z',
            'teams': [{'team_id': 'team1', 'heartbeat': '2026-10-13T14:00:00Z'}],
            'beta': {'observed_at': '2026-10-13T13:00:00Z'}}}
        retain_report(self.state, 'account-a', lambda: self.report)

    def test_failure_keeps_complete_snapshot_and_original_timestamps(self):
        def fail(): raise OSError('private provider text')
        retained = retain_report(self.state, 'account-a', fail)
        self.assertEqual(retained, self.report)
        self.assertIn('unconfirmed', self.state['warning'])
        self.assertNotIn('private', self.state['warning'])
        retained['snapshot']['teams'].clear()
        self.assertEqual(self.state['report'], self.report)

    def test_empty_team_upload_does_not_erase_portfolio(self):
        broken = deepcopy(self.report)
        broken['snapshot']['teams'] = []
        self.assertEqual(retain_report(self.state, 'account-a', lambda: broken), self.report)
        self.assertIsNotNone(self.state['warning'])

    def test_recovery_clears_warning_and_accepts_closed_positions(self):
        retain_report(self.state, 'account-a', lambda: None)
        recovered = deepcopy(self.report)
        recovered['snapshot']['teams'][0]['positions'] = []
        recovered['snapshot']['observed_at'] = '2026-10-13T14:01:00Z'
        self.assertEqual(retain_report(self.state, 'account-a', lambda: recovered), recovered)
        self.assertIsNone(self.state['warning'])

    def test_source_change_never_displays_previous_accounts_data(self):
        self.assertIsNone(retain_report(self.state, 'account-b', lambda: None))
        self.assertNotIn('report', self.state)
