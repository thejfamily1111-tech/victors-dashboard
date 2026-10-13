from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from operations_panel import control_state, group_state, request_group, CONTROLS, VIC_KEYS, load_context


NOW = datetime(2026, 10, 12, 15, 0, tzinfo=timezone.utc)


def envelope(enabled=True):
    values = {key: enabled for key in CONTROLS}
    return {'desired': {'revision': 4, 'controls': values.copy(), 'updated_at': NOW.isoformat()},
            'applied': {'revision': 4, 'controls': values.copy(), 'observed_at': NOW.isoformat(),
                        'services': {key: {'state': 'RUNNING', 'heartbeat_at': NOW.isoformat(), 'control_revision': 4}
                                     for key in ('qqq', 'overnight', 'vic', 'beta')}}}


class ControlStateTests(unittest.TestCase):
    def test_exact_receipt_and_fresh_service_required_for_running(self):
        raw = envelope()
        self.assertEqual(control_state(raw, 'qqq_trading_enabled', NOW)['label'], 'ON · RUNNING')
        raw['applied']['revision'] = 3
        self.assertEqual(control_state(raw, 'qqq_trading_enabled', NOW)['label'], 'CHANGE PENDING')
        raw = envelope()
        raw['applied']['services']['qqq']['heartbeat_at'] = (NOW-timedelta(minutes=3)).isoformat()
        self.assertEqual(control_state(raw, 'qqq_trading_enabled', NOW)['label'], 'ON · WAITING FOR SERVICE')

    def test_stale_and_future_receipts_never_report_running(self):
        for offset in (-100, 6):
            raw = envelope()
            raw['applied']['observed_at'] = (NOW+timedelta(seconds=offset)).isoformat()
            state = control_state(raw, 'beta_engine_enabled', NOW)
            self.assertFalse(state['online'])
            self.assertFalse(state['acknowledged'])

    def test_received_boolean_and_revision_are_strict(self):
        raw = envelope()
        raw['applied']['controls']['vic_enabled'] = False
        self.assertEqual(control_state(raw, 'vic_enabled', NOW)['label'], 'CHANGE PENDING')
        raw['desired']['revision'] = True
        self.assertEqual(control_state(raw, 'vic_enabled', NOW)['label'], 'NOT CONNECTED')

    def test_off_retains_monitoring_and_does_not_claim_process_stopped(self):
        raw = envelope(False)
        self.assertEqual(control_state(raw, 'qqq_trading_enabled', NOW)['label'], 'OFF · POSITION MONITORING')
        self.assertEqual(control_state(raw, 'beta_engine_enabled', NOW)['label'], 'OFF · POSITION MONITORING')
        self.assertEqual(control_state(raw, 'qqq_research_enabled', NOW)['label'], 'OFF')

    def test_child_must_acknowledge_unless_confirmed_stopped(self):
        raw = envelope(False)
        raw['applied']['services']['beta']['control_revision'] = 3
        self.assertEqual(control_state(raw, 'beta_engine_enabled', NOW)['label'], 'CHANGE PENDING')
        raw['applied']['services']['beta']['state'] = 'STOPPED'
        self.assertEqual(control_state(raw, 'beta_engine_enabled', NOW)['label'], 'OFF')

    def test_error_and_missing_status_never_running(self):
        raw = envelope()
        raw['applied']['services']['beta']['state'] = 'ERROR'
        self.assertEqual(control_state(raw, 'beta_engine_enabled', NOW)['label'], 'NEEDS ATTENTION')
        self.assertEqual(control_state({}, 'beta_engine_enabled', NOW)['label'], 'NOT CONNECTED')

    def test_vic_has_distinct_receipt(self):
        raw = envelope()
        raw['applied']['services']['vic']['state'] = 'STOPPED'
        self.assertEqual(control_state(raw, 'vic_enabled', NOW)['label'], 'ON · WAITING FOR SERVICE')
        self.assertEqual(control_state(raw, 'qqq_trading_enabled', NOW)['label'], 'ON · RUNNING')

    def test_ui_buttons_send_one_fixed_request_and_wait_for_ack(self):
        from streamlit.testing.v1 import AppTest
        script = '''
from datetime import datetime,timezone
import streamlit as st
from operations_panel import render_controls, render_connection, CONTROLS
values={key:False for key in CONTROLS}
class Client:
    def request_controls(self,changes,expected_revision,request_id):
        st.session_state['sent']={'changes':changes,'expected_revision':expected_revision,'request_id':request_id}
now=datetime.now(timezone.utc).isoformat()
context={'client':Client(),'error':None,'envelope':{'desired':{'revision':4,'controls':values},'applied':{'revision':4,'controls':values,'observed_at':now,'services':{}}}}
render_connection(context)
render_controls(context,'qqq')
render_controls(context,'beta')
'''
        at = AppTest.from_string(script).run(timeout=20)
        self.assertEqual(len(at.exception), 0)
        self.assertEqual(len(at.button), 5)
        self.assertEqual({b.key for b in at.button}, {'control_all_services', 'control_on_vic', 'control_off_vic', 'control_on_beta_engine_enabled', 'control_off_beta_engine_enabled'})
        at.button(key='control_all_services').click().run()
        self.assertEqual(at.session_state['sent']['changes'], {key: True for key in CONTROLS})
        self.assertEqual(at.session_state['sent']['expected_revision'], 4)
        at.button(key='control_on_vic').click().run()
        self.assertEqual(at.session_state['sent']['changes'], {key: True for key in VIC_KEYS})
        at.button(key='control_on_beta_engine_enabled').click().run()
        self.assertEqual(len(at.exception), 0)
        self.assertEqual(at.session_state['sent']['changes'], {'beta_engine_enabled': True})
        self.assertEqual(at.session_state['sent']['expected_revision'], 4)
        self.assertTrue(any('Waiting for the Mac to acknowledge' in item.value for item in at.info))

    def test_offline_ui_allows_off_request_but_disables_on(self):
        from streamlit.testing.v1 import AppTest
        script = '''
import streamlit as st
from operations_panel import render_controls,CONTROLS
values={key:True for key in CONTROLS}
context={'client':object(),'error':None,'envelope':{'desired':{'revision':4,'controls':values},'applied':None}}
render_controls(context,'qqq')
'''
        at = AppTest.from_string(script).run(timeout=15)
        self.assertEqual(len(at.exception), 0)
        self.assertTrue(at.button(key='control_on_vic').disabled)
        self.assertFalse(at.button(key='control_off_vic').disabled)


class GroupStateTests(unittest.TestCase):
    def test_vic_waits_for_every_child_and_keeps_beta_independent(self):
        for service in ('qqq','overnight','vic'):
            raw=envelope()
            raw['applied']['services'][service]['control_revision']=3
            self.assertEqual(group_state(raw,'vic',NOW)['label'],'CHANGE PENDING')
            self.assertEqual(group_state(raw,'beta',NOW)['label'],'ON · RUNNING')
        raw=envelope()
        raw['applied']['controls']['beta_engine_enabled']=False
        self.assertEqual(group_state(raw,'vic',NOW)['label'],'ON · RUNNING')
        self.assertEqual(group_state(raw,'master',NOW)['label'],'CHANGE PENDING')

    def test_stale_heartbeat_and_error_never_become_running(self):
        for service in ('qqq','overnight','vic'):
            raw=envelope()
            raw['applied']['services'][service]['heartbeat_at']=(NOW-timedelta(minutes=3)).isoformat()
            self.assertEqual(group_state(raw,'vic',NOW)['label'],'ON · WAITING FOR SERVICE')
            raw['applied']['services'][service]['state']='ERROR'
            self.assertEqual(group_state(raw,'vic',NOW)['label'],'NEEDS ATTENTION')
        raw=envelope()
        raw['applied']['observed_at']=(NOW-timedelta(minutes=3)).isoformat()
        self.assertEqual(group_state(raw,'vic',NOW)['label'],'MAC OFFLINE / UNCONFIRMED')

    def test_mixed_is_never_on_and_off_preserves_monitoring(self):
        raw=envelope()
        for section in ('desired','applied'):raw[section]['controls']['vic_enabled']=False
        state=group_state(raw,'vic',NOW)
        self.assertTrue(state['mixed'])
        self.assertEqual(state['label'],'MIXED')
        self.assertEqual(group_state(envelope(False),'vic',NOW)['label'],'OFF · POSITION MONITORING')

    def test_callback_rechecks_stale_on_but_sends_atomic_off(self):
        from unittest.mock import Mock
        raw=envelope()
        client=Mock()
        context={'client':client,'envelope':raw}
        with patch('operations_panel.st.session_state',{}):
            request_group(context,'vic',True)
            client.request_controls.assert_not_called()
            request_group(context,'vic',False)
            self.assertEqual(client.request_controls.call_args.args,({key:False for key in VIC_KEYS},))
            self.assertEqual(client.request_controls.call_args.kwargs['expected_revision'],4)

    def test_boolean_revision_is_not_an_acknowledgement(self):
        raw=envelope()
        raw['desired']['revision']=1
        raw['applied']['revision']=True
        for service in raw['applied']['services'].values():service['control_revision']=1
        self.assertEqual(group_state(raw,'vic',NOW)['label'],'CHANGE PENDING')
        raw['applied']['revision']=1
        raw['applied']['services']['qqq']['control_revision']=True
        self.assertEqual(group_state(raw,'vic',NOW)['label'],'CHANGE PENDING')


if __name__ == '__main__':
    unittest.main()
